"""Shared comment tokenizer for the suppression-directive rules (SARJ038, SARJ054)."""

from __future__ import annotations

from dataclasses import dataclass

from sarj_python_lint.rules._comments import all_comments


@dataclass(frozen=True, slots=True)
class Comment:
    """One comment token, with the context that decides whether it is file-level."""

    line: int
    col: int
    body: str
    standalone: bool
    before_first_statement: bool = False


def scan_comments(source: str) -> list[Comment]:
    """Describe every comment in `source`, in source order."""
    ordered, first_statement_line = all_comments(source)
    return [
        Comment(
            line=line,
            col=col + 1,
            body=body,
            standalone=standalone,
            before_first_statement=line < first_statement_line,
        )
        for line, col, body, standalone in ordered
    ]
