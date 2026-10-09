from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import tokenize
from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_python_lint.rules._comments import all_comments


if TYPE_CHECKING:
    from collections.abc import Mapping


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


@lru_cache(maxsize=1)
def comment_lines(source_lines: tuple[str, ...]) -> Mapping[int, str]:
    return MappingProxyType(
        {comment.line: "# " + comment.body for comment in scan_comments_or_none("\n".join(source_lines)) or ()}
    )
