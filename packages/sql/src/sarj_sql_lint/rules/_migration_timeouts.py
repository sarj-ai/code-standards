from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import re

from sarj_sql_lint.rule_base import (
    SourceComment,
    dollar_quoted_lines,
    is_postgres,
    mask_sql_comments,
    physical_lines,
    source_location,
    sql_comments,
)
from sarj_sql_lint.rules._constraint_analysis import Token, consume, sequence, tokenize
from sarj_sql_lint.rules._copy_input import mask_top_level_sql, sql_before_copy_input


class TimeoutSetting(StrEnum):
    STATEMENT = "statement_timeout"
    LOCK = "lock_timeout"
    IDLE_TRANSACTION = "idle_in_transaction_session_timeout"
    IDLE_SESSION = "idle_session_timeout"
    TRANSACTION = "transaction_timeout"
    DEADLOCK = "deadlock_timeout"


_TIMEOUT_WORD = re.compile("|".join(TimeoutSetting), re.IGNORECASE)
_MIN_CONTROL_TOKENS = 2
_JUSTIFICATION = re.compile(
    r"timeout-justification:[ \t]*(?P<setting>[a-z_]+)[ \t]+--[ \t]*(?P<reason>[^\r\n]*\S)[ \t]*",
    re.IGNORECASE | re.ASCII,
)


@dataclass(frozen=True, slots=True)
class TimeoutControl:
    offset: int
    setting: TimeoutSetting
    justification: SourceComment | None


@lru_cache(maxsize=32)
def migration_timeout_controls(source: str) -> tuple[TimeoutControl, ...]:
    if _TIMEOUT_WORD.search(source) is None or not is_postgres(source):
        return ()
    source = sql_before_copy_input(source)
    masked = mask_top_level_sql(source)
    if masked.startswith("\ufeff"):
        masked = " " + masked[1:]
    tokens = tokenize(masked)
    if tokens is None or any(sequence(tokens, index, ("BEGIN", "ATOMIC")) for index in range(len(tokens))):
        return ()
    lines = physical_lines(source)
    comments = _standalone_comments(source, lines)
    uncommented = mask_sql_comments(source)
    controls: list[TimeoutControl] = []
    first = 0
    depth = 0
    for index, token in enumerate((*tokens, Token(";", len(masked)))):
        if token.quoted:
            continue
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.text == ";" and depth == 0:
            statement = tokens[first:index]
            setting = _timeout_setting(statement, uncommented, token.start)
            if setting is not None:
                offset = statement[0].start
                justification = _justification(source, lines, comments, offset, setting)
                controls.append(TimeoutControl(offset, setting, justification))
            first = index + 1
    return tuple(controls)


def _standalone_comments(source: str, lines: list[str]) -> dict[int, SourceComment]:
    dollar_lines = dollar_quoted_lines(source)
    return {
        comment.line: comment
        for comment in sql_comments(source, mask_dollar_literals=True)
        if not comment.block
        and comment.line not in dollar_lines
        and not lines[comment.line - 1][: comment.column - 1].strip("\ufeff \t")
    }


def _timeout_setting(tokens: list[Token], uncommented: str, end: int) -> TimeoutSetting | None:
    if len(tokens) < _MIN_CONTROL_TOKENS or not (consume(tokens, 0, "SET") or consume(tokens, 0, "RESET")):
        return None
    cursor = 1
    if consume(tokens, 0, "SET") and (consume(tokens, cursor, "LOCAL") or consume(tokens, cursor, "SESSION")):
        cursor += 1
    if cursor >= len(tokens):
        return None
    setting = _known_timeout(tokens[cursor])
    cursor += 1
    if setting is None:
        return None
    if consume(tokens, 0, "RESET"):
        return setting if cursor == len(tokens) else None
    if cursor < len(tokens) and (tokens[cursor].text == "=" or consume(tokens, cursor, "TO")):
        value_start = tokens[cursor].start + len(tokens[cursor].text)
        return setting if uncommented[value_start:end].strip() else None
    return None


def _known_timeout(token: Token) -> TimeoutSetting | None:
    name = token.text[1:-1].replace('""', '"') if token.quoted else token.text
    return next((value for value in TimeoutSetting if value.value == name.lower()), None)


def _justification(
    source: str,
    lines: list[str],
    comments: dict[int, SourceComment],
    offset: int,
    setting: TimeoutSetting,
) -> SourceComment | None:
    location = source_location(source, offset)
    comment = comments.get(location.line - 1)
    if comment is None or lines[location.line - 1][: location.column - 1].strip("\ufeff \t"):
        return None
    match = _JUSTIFICATION.fullmatch(comment.body.strip())
    if match is None or match.group("setting").lower() != setting:
        return None
    return comment if any(character.isalnum() for character in match.group("reason")) else None
