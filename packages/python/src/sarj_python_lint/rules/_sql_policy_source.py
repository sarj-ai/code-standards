from __future__ import annotations

from itertools import pairwise
import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlglot.tokenizer_core import Token


def normalize_group_comments(source: str, tokens: Sequence[Token]) -> str:
    from sqlglot.tokenizer_core import TokenType  # ruff: ignore[import-outside-top-level] -- only parsed SQL candidates need native token identities.

    chunks: list[str] = []
    start = 0
    for left, right in pairwise(tokens):
        if left.token_type is not TokenType.VAR or right.token_type is not TokenType.VAR:
            continue
        if left.text.upper() != "GROUP" or right.text.upper() != "BY":
            continue
        gap = source[left.end + 1 : right.start]
        if not gap.strip():
            continue
        # Native adjacent unquoted tokens prove this gap contains only comments/space.
        # Blanking just that gap preserves values, quoted identifiers and source spans.
        chunks.extend((source[start : left.end + 1], re.sub(r"[^\r\n]", " ", gap)))
        start = right.start
    chunks.append(source[start:])
    return "".join(chunks)
