"""SARJ092 — Typed signatures do not need parameter or return prose tables.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_typed_doc_sections.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._prose_budget import groups


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoTypedDocSections(Rule):
    id = "no-typed-doc-sections"
    code = "SARJ092"
    description = "Typed docstring repeats parameters or returns — delete the section and improve names/types instead."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return [
            Diagnostic(
                path,
                group.line,
                group.col,
                self.code,
                self.description,
                column_encoding=group.column_encoding,
            )
            for group in groups(path, source)
            if group.typed_sections
        ]
