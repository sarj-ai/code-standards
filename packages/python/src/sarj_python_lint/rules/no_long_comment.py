"""SARJ091 — Flag unusually large, unstructured docstring prose walls.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_long_comment.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity
from sarj_python_lint.rules._prose_budget import (
    ProseGroup,
    groups,
    has_documentation_structure,
    has_technical_anchor,
    sentence_units,
)


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoLongComment(Rule):
    _ERROR_SENTENCES = 8
    id = "no-long-comment"
    code = "SARJ091"
    description = "Docstring is an unusually large prose wall — structure durable documentation or clarify the code."

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
            if _eligible_owner(group)
            and not group.typed_sections
            and not has_documentation_structure(group.text)
            and not has_technical_anchor(group.text)
            and sentence_units(group.text) >= self._ERROR_SENTENCES
        ]


def _eligible_owner(group: ProseGroup) -> bool:
    """Limit the heuristic to docstrings whose prose is not a typed public API contract."""
    if group.kind != "docstring":
        return False
    if group.owner_kind == "module":
        return True
    if group.owner_kind == "class":
        return bool(group.owner_name and group.owner_name.startswith("_"))
    if group.owner_kind == "function":
        return bool(group.owner_name and (group.owner_name.startswith("_") or not group.owner_fully_typed))
    return False
