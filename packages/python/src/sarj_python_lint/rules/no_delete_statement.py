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
class NoDeleteStatement(Rule):
    id = "no-delete-statement"
    code = "SARJ442"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Avoid `del` statements; prefer constructing an immutable replacement value.",
        rationale=(
            "Deleting a name, attribute, or collection entry introduces lifetime or in-place mutation semantics "
            "that are harder to follow than explicit value construction."
        ),
        remediation=(
            "Remove unused-value deletion markers. Rebuild collections with comprehensions, copies, or immutable "
            "value helpers such as dataclasses.replace. When an external API or deliberate lifetime boundary "
            "requires deletion, add an exact SARJ442 suppression on the statement and explain why."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("no-deleted-only-override-parameter",),
        limitations=(
            "Every authored Python del statement is reported once, regardless of how many targets it contains.",
            "The rule does not automatically rewrite deletion because the correct immutable replacement depends on ownership and value semantics.",
            "Generated and vendored files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="delete-mapping-entry",
                title="Build a mapping without the removed entry",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "payload = dict(raw_payload)\ndel payload['secret']\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-mapping-filter",
                title="Construct the desired mapping directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "payload = {key: value for key, value in raw_payload.items() if key != 'secret'}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "del" not in source or is_generated(path, source):
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
                    "`del` introduces mutation or hidden lifetime behavior — construct the desired value "
                    "immutably, or add an exact SARJ442 suppression explaining why deletion is required."
                ),
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Delete) and not is_suppressed(source_lines, node.lineno, self.code)
        ]
