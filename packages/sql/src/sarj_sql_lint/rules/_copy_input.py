from __future__ import annotations

import re

from sarj_sql_lint.rule_base import dollar_quoted_spans, mask_sql, mask_sql_literals_and_comments
from sarj_sql_lint.rules._constraint_analysis import Token, consume, sequence, tokenize, top_level_tokens


_COPY_WORD = re.compile(r"\bCOPY\b", re.IGNORECASE)
_NON_NEWLINE = re.compile(r"[^\r\n]")


def sql_before_copy_input(source: str) -> str:
    if _COPY_WORD.search(source) is None:
        return source
    masked_chars = list(mask_sql(source, mask_dollar_literals=True))
    for start, end in dollar_quoted_spans(source):
        masked_chars[start:end] = _NON_NEWLINE.sub(" ", source[start:end])
    masked = "".join(masked_chars)
    names_preserved = _masked_top_level_sql(source)
    start = 0
    for separator in re.finditer(r";", masked):
        tokens = tokenize(names_preserved[start : separator.start()])
        if tokens and _copy_from_stdin(tokens):
            return source[: start + tokens[0].start]
        start = separator.end()
    tokens = tokenize(names_preserved[start:])
    return source[: start + tokens[0].start] if tokens and _copy_from_stdin(tokens) else source


def _copy_from_stdin(tokens: list[Token]) -> bool:
    top = top_level_tokens(tokens)
    return consume(top, 0, "COPY") and any(sequence(top, index, ("FROM", "STDIN")) for index in range(1, len(top)))


def _masked_top_level_sql(source: str) -> str:
    masked_chars = list(mask_sql_literals_and_comments(source, mask_dollar_literals=True))
    for start, end in dollar_quoted_spans(source):
        masked_chars[start:end] = _NON_NEWLINE.sub(" ", source[start:end])
    return "".join(masked_chars)
