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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoUnusedValueMarker(Rule):
    id = "no-unused-value-marker"
    code = "SARJ452"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not use standalone assignments to `_` to discard values.",
        rationale=(
            "A standalone `_ = value` assignment adds a binding without clarifying intent. A side-effecting call can "
            "be invoked directly, while an unused parameter should be addressed at its declaration."
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
            "Unpacking placeholders, loop targets, wildcard imports, and underscore-prefixed names are excluded.",
            "Generated and vendored files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="unused-parameter-marker",
                title="Do not manufacture a use for interface parameters",
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

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "_" not in source or "=" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        source_lines = source.splitlines()
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
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and _is_unused_value_marker(node)
            and not is_suppressed(source_lines, node.lineno, self.code)
        ]


def _is_unused_value_marker(node: ast.Assign | ast.AnnAssign) -> bool:
    if isinstance(node, ast.AnnAssign):
        return node.value is not None and isinstance(node.target, ast.Name) and node.target.id == "_"
    return any(isinstance(target, ast.Name) and target.id == "_" for target in node.targets)
