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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules.require_port_for_service import class_methods, is_data_type, self_stored_parameters


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ClassSummary, ProjectIndexSet, SourceUnit, SymbolRef


@final
class RequirePublicDependencyContract(ProjectRule):
    id = "require-public-dependency-contract"
    code = "SARJ466"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Reuse an existing substitutable contract instead of its concrete implementation annotation.",
        rationale="A concrete dependency annotation obstructs substitution even when an existing public contract already has multiple implementations.",
        remediation="Annotate the dependency with the existing public contract; do not create a new interface.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a resolved direct public ABC or Protocol base with multiple owned implementations explicitly covering its public operations.",
            "Only directly retained constructor dependencies used exclusively through the contract's declared operations are checked; parameter aliases or other constructor uses are excluded.",
            "Private consumer-owned Protocols, unresolved bases, indirect inheritance, single implementations, data-only dependencies, tests, and generated files are excluded.",
        ),
        examples=tuple(
            RuleExample(
                example_id=f"existing-contract-{annotation.lower()}",
                title="Use the existing substitutable publisher contract"
                if expected
                else "The consumer already uses the existing contract",
                outcome=ExampleOutcome.MATCH if expected else ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "# package\n"),
                    ExampleFile.python(
                        "app/publisher.py",
                        "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n"
                        "    @abstractmethod\n    def publish(self) -> None: ...\n"
                        "class HttpPublisher(Publisher):\n    def publish(self) -> None: ...\n"
                        "class QueuePublisher(Publisher):\n    def publish(self) -> None: ...\n",
                    ),
                    ExampleFile.python(
                        "app/consumer.py",
                        "from app.publisher import Publisher, HttpPublisher\nclass Consumer:\n"
                        f"    def __init__(self, publisher: {annotation}) -> None: self.publisher = publisher\n"
                        "    def run(self) -> None: self.publisher.publish()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/consumer.py"),
                expected_count=expected,
                public=True,
            )
            for annotation, expected in (("HttpPublisher", 1), ("Publisher", 0))
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path) or context.session.project is None:
            return []
        diagnostics: list[Diagnostic] = []
        for node in context.tree.body:
            if isinstance(node, ast.ClassDef):
                diagnostics.extend(self._check_class(node, context))
        return diagnostics

    def _check_class(self, node: ast.ClassDef, context: PythonFileContext) -> list[Diagnostic]:
        if node.name.startswith("_") or is_data_type(node):
            return []
        constructor = next((method for method in class_methods(node) if method.name == "__init__"), None)
        if constructor is None:
            return []
        stored = self_stored_parameters(constructor, context.imports)
        diagnostics: list[Diagnostic] = []
        for parameter in (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs):
            fields = stored.fields_by_parameter.get(parameter.arg)
            if fields is None or not _only_retains_parameter(constructor, parameter.arg, fields):
                continue
            diagnostic = self._check_parameter(node, parameter, fields, context)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
        return diagnostics

    def _check_parameter(
        self, node: ast.ClassDef, parameter: ast.arg, fields: frozenset[str], context: PythonFileContext
    ) -> Diagnostic | None:
        project = context.session.project
        if project is None or parameter.annotation is None:
            return None
        unit = project.unit(context.path)
        reference = annotation_reference(parameter.annotation)
        if unit is None or reference is None or is_suppressed(context.source_lines, parameter.lineno, self.code):
            return None
        implementation = project.class_for(unit, reference)
        if implementation is None:
            return None
        contract = _existing_substitutable_contract(implementation, project)
        members = _dependency_members(node, fields, context)
        if contract is None or members is None or not members <= _public_operations(contract):
            return None
        return Diagnostic(
            path=context.path,
            line=parameter.lineno,
            col=parameter.col_offset + 1,
            code=self.code,
            severity=Severity.WARNING,
            message=f"`{parameter.arg}` uses concrete `{implementation.symbol.name}` despite an existing substitutable `{contract.name}` contract; annotate with that existing contract.",
        )


def _only_retains_parameter(
    constructor: ast.FunctionDef | ast.AsyncFunctionDef, parameter: str, fields: frozenset[str]
) -> bool:
    allowed: set[ast.Name] = set()
    for statement in constructor.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        value = statement.value
        if not isinstance(value, ast.Name) or value.id != parameter:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if all(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr in fields
            for target in targets
        ):
            allowed.add(value)
    return all(node in allowed for node in ast.walk(constructor) if isinstance(node, ast.Name) and node.id == parameter)


def _existing_substitutable_contract(implementation: ClassSummary, project: ProjectIndexSet) -> ast.ClassDef | None:
    unit = project.source_unit(implementation.symbol.module)
    if unit is None:
        return None
    declaration = _declaration(unit, implementation.symbol.name)
    if declaration is None or is_data_type(declaration):
        return None
    implemented = _concrete_operations(declaration, unit)
    candidates: list[ast.ClassDef] = []
    for base in implementation.bases:
        candidate = _substitutable_base(base, implementation, implemented, project)
        if candidate is not None:
            candidates.append(candidate)
    return candidates[0] if len(candidates) == 1 else None


def _substitutable_base(
    base: SymbolRef, implementation: ClassSummary, implemented: frozenset[str], project: ProjectIndexSet
) -> ast.ClassDef | None:
    unit = project.source_unit(base.module)
    if unit is None:
        return None
    declaration = _declaration(unit, base.name)
    if declaration is None or not _is_public_contract(declaration, unit):
        return None
    operations = _public_operations(declaration)
    if not operations or not operations <= implemented:
        return None
    for path, name in project.direct_subclasses(unit, base.name):
        alternative_unit = project.unit(path)
        if alternative_unit is None:
            continue
        if alternative_unit.module == implementation.symbol.module and name == implementation.symbol.name:
            continue
        alternative = _declaration(alternative_unit, name)
        if alternative is not None and operations <= _concrete_operations(alternative, alternative_unit):
            return declaration
    return None


def _is_public_contract(declaration: ast.ClassDef, unit: SourceUnit) -> bool:
    if unit.tree is None or declaration.name.startswith("_"):
        return False
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    abstract_methods = _abstract_operations(declaration, imports)
    if any(name.startswith("_") for name in abstract_methods):
        return False
    if any(imports.resolves(parent, sources=TYPING_SOURCES, symbol="Protocol") for parent in declaration.bases):
        return True
    return bool(abstract_methods) and any(
        imports.resolves(parent, sources=ABC_SOURCES, symbol="ABC") for parent in declaration.bases
    )


def _concrete_operations(declaration: ast.ClassDef, unit: SourceUnit) -> frozenset[str]:
    if unit.tree is None:
        return frozenset()
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    return frozenset() if _abstract_operations(declaration, imports) else _public_operations(declaration)


def _public_operations(declaration: ast.ClassDef) -> frozenset[str]:
    return frozenset(method.name for method in class_methods(declaration) if not method.name.startswith("_"))


def _abstract_operations(declaration: ast.ClassDef, imports: ImportIndex) -> frozenset[str]:
    return frozenset(
        method.name
        for method in class_methods(declaration)
        if any(imports.resolves(dec, sources=ABC_SOURCES, symbol="abstractmethod") for dec in method.decorator_list)
    )


def _declaration(unit: SourceUnit, name: str) -> ast.ClassDef | None:
    if unit.tree is None:
        return None
    return next((node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == name), None)


def _dependency_members(
    node: ast.ClassDef, fields: frozenset[str], context: PythonFileContext
) -> frozenset[str] | None:
    members: set[str] = set()
    called = False
    for method in class_methods(node):
        for child in ast.walk(method):
            if _dependency_field_escapes(child, fields, context):
                return None
            target = child.func if isinstance(child, ast.Call) else child
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Attribute)
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"
                and target.value.attr in fields
            ):
                members.add(target.attr)
                called |= isinstance(child, ast.Call) and not method.name.startswith("_")
    return frozenset(members) if called else None


def _dependency_field_escapes(node: ast.AST, fields: frozenset[str], context: PythonFileContext) -> bool:
    if not (
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in fields
    ):
        return False
    parent = context.parents.get(node)
    return not (isinstance(parent, ast.Attribute) and parent.value is node)
