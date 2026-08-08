"""SARJ092 — Docstrings should not repeat types already present in signatures.

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
    description = "Docstring entry repeats a signature type — remove the type spelling but keep behavioral facts."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        return [
            Diagnostic(
                path,
                line,
                group.col,
                self.code,
                self.description,
                column_encoding=group.column_encoding,
            )
            for group in groups(path, source)
            for line in group.typed_restatements
        ]
