from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, final

from sqlglot.dialects.postgres import Postgres
from sqlglot.tokenizer_core import Token, TokenType


if TYPE_CHECKING:
    from collections.abc import Sequence


_BOOL_VALUES = MappingProxyType({"TRUE": True, "ON": True, "1": True, "FALSE": False, "OFF": False, "0": False})
_BOOL_OPTIONS = frozenset(
    {"ANALYZE", "VERBOSE", "COSTS", "SETTINGS", "GENERIC_PLAN", "BUFFERS", "WAL", "TIMING", "SUMMARY", "MEMORY"}
)
_QUERY_STARTS = frozenset(
    {"SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "MERGE", "VALUES", "EXECUTE", "DECLARE", "CREATE"}
)
_OPTION_VALUE_ARITY = 2
_MIN_EXPLAIN_TOKENS = 3


@final
class _ExplainTokenizer(Postgres.Tokenizer):
    # Keep the native PostgreSQL lexer while exposing EXPLAIN's query tokens.
    COMMANDS: ClassVar[set[TokenType]] = Postgres.Tokenizer.COMMANDS - {TokenType.COMMAND}


@dataclass(frozen=True, slots=True)
class _Option:
    name: str
    enabled: bool | None


@dataclass(frozen=True, slots=True)
class _Header:
    query_index: int
    options: tuple[_Option, ...]


def normalize_postgres_explain(sql: str) -> str:
    output = list(sql)
    statement: list[Token] = []
    for token in _ExplainTokenizer(dialect="postgres").tokenize(sql):
        if token.token_type is TokenType.SEMICOLON:
            _blank_explain(output, statement)
            statement = []
        else:
            statement.append(token)
    _blank_explain(output, statement)
    return "".join(output)


def _blank_explain(output: list[str], tokens: Sequence[Token]) -> None:
    if not tokens or tokens[0].token_type is not TokenType.COMMAND or tokens[0].text.upper() != "EXPLAIN":
        return
    query_index = _executed_query_start(tokens)
    end = tokens[query_index].start if query_index is not None else tokens[-1].end + 1
    for position in range(tokens[0].start, end):
        if output[position] not in {"\r", "\n"}:
            output[position] = " "


def _executed_query_start(tokens: Sequence[Token]) -> int | None:
    if len(tokens) < _MIN_EXPLAIN_TOKENS:
        return None
    index = 1
    if tokens[index].token_type is TokenType.L_PAREN:
        header = _option_header(tokens)
        if header is None or not _executes(header.options):
            return None
        index = header.query_index
    else:
        if tokens[index].text.upper() != "ANALYZE":
            return None
        index += 1
        if index < len(tokens) and tokens[index].text.upper() == "VERBOSE":
            index += 1
    return index if _starts_query(tokens, index) else None


def _option_header(tokens: Sequence[Token]) -> _Header | None:
    closing = next((index for index in range(2, len(tokens)) if tokens[index].token_type is TokenType.R_PAREN), None)
    if closing is None:
        return None
    groups: list[list[Token]] = [[]]
    for token in tokens[2:closing]:
        if token.token_type is TokenType.COMMA:
            groups.append([])
        else:
            groups[-1].append(token)
    options: list[_Option] = []
    for group in groups:
        option = _option(group)
        if option is None:
            return None
        options.append(option)
    return _Header(closing + 1, tuple(options))


def _option(tokens: Sequence[Token]) -> _Option | None:
    if not tokens or tokens[0].token_type is TokenType.IDENTIFIER:
        return None
    name = tokens[0].text.upper()
    if name in _BOOL_OPTIONS:
        if len(tokens) == 1:
            return _Option(name, enabled=True)
        if len(tokens) == _OPTION_VALUE_ARITY and tokens[1].token_type is not TokenType.STRING:
            enabled = _BOOL_VALUES.get(tokens[1].text.upper())
            if enabled is not None:
                return _Option(name, enabled=enabled)
        return None
    if (
        name == "FORMAT"
        and len(tokens) == _OPTION_VALUE_ARITY
        and tokens[1].text.upper() in {"TEXT", "XML", "JSON", "YAML"}
    ):
        return _Option(name, enabled=None)
    if name == "SERIALIZE" and (
        len(tokens) == 1
        or (len(tokens) == _OPTION_VALUE_ARITY and tokens[1].text.upper() in {"NONE", "TEXT", "BINARY"})
    ):
        return _Option(name, enabled=None)
    return None


def _executes(options: tuple[_Option, ...]) -> bool:
    analyze = [option.enabled for option in options if option.name == "ANALYZE"]
    if len(analyze) != 1 or analyze[0] is not True:
        return False
    return not any(option.name == "GENERIC_PLAN" and option.enabled is True for option in options)


def _starts_query(tokens: Sequence[Token], index: int) -> bool:
    while index < len(tokens) and tokens[index].token_type is TokenType.L_PAREN:
        index += 1
    return index < len(tokens) and tokens[index].text.upper() in _QUERY_STARTS
