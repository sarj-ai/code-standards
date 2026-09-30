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
from sarj_python_lint.rules.require_explicit_service_contract import (
    BOUNDARY_DIRECTORIES,
    BOUNDARY_SUFFIXES,
    operations_for_fields,
)
from sarj_python_lint.rules.require_port_for_service import (
    class_methods,
    is_data_type,
    self_stored_parameters,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class RequirePublicDependencyContract(ProjectRule):
    id = "require-public-dependency-contract"
    code = "SARJ466"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use a public contract to type an injected behavioral collaborator.",
        rationale="A private protocol or concrete service annotation hides the dependency's substitutable contract from callers and fakes.",
        remediation="Publish a focused ABC or Protocol and annotate the constructor parameter with it.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a public owned class, a directly retained typed constructor parameter, and a public operation invoking it.",
            "Unresolved, third-party, data-only, generated, and test-only declarations are not diagnosed.",
        ),
        examples=(
            RuleExample(
                example_id="private-publisher-protocol",
                title="A public consumer hides its publisher contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/enqueuer.py",
                        "from typing import Protocol\n"
                        "class _Publisher(Protocol):\n"
                        "    def publish(self) -> None: ...\n"
                        "class Enqueuer:\n"
                        "    def __init__(self, publisher: _Publisher) -> None:\n"
                        "        self.publisher = publisher\n"
                        "    def enqueue(self) -> None:\n"
                        "        self.publisher.publish()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/enqueuer.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="public-publisher-protocol",
                title="The publisher contract is public",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/enqueuer.py",
                        "from typing import Protocol\n"
                        "class Publisher(Protocol):\n"
                        "    def publish(self) -> None: ...\n"
                        "class Enqueuer:\n"
                        "    def __init__(self, publisher: Publisher) -> None:\n"
                        "        self.publisher = publisher\n"
                        "    def enqueue(self) -> None:\n"
                        "        self.publisher.publish()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/enqueuer.py"),
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
            diagnostics.extend(self._check_class(node, classes, context))
        return diagnostics

    def _check_class(
        self, node: ast.ClassDef, classes: dict[str, ast.ClassDef], context: PythonFileContext
    ) -> list[Diagnostic]:
        if node.name.startswith("_") or is_data_type(node):
            return []
        constructor = next((method for method in class_methods(node) if method.name == "__init__"), None)
        if constructor is None:
            return []
        stored = self_stored_parameters(constructor, context.imports)
        parameters = (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs)
        return [
            diagnostic
            for parameter in parameters
            if (diagnostic := self._check_parameter(node, parameter, stored.fields_by_parameter, classes, context))
            is not None
        ]

    def _check_parameter(
        self,
        node: ast.ClassDef,
        parameter: ast.arg,
        fields_by_parameter: dict[str, frozenset[str]],
        classes: dict[str, ast.ClassDef],
        context: PythonFileContext,
    ) -> Diagnostic | None:
        fields = fields_by_parameter.get(parameter.arg)
        if fields is None or parameter.annotation is None or not operations_for_fields(node, fields):
            return None
        reference = annotation_reference(parameter.annotation)
        if reference is None:
            return None
        reason = _hidden_dependency(reference, classes, context)
        if reason is None or is_suppressed(context.source_lines, parameter.lineno, self.code):
            return None
        return Diagnostic(
            path=context.path,
            line=parameter.lineno,
            col=parameter.col_offset + 1,
            code=self.code,
            severity=Severity.WARNING,
            message=f"`{parameter.arg}` uses {reason}; type this behavioral dependency with a public ABC or Protocol.",
        )


def _hidden_dependency(
    reference: ast.Name | ast.Attribute, classes: dict[str, ast.ClassDef], context: PythonFileContext
) -> str | None:
    if (
        isinstance(reference, ast.Name)
        and reference.id.startswith("_")
        and reference.id in classes
        and not is_data_type(classes[reference.id])
    ):
        return f"private local contract `{reference.id}`"
    project = context.session.project
    if project is None:
        return None
    # ProjectIndexSet resolves only declarations that exist in the scanned first-party source.
    source_unit = project.unit(context.path)
    if source_unit is None:
        return None
    summary = project.class_for(source_unit, reference)
    if summary is None:
        return None
    declaration_unit = project.source_unit(summary.symbol.module)
    if declaration_unit is None or declaration_unit.tree is None:
        return None
    declaration = _class_named(declaration_unit.tree, summary.symbol.name)
    if declaration is None or is_data_type(declaration):
        return None
    if declaration.name.startswith("_"):
        return f"private first-party contract `{declaration.name}`"
    imports = ImportIndex.from_tree(declaration_unit.tree, module_scope_only=True)
    if any(
        imports.resolves(base, sources=ABC_SOURCES, symbol="ABC")
        or imports.resolves(base, sources=TYPING_SOURCES, symbol="Protocol")
        for base in declaration.bases
    ):
        return None
    if declaration.name.endswith(BOUNDARY_SUFFIXES) or BOUNDARY_DIRECTORIES.intersection(declaration_unit.path.parts):
        return f"owned concrete service `{declaration.name}`"
    return None


def _class_named(tree: ast.Module, name: str) -> ast.ClassDef | None:
    return next((item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name), None)
