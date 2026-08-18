from __future__ import annotations

from dataclasses import dataclass
import tokenize

from sarj_python_lint.rules._comments import all_comments


@dataclass(frozen=True, slots=True)
class Comment:
    line: int
    col: int
    body: str
    standalone: bool
    before_first_statement: bool = False


def scan_comments(source: str) -> list[Comment]:
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


def scan_comments_or_none(source: str) -> list[Comment] | None:
    try:
        return scan_comments(source)
    except tokenize.TokenError, SyntaxError:
        return None
