"""Shared comment tokenizer for the suppression-directive rules (SARJ038, SARJ054).

Comments do not survive `ast.parse`, so any rule that judges a suppression
*comment* has to lex the file. Both suppression rules need the same three facts
about every comment — its text, whether it stands alone on its line, and whether
it precedes the module's first statement — so they share one scanner rather than
drifting apart on what "file-level" means.
"""

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
    """Describe every comment in `source`, in source order.

    A comment is standalone when no token ended on its line before it, and
    precedes the first statement when it sits above the first non-comment,
    non-layout token.

    Anything `tokenize` cannot lex propagates as `tokenize.TokenError`,
    `IndentationError` or `SyntaxError`; callers treat that as "no diagnostics".

    Built from `_comments.all_comments`, which is the same tokenize pass the
    comment-hygiene rules already run. This module used to lex the file a second
    time to compute exactly the same three facts from identical token-class
    sets, which cost SARJ038 ~4% of total rule time for no additional
    information. The memo now lives in one place rather than two.

    Returns:
        Every comment, in source order. `Comment` is frozen and the list is
        read-only to callers.

    """
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
