from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlglot.tokenizer_core import Token


def normalize_group_comments(source: str, tokens: Sequence[Token]) -> str:
    from sqlglot.tokenizer_core import TokenType  # ruff: ignore[import-outside-top-level] -- only parsed SQL candidates need native token identities.

    chunks: list[str] = []
    start = 0
    for index, left in enumerate(tokens):
        if left.token_type is TokenType.GROUP_BY:
            gap_start = left.start + len("GROUP")
            gap_end = left.end + 1 - len("BY")
        elif left.token_type is TokenType.VAR and left.text.upper() == "GROUP" and index + 1 < len(tokens):
            right = tokens[index + 1]
            if right.token_type is not TokenType.VAR or right.text.upper() != "BY":
                continue
            gap_start = left.end + 1
            gap_end = right.start
        else:
            continue
        gap = source[gap_start:gap_end]
        if not gap.strip():
            continue
        chunks.extend((source[start:gap_start], re.sub(r"[^\r\n]", " ", gap)))
        start = gap_end
    chunks.append(source[start:])
    return "".join(chunks)
