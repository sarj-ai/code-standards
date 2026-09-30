from __future__ import annotations

import ast
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
from sarj_python_lint.rules._contract_annotation import annotation_reference
from sarj_python_lint.rules._imports import ABC_SOURCES, TYPING_SOURCES, ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ClassSummary, ProjectIndexSet, SourceUnit, SymbolRef


@final
class RequireExplicitContractImplementation(ProjectRule):
    id = "require-explicit-contract-implementation"
    code = "SARJ467"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require owned substitutes to explicitly inherit their injected contract.",
        rationale=(
            "Structural matching only checks a fake where it is passed. Explicit inheritance makes its obligation "
            "visible at the class declaration and catches missing abstract operations at instantiation."
        ),
        remediation="Make the owned implementation inherit the exact ABC or Protocol expected by the consumer.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct constructor arguments and unreassigned local constructor results supplied to a resolvable typed parameter are checked.",
            "Dynamic factories, containers, casts, unresolved or multiple owned ABC ancestry, and third-party implementations are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="structural-fake-at-injection",
                title="A fake is supplied without declaring its contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "# package\n"),
                    ExampleFile.python(
                        "app/consumer.py",
                        "from typing import Protocol\nclass Publisher(Protocol):\n    def publish(self) -> None: ...\nclass Consumer:\n    def __init__(self, publisher: Publisher) -> None:\n        self.publisher = publisher\n",
                    ),
                    ExampleFile.python("app/fake.py", "class FakePublisher:\n    def publish(self) -> None: ...\n"),
                    ExampleFile.python(
                        "app/usage.py",
                        "from app.consumer import Consumer\nfrom app.fake import FakePublisher\ndef setup() -> None:\n    Consumer(publisher=FakePublisher())\n",
                    ),
                ),
                focus_path=PurePosixPath("app/usage.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-fake-at-injection",
                title="The fake declares the actual contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "# package\n"),
                    ExampleFile.python(
                        "app/consumer.py",
                        "from typing import Protocol\nclass Publisher(Protocol):\n    def publish(self) -> None: ...\nclass Consumer:\n    def __init__(self, publisher: Publisher) -> None:\n        self.publisher = publisher\n",
                    ),
                    ExampleFile.python(
                        "app/fake.py",
                        "from app.consumer import Publisher\nclass FakePublisher(Publisher):\n    def publish(self) -> None: ...\n",
                    ),
                    ExampleFile.python(
                        "app/usage.py",
                        "from app.consumer import Consumer\nfrom app.fake import FakePublisher\ndef setup() -> None:\n    Consumer(publisher=FakePublisher())\n",
                    ),
                ),
                focus_path=PurePosixPath("app/usage.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or context.session.project is None:
            return []
        project = context.session.project
        unit = project.unit_or_source(context.path, context.source, context.tree)
        if unit is None:
            return []
        visitor = _InjectionVisitor(context, unit, project, self.code)
        visitor.visit(context.tree)
        return visitor.findings


@final
class _InjectionVisitor(ast.NodeVisitor):
    def __init__(self, context: PythonFileContext, unit: SourceUnit, project: ProjectIndexSet, code: str) -> None:
        self.context = context
        self.unit = unit
        self.project = project
        self.code = code
        self.findings: list[Diagnostic] = []
        self.origins: dict[str, ClassSummary] = {}
        self.local_any_names: frozenset[str] = frozenset()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.origins
        previous_any = self.local_any_names
        self.origins = {}
        self.local_any_names = frozenset(
            alias.asname or alias.name
            for statement in node.body
            if isinstance(statement, ast.ImportFrom) and statement.module in {"typing", "typing_extensions"}
            for alias in statement.names
            if alias.name == "Any"
        )
        for statement in node.body:
            self.visit(statement)
        self.origins = previous
        self.local_any_names = previous_any

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        origin = self._origin(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if origin is None:
                    self.origins.pop(target.id, None)
                else:
                    self.origins[target.id] = origin
            else:
                for name in (item.id for item in ast.walk(target) if isinstance(item, ast.Name)):
                    self.origins.pop(name, None)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            if self.context.imports.resolves(node.annotation, sources=TYPING_SOURCES, symbol="Any") or (
                isinstance(node.annotation, ast.Name) and node.annotation.id in self.local_any_names
            ):
                self.origins.pop(node.target.id, None)
                return
            origin = self._origin(node.value)
            if origin is None:
                self.origins.pop(node.target.id, None)
            else:
                self.origins[node.target.id] = origin

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = self.origins.copy()
        for statement in node.body:
            self.visit(statement)
        after_body = self.origins
        self.origins = before.copy()
        for statement in node.orelse:
            self.visit(statement)
        after_else = self.origins
        self.origins = {name: origin for name, origin in after_body.items() if after_else.get(name) == origin}

    def visit_For(self, node: ast.For) -> None:
        self._visit_uncertain_flow(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_uncertain_flow(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_uncertain_flow(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_uncertain_flow(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._visit_uncertain_flow(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._visit_uncertain_flow(node)

    def _visit_uncertain_flow(self, node: ast.stmt) -> None:
        self.generic_visit(node)
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                self.origins.pop(child.id, None)

    def visit_Call(self, node: ast.Call) -> None:
        target = self.project.class_for(self.unit, node.func)
        if target is not None:
            target_unit = self.project.source_unit(target.symbol.module)
            if target_unit is not None and target_unit.tree is not None:
                declaration = next(
                    (
                        item
                        for item in target_unit.tree.body
                        if isinstance(item, ast.ClassDef) and item.name == target.symbol.name
                    ),
                    None,
                )
                if declaration is not None:
                    self._check_constructor(node, declaration, target_unit)
        self.generic_visit(node)

    def _check_constructor(self, call: ast.Call, declaration: ast.ClassDef, target_unit: SourceUnit) -> None:
        constructor = next(
            (item for item in declaration.body if isinstance(item, ast.FunctionDef) and item.name == "__init__"),
            None,
        )
        if constructor is None:
            return
        positional = [*constructor.args.posonlyargs, *constructor.args.args][1:]
        parameters = {argument.arg: argument for argument in (*positional, *constructor.args.kwonlyargs)}
        supplied = [
            (parameters.get(keyword.arg), keyword.value) for keyword in call.keywords if keyword.arg is not None
        ]
        supplied.extend((parameter, value) for parameter, value in zip(positional, call.args, strict=False))
        for parameter, value in supplied:
            self._check_argument(parameter, value, target_unit)

    def _check_argument(self, parameter: ast.arg | None, value: ast.expr, target_unit: SourceUnit) -> None:
        if parameter is None or parameter.annotation is None:
            return
        reference = annotation_reference(parameter.annotation)
        if reference is None:
            return
        contract = self.project.class_for(target_unit, reference)
        if contract is None or not _is_direct_contract(contract, self.project):
            return
        origin = self._origin(value)
        if origin is None:
            return
        inherits = _inherits_contract(origin, contract.symbol, self.project, set())
        if inherits is not False or is_suppressed(self.context.source_lines, value.lineno, self.code):
            return
        self.findings.append(
            Diagnostic(
                path=self.context.path,
                line=value.lineno,
                col=value.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"`{origin.symbol.name}` is supplied as `{contract.symbol.name}` without explicitly "
                    "inheriting that contract. Declare the relationship on the implementation class."
                ),
            )
        )

    def _origin(self, value: ast.expr) -> ClassSummary | None:
        if isinstance(value, ast.Name):
            return self.origins.get(value.id)
        if isinstance(value, ast.Call):
            return self.project.class_for(self.unit, value.func)
        return None


def _is_direct_contract(summary: ClassSummary, project: ProjectIndexSet) -> bool:
    protocol = any(
        (base.module, base.name) in {("typing", "Protocol"), ("typing_extensions", "Protocol")}
        for base in summary.bases
    )
    unit = project.source_unit(summary.symbol.module)
    if unit is None or unit.tree is None:
        return False
    declaration = next(
        (item for item in unit.tree.body if isinstance(item, ast.ClassDef) and item.name == summary.symbol.name),
        None,
    )
    if declaration is None:
        return False
    if protocol and any(
        isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and not member.name.startswith("_")
        for member in declaration.body
    ):
        return True
    if not project.class_inherits_from(unit, summary.symbol.name, frozenset({"abc.ABC"})):
        return False
    return bool(_remaining_abstract_operations(summary, project, set()))


def _remaining_abstract_operations(summary: ClassSummary, project: ProjectIndexSet, seen: set[SymbolRef]) -> set[str]:
    if summary.symbol in seen:
        return set()
    seen.add(summary.symbol)
    unit = project.source_unit(summary.symbol.module)
    if unit is None or unit.tree is None:
        return set()
    declaration = next(
        (item for item in unit.tree.body if isinstance(item, ast.ClassDef) and item.name == summary.symbol.name),
        None,
    )
    if declaration is None:
        return set()
    owned_parents = [base for base in summary.bases if project.source_unit(base.module) is not None]
    if len(owned_parents) > 1:
        return set()
    abstract: set[str] = set()
    for base in summary.bases:
        parent_unit = project.source_unit(base.module)
        parent = project.class_for(parent_unit, ast.Name(id=base.name, ctx=ast.Load())) if parent_unit else None
        if parent is not None:
            abstract.update(_remaining_abstract_operations(parent, project, seen.copy()))
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    _apply_abstract_overrides(abstract, declaration, imports)
    return abstract


def _apply_abstract_overrides(abstract: set[str], declaration: ast.ClassDef, imports: ImportIndex) -> None:
    for member in declaration.body:
        if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) or member.name.startswith("_"):
            continue
        if any(imports.resolves(dec, sources=ABC_SOURCES, symbol="abstractmethod") for dec in member.decorator_list):
            abstract.add(member.name)
        else:
            abstract.discard(member.name)


def _inherits_contract(
    implementation: ClassSummary,
    target: SymbolRef,
    project: ProjectIndexSet,
    seen: set[SymbolRef],
) -> bool | None:
    if implementation.symbol == target:
        return True
    if implementation.symbol in seen:
        return None
    seen.add(implementation.symbol)
    unknown = False
    for base in implementation.bases:
        if base == target:
            return True
        if (base.module, base.name) in {("abc", "ABC"), ("typing", "Generic"), ("builtins", "object")}:
            continue
        unit = project.source_unit(base.module)
        ancestor = project.class_for(unit, ast.Name(id=base.name, ctx=ast.Load())) if unit is not None else None
        if ancestor is None:
            unknown = True
            continue
        relationship = _inherits_contract(ancestor, target, project, seen.copy())
        if relationship is True:
            return True
        unknown |= relationship is None
    return None if unknown else False
