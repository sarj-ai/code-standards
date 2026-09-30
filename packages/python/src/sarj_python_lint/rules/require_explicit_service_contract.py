from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._imports import ABC_SOURCES, TYPING_SOURCES, ImportIndex
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._project_index import SourceUnit, SymbolRef
from sarj_python_lint.rules.require_port_for_service import (
    called_self_field,
    class_methods,
    is_data_type,
    self_stored_parameters,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet


@final
class RequireExplicitServiceContract(ProjectRule):
    id = "require-explicit-service-contract"
    code = "SARJ465"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require an explicit contract for a service that invokes a retained collaborator.",
        rationale=(
            "A one-operation service can orchestrate other services without declaring "
            "the contract that its callers and fakes must implement."
        ),
        remediation="Declare a public ABC for the service operation and explicitly inherit it.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module-level service, store, and provider roles with a direct constructor assignment and a public operation that invokes the retained collaborator are checked.",
            "Imported or dynamic base classes are unresolved and are not treated as missing contracts.",
            "Generated code, test classes, and data classes are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="single-operation-service-without-contract",
                title="One service operation still needs its contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class OrchestratorService:\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-single-operation-contract",
                title="The service declares its operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from abc import ABC, abstractmethod\n"
                        "class Runner(ABC):\n"
                        "    @abstractmethod\n"
                        "    def run(self) -> None: ...\n"
                        "class OrchestratorService(Runner):\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated or is_test_path(context.path):
            return []
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        diagnostics: list[Diagnostic] = []
        for node in classes.values():
            if node.name.startswith("_") or is_data_type(node) or not _is_service_role(node, context):
                continue
            operations = _collaborator_operations(node, context)
            if not operations:
                continue
            if _contract_status(node, operations, classes, context) is not False:
                continue
            start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
            if any(is_suppressed(context.source_lines, line, self.code) for line in range(start, node.lineno + 1)):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"`{node.name}` invokes a retained collaborator from "
                        f"{', '.join(sorted(operations))} without inheriting a public ABC covering its service operations."
                    ),
                )
            )
        return diagnostics


BOUNDARY_SUFFIXES = (
    "Service",
    "ServiceImpl",
    "Store",
    "Repository",
    "Provider",
    "Executor",
    "Enqueuer",
    "Runner",
    "Platform",
    "Manager",
    "ManagerImpl",
    "Control",
    "Refresher",
    "Reader",
    "Settlement",
    "Retry",
    "Stop",
    "Catalog",
    "DAO",
)
_NON_SERVICE_SUFFIXES = ("Router", "Middleware", "Builder")
BOUNDARY_DIRECTORIES = frozenset({"services", "stores", "providers", "repositories"})
_NON_SERVICE_DIRECTORIES = frozenset({"routers", "middleware", "scripts"})


def _is_service_role(node: ast.ClassDef, context: PythonFileContext) -> bool:
    parts = frozenset(context.path.parts)
    if parts & _NON_SERVICE_DIRECTORIES or node.name.endswith(_NON_SERVICE_SUFFIXES):
        return False
    return bool(parts & BOUNDARY_DIRECTORIES) or node.name.endswith(BOUNDARY_SUFFIXES)


def _collaborator_operations(node: ast.ClassDef, context: PythonFileContext) -> frozenset[str]:
    constructor = next((method for method in class_methods(node) if method.name == "__init__"), None)
    if constructor is None:
        return frozenset()
    stored = self_stored_parameters(constructor, context.imports)
    fields = frozenset(field for parameter_fields in stored.fields_by_parameter.values() for field in parameter_fields)
    return operations_for_fields(node, fields)


def operations_for_fields(node: ast.ClassDef, fields: frozenset[str]) -> frozenset[str]:
    if not fields:
        return frozenset()
    methods = class_methods(node)
    callers: dict[str, set[str]] = defaultdict(set)
    reaches_collaborator: set[str] = set()
    for method in methods:
        visitor = _CollaboratorCalls(fields)
        for statement in method.body:
            visitor.visit(statement)
        if visitor.found:
            reaches_collaborator.add(method.name)
        for callee in visitor.calledclass_methods:
            callers[callee].add(method.name)
    pending = deque(reaches_collaborator)
    while pending:
        for caller in callers[pending.popleft()] - reaches_collaborator:
            reaches_collaborator.add(caller)
            pending.append(caller)
    return frozenset(
        method.name for method in methods if not method.name.startswith("_") and method.name in reaches_collaborator
    )


@final
class _CollaboratorCalls(ast.NodeVisitor):
    def __init__(self, fields: frozenset[str]) -> None:
        self.fields = fields
        self.found = False
        self.calledclass_methods: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if called_self_field(node.func) in self.fields:
            self.found = True
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            self.calledclass_methods.add(node.func.attr)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Constant):
            for statement in node.body if node.test.value else node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)


def _contract_status(
    node: ast.ClassDef,
    operations: frozenset[str],
    classes: dict[str, ast.ClassDef],
    context: PythonFileContext,
) -> bool | None:
    surfaces: set[str] = set()
    unknown = False
    project = context.session.project
    unit = project.unit(context.path) if project is not None else None
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "object":
            continue
        if context.imports.resolves(base, sources=ABC_SOURCES, symbol="ABC"):
            continue
        if context.imports.resolves(base, sources=TYPING_SOURCES, symbol="Generic"):
            continue
        resolved = _resolve_base(base, classes, context.imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        declaration, source_unit, source_imports = resolved
        if declaration.name.startswith("_"):
            continue
        contract = _contract_surface(declaration, source_unit, source_imports, project, set())
        surfaces.update(contract.operations)
        unknown |= contract.unresolved
    return True if operations <= surfaces else None if unknown else False


def _resolve_base(
    base: ast.expr,
    classes: dict[str, ast.ClassDef],
    imports: ImportIndex,
    project: ProjectIndexSet | None,
    unit: SourceUnit | None,
) -> tuple[ast.ClassDef, SourceUnit | None, ImportIndex] | None:
    if isinstance(base, ast.Name) and base.id in classes:
        return classes[base.id], unit, imports
    if project is None or unit is None:
        return None
    summary = project.class_for(unit, base)
    if summary is None:
        return None
    stable = imports.resolved_qualified_name(base)
    if stable != f"{summary.symbol.module}.{summary.symbol.name}":
        return None
    source_unit = project.source_unit(summary.symbol.module)
    if source_unit is None or source_unit.tree is None:
        return None
    declaration = next(
        (item for item in source_unit.tree.body if isinstance(item, ast.ClassDef) and item.name == summary.symbol.name),
        None,
    )
    if declaration is None:
        return None
    return declaration, source_unit, ImportIndex.from_tree(source_unit.tree, module_scope_only=True)


@dataclass(frozen=True)
class _ContractSurface:
    operations: frozenset[str]
    unresolved: bool


def _contract_surface(
    declaration: ast.ClassDef,
    unit: SourceUnit | None,
    imports: ImportIndex,
    project: ProjectIndexSet | None,
    seen: set[SymbolRef],
) -> _ContractSurface:
    if unit is not None and unit.module is not None:
        symbol = SymbolRef(unit.module, declaration.name)
        if symbol in seen:
            return _ContractSurface(operations=frozenset(), unresolved=True)
        seen.add(symbol)
    abc = any(imports.resolves(base, sources=ABC_SOURCES, symbol="ABC") for base in declaration.bases)
    surface: set[str] = _public_operations(declaration) if abc else set()
    unknown = False
    local_classes = (
        {item.name: item for item in unit.tree.body if isinstance(item, ast.ClassDef)}
        if unit is not None and unit.tree is not None
        else {declaration.name: declaration}
    )
    for base in declaration.bases:
        if imports.resolves(base, sources=TYPING_SOURCES, symbol="Protocol") or imports.resolves(
            base, sources=ABC_SOURCES, symbol="ABC"
        ):
            continue
        resolved = _resolve_base(base, local_classes, imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        ancestor, ancestor_unit, ancestor_imports = resolved
        ancestor_surface = _contract_surface(ancestor, ancestor_unit, ancestor_imports, project, seen.copy())
        surface.update(ancestor_surface.operations)
        unknown |= ancestor_surface.unresolved
    return _ContractSurface(operations=frozenset(surface), unresolved=unknown)


def _public_operations(declaration: ast.ClassDef) -> set[str]:
    return {method.name for method in class_methods(declaration) if not method.name.startswith("_")}
