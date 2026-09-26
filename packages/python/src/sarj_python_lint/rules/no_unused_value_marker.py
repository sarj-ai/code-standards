from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


@final
class NoUnusedValueMarker(Rule):
    id = "no-unused-value-marker"
    code = "SARJ452"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not use standalone assignments to `_` to discard values.",
        rationale=(
            "A standalone `_ = value` assignment adds a binding without clarifying intent. A side-effecting call can "
            "be invoked directly. Pure references to formal parameters are excluded because callback and protocol "
            "signatures may require names that Ruff otherwise reports as unused."
        ),
        remediation=(
            "Invoke calls directly instead of assigning their result to `_`. Remove or rename locally owned unused "
            "values; when an external interface requires the exact unused parameter, put a narrow reasoned linter "
            "suppression on its declaration."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Plain and annotated assignments whose standalone target is `_` are reported, including chained assignments.",
            "Pure name or tuple references to the enclosing function's unchanged parameters are excluded.",
            "Unpacking placeholders, loop targets, wildcard imports, and underscore-prefixed names are excluded.",
            "Generated and vendored files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="callback-parameter-marker",
                title="A callback keeps its required parameter names",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "def render(root: Path, manifest: Path) -> str:\n    _ = root, manifest\n    return 'ready'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="discarded-nonparameter-value",
                title="A standalone discard binding is unnecessary",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/adapter.py", "value = 1\n_ = value\n"),),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="discarded-call-result",
                title="Invoke a call directly when its result is intentionally unused",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "_ = refresh_cache()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=1,
                public=True,
                scenario="call-result",
            ),
            RuleExample(
                example_id="direct-call",
                title="Run the call without creating a discard binding",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "refresh_cache()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=True,
                scenario="call-result",
            ),
            RuleExample(
                example_id="unpacking-placeholder",
                title="Keep a conventional placeholder inside unpacking",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "name, _ = load_pair()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if "_" not in source or "=" not in source or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        source_lines = context.source_lines
        markers = [
            node
            for node in context.nodes(ast.AST)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_unused_value_marker(node)
        ]
        if not markers:
            return []
        parents: Mapping[ast.AST, ast.AST] = (
            context.parents
            if any(isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Tuple)) for node in markers)
            else {}
        )
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "standalone assignment to `_` discards a value through an unnecessary binding — invoke calls "
                    "directly or address unused values at their declaration."
                ),
            )
            for node in markers
            if not _is_pure_parameter_marker(node, parents) and not is_suppressed(source_lines, node.lineno, self.code)
        ]


def _is_unused_value_marker(node: ast.Assign | ast.AnnAssign) -> bool:
    if isinstance(node, ast.AnnAssign):
        return node.value is not None and isinstance(node.target, ast.Name) and node.target.id == "_"
    return any(isinstance(target, ast.Name) and target.id == "_" for target in node.targets)


def _is_pure_parameter_marker(
    node: ast.Assign | ast.AnnAssign,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    if not isinstance(node.targets[0], ast.Name) or node.targets[0].id != "_":
        return False
    names = _marker_reference_names(node.value)
    if names is None:
        return False
    function = _enclosing_function(node, parents)
    if function is None:
        return False
    parameters = {argument.arg for argument in walk_ast(function.args) if isinstance(argument, ast.arg)}
    return names <= parameters and not any(
        isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store) and child.id in names
        for child in walk_ast(function)
    )


def _marker_reference_names(value: ast.expr) -> set[str] | None:
    values = value.elts if isinstance(value, ast.Tuple) else [value]
    if not values or not all(isinstance(item, ast.Name) for item in values):
        return None
    return {item.id for item in values if isinstance(item, ast.Name)}


def _enclosing_function(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None
