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
from sarj_python_lint.rules.require_port_for_service import (
    annotation_tail,
    called_self_field,
    class_methods,
    is_data_type,
    self_stored_parameters,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit


@final
class RequireExplicitServiceContract(ProjectRule):
    id = "require-explicit-service-contract"
    code = "SARJ465"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require an explicit contract for a service that invokes a retained collaborator.",
        rationale=(
            "A one-operation service can orchestrate other services without declaring "
            "the contract that callers consume and implementations and fakes satisfy."
        ),
        remediation=(
            "Declare a focused ABC or Protocol covering the service operations and make that contract explicit "
            "on the implementation; reuse an existing contract instead of adding a nominal duplicate."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module-level service, store, and provider roles with a direct constructor assignment and a public operation that invokes the retained collaborator are checked.",
            "Resolvable inherited ABC and Protocol operations, including private and generic contracts, satisfy this policy; unresolved ancestry is not treated as a missing contract.",
            "Generated code, tests, data values, abstract declarations, descriptors, static/class helpers, and unknown rewriting decorators are excluded.",
            "The bounded analysis follows directly retained constructor parameters and private instance helpers; dynamic field aliases and structurally implemented Protocols declared only by external consumers are not inferred.",
            "Method signatures are checked by the type checker. The rule is an architectural warning and has no automatic rewrite.",
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
            RuleExample(
                example_id="explicit-protocol-contract",
                title="A focused Protocol already supplies the service contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Protocol\n"
                        "class _Runner(Protocol):\n"
                        "    def run(self) -> None: ...\n"
                        "class OrchestratorService(_Runner):\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=False,
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
            if (
                node.name.startswith("_")
                or is_data_type(node)
                or not _is_service_role(node, context)
                or not _known_decorators(node.decorator_list, context.imports)
                or _declares_abstract_operations(node, context.imports)
            ):
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
                        f"{', '.join(sorted(operations))} without a declared ABC or Protocol covering its service operations."
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
_NON_SERVICE_SUFFIXES = ("Router", "Middleware", "Builder", "Factory")
BOUNDARY_DIRECTORIES = frozenset({"services", "stores", "providers", "repositories"})
_NON_SERVICE_DIRECTORIES = frozenset({"routers", "middleware", "scripts"})
_BUILTIN_VALUES = frozenset(
    {
        "str",
        "int",
        "bool",
        "float",
        "complex",
        "bytes",
        "bytearray",
        "object",
        "None",
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "type",
    }
)
_VALUE_SOURCES = frozenset(
    {
        "typing",
        "typing_extensions",
        "collections.abc",
        "pathlib",
        "uuid",
        "datetime",
        "decimal",
        "fractions",
        "re",
        "logging",
    }
)
_IMPORTED_VALUES = frozenset(
    {
        "Any",
        "List",
        "Dict",
        "Set",
        "FrozenSet",
        "Tuple",
        "Type",
        "Text",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Iterable",
        "Iterator",
        "Collection",
        "Callable",
        "Path",
        "PurePath",
        "UUID",
        "datetime",
        "date",
        "time",
        "timedelta",
        "Decimal",
        "Fraction",
        "Pattern",
        "TextIO",
        "BinaryIO",
        "Literal",
        "Logger",
    }
)


def _is_service_role(node: ast.ClassDef, context: PythonFileContext) -> bool:
    parts = frozenset(context.path.parts)
    if parts & _NON_SERVICE_DIRECTORIES or node.name.endswith(_NON_SERVICE_SUFFIXES):
        return False
    for keyword in node.keywords:
        if keyword.arg is None:
            return False
        if keyword.arg != "metaclass":
            continue
        if context.imports.resolves(keyword.value, sources=ABC_SOURCES, symbol="ABCMeta"):
            continue
        if (
            isinstance(keyword.value, ast.Name)
            and keyword.value.id == "type"
            and context.imports.builtin_is_unshadowed("type")
        ):
            continue
        return False
    return bool(parts & BOUNDARY_DIRECTORIES) or node.name.endswith(BOUNDARY_SUFFIXES)


def _collaborator_operations(node: ast.ClassDef, context: PythonFileContext) -> frozenset[str]:
    constructor = next((method for method in class_methods(node) if method.name == "__init__"), None)
    if constructor is None or not _known_decorators(constructor.decorator_list, context.imports):
        return frozenset()
    stored = self_stored_parameters(constructor, context.imports)
    value_names: set[str] = (
        {item.name for item in context.tree.body if isinstance(item, ast.ClassDef) and is_data_type(item)}
        if context.tree is not None
        else set()
    )
    fields: set[str] = set()
    for parameter in (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs):
        if _is_value_parameter(parameter.annotation, context.imports, value_names):
            continue
        fields.update(stored.fields_by_parameter.get(parameter.arg, ()))
    return operations_for_fields(node, frozenset(fields), context.imports)


def _is_value_parameter(annotation: ast.expr | None, imports: ImportIndex, value_names: set[str]) -> bool:
    name = annotation_tail(annotation)
    if name in value_names:
        return True
    if name is not None and name in _BUILTIN_VALUES and imports.builtin_is_unshadowed(name):
        return True
    reference = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return reference is not None and imports.resolved_symbol(reference, sources=_VALUE_SOURCES) in _IMPORTED_VALUES


def operations_for_fields(node: ast.ClassDef, fields: frozenset[str], imports: ImportIndex) -> frozenset[str]:
    if not fields:
        return frozenset()
    methods = [method for method in class_methods(node) if _instance_operation(method, imports)]
    callers: dict[str, set[str]] = defaultdict(set)
    reaches_collaborator: set[str] = set()
    for method in methods:
        visitor = _CollaboratorCalls(fields)
        visitor.visit_statements(method.body)
        if visitor.invalidated:
            continue
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
        self.invalidated = False
        self.calledclass_methods: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "self" and isinstance(node.ctx, ast.Store | ast.Del):
            self.invalidated = True

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr in self.fields
        ):
            self.invalidated = True
        self.generic_visit(node)

    def visit_statements(self, statements: list[ast.stmt]) -> bool:
        for statement in statements:
            if isinstance(statement, ast.If):
                self.visit(statement.test)
                if isinstance(statement.test, ast.Constant):
                    branch = statement.body if statement.test.value else statement.orelse
                    falls_through = self.visit_statements(branch)
                else:
                    body_falls_through = self.visit_statements(statement.body)
                    else_falls_through = self.visit_statements(statement.orelse)
                    falls_through = body_falls_through or else_falls_through
                if not falls_through:
                    return False
                continue
            self.visit(statement)
            if isinstance(statement, ast.Return | ast.Raise | ast.Break | ast.Continue):
                return False
        return True

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
        self.visit_statements([node])

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        if not isinstance(node.test, ast.Constant) or node.test.value:
            self.visit_statements(node.body)
        self.visit_statements(node.orelse)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        for value in node.values:
            self.visit(value)
            if not isinstance(value, ast.Constant):
                continue
            if isinstance(node.op, ast.And) and not value.value:
                break
            if isinstance(node.op, ast.Or) and value.value:
                break

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        if isinstance(node.test, ast.Constant):
            self.visit(node.body if node.test.value else node.orelse)
            return
        self.visit(node.body)
        self.visit(node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        body_falls_through = self.visit_statements(node.body)
        for handler in node.handlers:
            self.visit_statements(handler.body)
        if body_falls_through:
            self.visit_statements(node.orelse)
        self.visit_statements(node.finalbody)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        # Creation evaluates the first iterable, while the generator body is deferred.
        self.visit(node.generators[0].iter)


def _known_decorators(decorators: list[ast.expr], imports: ImportIndex) -> bool:
    return all(
        imports.resolved_symbol(decorator, sources=TYPING_SOURCES) in {"final", "override", "runtime_checkable"}
        or imports.resolves(decorator, sources=ABC_SOURCES, symbol="abstractmethod")
        for decorator in decorators
    )


def _instance_operation(method: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    positional = [*method.args.posonlyargs, *method.args.args]
    return bool(positional) and positional[0].arg == "self" and _known_decorators(method.decorator_list, imports)


def _declares_abstract_operations(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(
        imports.resolves(decorator, sources=ABC_SOURCES, symbol="abstractmethod")
        for method in class_methods(node)
        for decorator in method.decorator_list
    )


def _declares_contract(node: ast.ClassDef, imports: ImportIndex) -> bool:
    bases = [base.value if isinstance(base, ast.Subscript) else base for base in node.bases]
    return any(
        imports.resolves(base, sources=ABC_SOURCES, symbol="ABC")
        or imports.resolves(base, sources=TYPING_SOURCES, symbol="Protocol")
        for base in bases
    ) or any(
        keyword.arg == "metaclass" and imports.resolves(keyword.value, sources=ABC_SOURCES, symbol="ABCMeta")
        for keyword in node.keywords
    )


def _neutral_base(base: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(base, ast.Name) and base.id == "object" and imports.builtin_is_unshadowed("object"):
        return True
    return imports.resolves(base, sources=ABC_SOURCES, symbol="ABC") or imports.resolved_symbol(
        base, sources=TYPING_SOURCES
    ) in {"Generic", "Protocol"}


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
    for expression in node.bases:
        base = expression.value if isinstance(expression, ast.Subscript) else expression
        if _neutral_base(base, context.imports):
            continue
        resolved = _resolve_base(base, classes, context.imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        declaration, source_unit, source_imports = resolved
        contract = _contract_surface(declaration, source_unit, source_imports, project, set(), classes=classes)
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
    base = base.value if isinstance(base, ast.Subscript) else base
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
    seen: set[ast.ClassDef],
    *,
    classes: dict[str, ast.ClassDef],
) -> _ContractSurface:
    if declaration in seen or not _known_decorators(declaration.decorator_list, imports):
        return _ContractSurface(operations=frozenset(), unresolved=True)
    seen.add(declaration)
    bases = [base.value if isinstance(base, ast.Subscript) else base for base in declaration.bases]
    surface: set[str] = _public_operations(declaration, imports) if _declares_contract(declaration, imports) else set()
    unknown = False
    local_classes = (
        {item.name: item for item in unit.tree.body if isinstance(item, ast.ClassDef)}
        if unit is not None and unit.tree is not None
        else classes
    )
    for base in bases:
        if _neutral_base(base, imports):
            continue
        resolved = _resolve_base(base, local_classes, imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        ancestor, ancestor_unit, ancestor_imports = resolved
        ancestor_surface = _contract_surface(
            ancestor, ancestor_unit, ancestor_imports, project, seen.copy(), classes=local_classes
        )
        surface.update(ancestor_surface.operations)
        unknown |= ancestor_surface.unresolved
    if surface and _declares_abstract_operations(declaration, imports):
        surface.update(_public_operations(declaration, imports))
    return _ContractSurface(operations=frozenset(surface), unresolved=unknown)


def _public_operations(declaration: ast.ClassDef, imports: ImportIndex) -> set[str]:
    return {
        method.name
        for method in class_methods(declaration)
        if not method.name.startswith("_") and _instance_operation(method, imports)
    }
