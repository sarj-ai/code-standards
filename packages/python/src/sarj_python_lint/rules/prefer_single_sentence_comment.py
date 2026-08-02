"""SARJ090 — Two sentences of comment prose should become one.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_single_sentence_comment.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity
from sarj_python_lint.rules._prose_budget import groups, sentence_units


if TYPE_CHECKING:
    from pathlib import Path


@final
class PreferSingleSentenceComment(Rule):
    _WARNING_SENTENCES = 2
    id = "prefer-single-sentence-comment"
    code = "SARJ090"
    description = "Two-sentence comment — prefer one sentence and self-documenting code."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return [
            Diagnostic(path, group.line, group.col, self.code, self.description, Severity.WARNING)
            for group in groups(path, source)
            if not group.typed_sections and sentence_units(group.text) == self._WARNING_SENTENCES
        ]
