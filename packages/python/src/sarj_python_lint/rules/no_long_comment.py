"""SARJ091 — Three or more sentences of in-code prose exceed the comment budget.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_long_comment.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity
from sarj_python_lint.rules._prose_budget import groups, has_list_items, sentence_units


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoLongComment(Rule):
    _ERROR_SENTENCES = 3
    id = "no-long-comment"
    code = "SARJ091"
    description = "Comment exceeds two sentences — keep one local fact and clarify the code itself."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return [
            Diagnostic(
                path,
                group.line,
                group.col,
                self.code,
                self.description,
                Severity.WARNING,
                column_encoding=group.column_encoding,
            )
            for group in groups(path, source)
            if not group.typed_sections
            and (group.kind == "comment" or not has_list_items(group.text))
            and sentence_units(group.text) >= self._ERROR_SENTENCES
        ]
