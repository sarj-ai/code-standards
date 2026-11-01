from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError, TokenError
from sqlglot.tokenizer_core import TokenType


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlglot.tokenizer_core import Token


_COPY_WORD = re.compile(r"\bCOPY\b", re.IGNORECASE)
_COPY_END = re.compile(r"(?m)^\\\.(?:\r?$)")
_TEMP_TABLE = (TokenType.CREATE, TokenType.TEMPORARY, TokenType.TABLE)
_ON_COMMIT_DROP = (TokenType.ON, TokenType.COMMIT, TokenType.DROP)
_ON_COMMIT_ROWS_SIZE = 4


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
    if not _may_have_copy_input(source):
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


def _may_have_copy_input(source: str) -> bool:
    remaining = len(source) * 2
    for candidate in _COPY_WORD.finditer(source):
        if candidate.end() > remaining:
            return True
        remaining -= candidate.end()
        try:
            tokens = sqlglot.tokenize(source[: candidate.end()], read="postgres")
        except TokenError:
            continue
        except SqlglotError, RecursionError, UnicodeError:
            return True
        if tokens:
            last = tokens[-1]
            if (
                last.token_type is TokenType.COPY
                and last.start == candidate.start()
                and last.end + 1 == candidate.end()
            ):
                return True
    return False


def _normalize_header(output: list[str], tokens: Sequence[Token]) -> None:
    if not _is_table_create(tokens):
        return
    depth = 0
    for index, token in enumerate(tokens):
        if token.token_type is TokenType.L_PAREN:
            depth += 1
        elif token.token_type is TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type is TokenType.ALIAS:
            spans = _ignored_header_spans(tokens[:index])
            if not spans:
                return
            start = tokens[0].start
            candidate = output[start : tokens[-1].end + 1]
            for first, last in spans:
                _blank(candidate, first.start - start, last.end + 1 - start)
            if _is_query_create("".join(candidate)):
                for first, last in spans:
                    _blank(output, first.start, last.end + 1)
            return


def _temporary_qualifier(tokens: Sequence[Token]) -> Token | None:
    if len(tokens) > 1 and tokens[1].token_type is TokenType.VAR and tokens[1].text.upper() in {"GLOBAL", "LOCAL"}:
        return tokens[1]
    return None


def _is_table_create(tokens: Sequence[Token]) -> bool:
    kinds = tuple(token.token_type for token in tokens[:4])
    if kinds[:2] == (TokenType.CREATE, TokenType.TABLE) or kinds[:3] == _TEMP_TABLE:
        return True
    if kinds[:3] == (TokenType.CREATE, TokenType.VAR, TokenType.TABLE):
        return tokens[1].text.upper() == "UNLOGGED"
    return (
        kinds == (TokenType.CREATE, TokenType.VAR, TokenType.TEMPORARY, TokenType.TABLE)
        and _temporary_qualifier(tokens) is not None
    )


def _ignored_header_spans(tokens: Sequence[Token]) -> tuple[tuple[Token, Token], ...]:
    spans: list[tuple[Token, Token]] = []
    qualifier = _temporary_qualifier(tokens)
    if qualifier is not None:
        spans.append((qualifier, qualifier))
    end = len(tokens)
    if _has_tablespace_property(tokens):
        spans.append((tokens[-2], tokens[-1]))
        end -= 2
    commit_start = _commit_property_start(tokens, end)
    if commit_start < end and tokens[end - 1].token_type is TokenType.DROP:
        spans.append((tokens[commit_start], tokens[end - 1]))
    if _has_without_oids_property(tokens[:commit_start]):
        spans.append((tokens[commit_start - 2], tokens[commit_start - 1]))
    return tuple(spans)


def _commit_property_start(tokens: Sequence[Token], end: int) -> int:
    if tuple(token.token_type for token in tokens[end - 3 : end]) == _ON_COMMIT_DROP:
        return end - 3
    if end < _ON_COMMIT_ROWS_SIZE or tuple(
        token.token_type for token in tokens[end - _ON_COMMIT_ROWS_SIZE : end - 2]
    ) != (TokenType.ON, TokenType.COMMIT):
        return end
    action, rows = tokens[end - 2 : end]
    if rows.token_type is TokenType.ROWS and (
        action.token_type is TokenType.DELETE
        or (action.token_type is TokenType.VAR and action.text.upper() == "PRESERVE")
    ):
        return end - _ON_COMMIT_ROWS_SIZE
    return end


def _has_without_oids_property(tokens: Sequence[Token]) -> bool:
    return (
        len(tokens) > 1
        and tokens[-2].token_type is TokenType.VAR
        and tokens[-1].token_type is TokenType.VAR
        and tokens[-2].text.upper() == "WITHOUT"
        and tokens[-1].text.upper() == "OIDS"
    )


def _has_tablespace_property(tokens: Sequence[Token]) -> bool:
    return (
        len(tokens) > 1
        and tokens[-2].token_type is TokenType.VAR
        and tokens[-2].text.upper() == "TABLESPACE"
        and tokens[-1].token_type in {TokenType.VAR, TokenType.IDENTIFIER}
    )


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
