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


if TYPE_CHECKING:
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
            "be invoked directly. Reading unused parameters only to satisfy a linter hides whether a callback is "
            "intentionally inert or implements an incomplete contract."
        ),
        remediation=(
            "Invoke calls directly instead of assigning their result to `_`. Remove or rename locally owned unused "
            "values; when an external interface requires the exact unused parameter, put a narrow reasoned linter "
            "suppression on its declaration. Use an explicit empty body for an intentional stub, `@override` for "
            "a real override, or `NotImplementedError` for an unsupported operation; preserve required keyword names."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Plain and annotated assignments whose standalone target is `_` are reported, including chained assignments.",
            "Formal-parameter references are reported too, including positional, keyword-only, and variadic parameters.",
            "Unpacking placeholders, loop targets, wildcard imports, and underscore-prefixed names are excluded.",
            "Generated and vendored files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="callback-parameter-marker",
                title="A callback disguises unused parameters with a discard binding",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "def render(root: Path, manifest: Path) -> str:\n    _ = root, manifest\n    return 'ready'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=1,
                public=True,
                scenario="callback-parameters",
            ),
            RuleExample(
                example_id="intentional-callback-stub",
                title="An intentional stub preserves its callback signature",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "def on(event: str, callback: object) -> None:\n    pass\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=True,
                scenario="callback-parameters",
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
            if not is_suppressed(source_lines, node.lineno, self.code)
        ]


def _is_unused_value_marker(node: ast.Assign | ast.AnnAssign) -> bool:
    if isinstance(node, ast.AnnAssign):
        return node.value is not None and isinstance(node.target, ast.Name) and node.target.id == "_"
    return any(isinstance(target, ast.Name) and target.id == "_" for target in node.targets)
