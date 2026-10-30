from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokenizer_core import TokenType


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlglot.tokenizer_core import Token


_COPY_END = re.compile(r"(?m)^\\\.(?:\r?$)")
_TEMP_TABLE = (TokenType.CREATE, TokenType.TEMPORARY, TokenType.TABLE)
_ON_COMMIT_DROP = (TokenType.ON, TokenType.COMMIT, TokenType.DROP)


def normalize_postgres_ctas(source: str) -> str:
    source = _mask_copy_input(source)
    try:
        tokens = sqlglot.tokenize(source, read="postgres")
    except SqlglotError, RecursionError:
        return source
    output = list(source)
    statement: list[Token] = []
    for token in tokens:
        if token.token_type is not TokenType.SEMICOLON:
            statement.append(token)
            continue
        _normalize_header(output, statement)
        statement = []
    _normalize_header(output, statement)
    return "".join(output)


def _mask_copy_input(source: str) -> str:
    if "COPY" not in source.upper():
        return source
    output = list(source)
    start = 0
    for separator in re.finditer(r";", source):
        if separator.start() < start:
            continue
        try:
            tokens = sqlglot.tokenize(source[start : separator.end()], read="postgres")
        except SqlglotError, RecursionError:
            continue
        if not tokens or tokens[-1].token_type is not TokenType.SEMICOLON:
            continue
        if start + tokens[-1].end != separator.start():
            continue
        if _copy_from_stdin(tokens):
            marker = _COPY_END.search(source, separator.end())
            end = marker.end() if marker is not None else len(source)
            _blank(output, start, end)
            start = end
        else:
            start = separator.end()
    return "".join(output)


def _normalize_header(output: list[str], tokens: Sequence[Token]) -> None:
    if tuple(token.token_type for token in tokens[:3]) != _TEMP_TABLE:
        return
    depth = 0
    for index, token in enumerate(tokens):
        if token.token_type is TokenType.L_PAREN:
            depth += 1
        elif token.token_type is TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type is TokenType.ALIAS:
            if tuple(part.token_type for part in tokens[index - 3 : index]) != _ON_COMMIT_DROP:
                return
            start = tokens[0].start
            candidate = output[start : tokens[-1].end + 1]
            _blank(candidate, tokens[index - 3].start - start, tokens[index - 1].end + 1 - start)
            if _is_query_create("".join(candidate)):
                # DROP is the unsupported SQLGlot property; the query and physical offsets stay intact.
                _blank(output, tokens[index - 3].start, tokens[index - 1].end + 1)
            return


def _is_query_create(candidate: str) -> bool:
    try:
        parsed = sqlglot.parse_one(candidate, read="postgres")
    except SqlglotError, RecursionError:
        return False
    return (
        isinstance(parsed, exp.Create)
        and parsed.args.get("kind") == "TABLE"
        and isinstance(parsed.args.get("expression"), exp.Query)
    )


def _copy_from_stdin(tokens: Sequence[Token]) -> bool:
    if not tokens or tokens[0].token_type is not TokenType.COPY:
        return False
    depth = 0
    for index, token in enumerate(tokens[:-1]):
        if token.token_type is TokenType.L_PAREN:
            depth += 1
        elif token.token_type is TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type is TokenType.FROM:
            following = tokens[index + 1]
            return following.token_type is TokenType.VAR and following.text.upper() == "STDIN"
    return False


def _blank(output: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if output[index] not in {"\r", "\n"}:
            output[index] = " "
