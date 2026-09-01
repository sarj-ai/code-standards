from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, NamedTuple

from sarj_sql_lint.rule_base import (
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    mask_sql_literals_and_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_CREATE_INDEX_RE = re.compile(
    r"\bCREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Za-z0-9_\".]+)\s+ON\s+"
    r"(?:ONLY\s+)?(?P<table>[A-Za-z0-9_\".]+)\s*"
    r"(?:USING\s+(?P<method>[A-Za-z0-9_]+)\s*)?\(",
    re.IGNORECASE,
)
_INCLUDE_RE = re.compile(r"\bINCLUDE\s*\(", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_APP_READ_JUSTIFICATION_RE = re.compile(
    r"^\s*--\s*index-justification:\s*app-read:\s*[^\s;\n](?:[^;\n]*[^\s;\n])?;\s*"
    r"(?:evidence:\s*https?://\S+|ticket:\s*(?-i:[A-Z][A-Z0-9]+-\d+))\s*$",
    re.IGNORECASE,
)
_REFERENTIAL_JUSTIFICATION_RE = re.compile(
    r"^\s*--\s*index-justification:\s*referential-action:\s*"
    r"(?:ON\s+(?:DELETE|UPDATE)\s+)?(?:CASCADE|SET\s+NULL|SET\s+DEFAULT)\s*$",
    re.IGNORECASE,
)


class IndexSignature(NamedTuple):
    unique: bool
    table: str
    method: str
    keys: tuple[str, ...]
    include: tuple[str, ...]
    predicate: str


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    start: int
    line: int
    column: int
    name: str
    table: str
    method: str
    keys: tuple[str, ...]
    include: tuple[str, ...]
    predicate: str
    unique: bool
    justified: bool

    @property
    def signature(self) -> IndexSignature:
        return IndexSignature(self.unique, self.table, self.method, self.keys, self.include, self.predicate)


def authored_indexes(path: Path, source: str) -> tuple[IndexDefinition, ...]:
    if is_dump_file(source, path) or not is_migration_source(path, source) or is_generated_migration(path, source):
        return ()
    return parse_indexes(source)


def authored_secondary_indexes(path: Path, source: str) -> tuple[IndexDefinition, ...]:
    return tuple(index for index in authored_indexes(path, source) if not index.unique)


def parse_indexes(source: str) -> tuple[IndexDefinition, ...]:
    masked = mask_sql_literals_and_comments(source)
    indexes: list[IndexDefinition] = []
    for match in _CREATE_INDEX_RE.finditer(masked):
        opening = match.end() - 1
        closing = _matching_paren(masked, opening)
        if closing is None:
            continue
        statement_end = masked.find(";", closing)
        if statement_end < 0:
            statement_end = len(masked)
        suffix = masked[closing + 1 : statement_end]
        include: tuple[str, ...] = ()
        if (include_match := _INCLUDE_RE.search(suffix)) is not None:
            include_open = closing + 1 + include_match.end() - 1
            include_close = _matching_paren(masked, include_open)
            if include_close is None or include_close > statement_end:
                continue
            include = _split_elements(source[include_open + 1 : include_close])
        where_match = _WHERE_RE.search(suffix)
        predicate = ""
        if where_match is not None:
            where_start = closing + 1 + where_match.end()
            predicate = _normalize_sql(source[where_start:statement_end])
        line_start = source.rfind("\n", 0, match.start()) + 1
        indexes.append(
            IndexDefinition(
                start=match.start(),
                line=source.count("\n", 0, match.start()) + 1,
                column=match.start() - line_start + 1,
                name=_normalize_sql(match.group("name")),
                table=_normalize_sql(match.group("table")),
                method=(match.group("method") or "btree").lower(),
                keys=_split_elements(source[opening + 1 : closing]),
                include=include,
                predicate=predicate,
                unique=match.group("unique") is not None,
                justified=_has_local_justification(source, match.start()),
            )
        )
    return tuple(indexes)


def _matching_paren(masked: str, opening: int) -> int | None:
    depth = 0
    for position in range(opening, len(masked)):
        char = masked[position]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
    return None


def _split_elements(value: str) -> tuple[str, ...]:
    elements: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    position = 0
    while position < len(value):
        char = value[position]
        if quote is not None:
            if char == quote:
                if position + 1 < len(value) and value[position + 1] == quote:
                    position += 2
                    continue
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            if normalized := _normalize_sql(value[start:position]):
                elements.append(normalized)
            start = position + 1
        position += 1
    if normalized := _normalize_sql(value[start:]):
        elements.append(normalized)
    return tuple(elements)


def _normalize_sql(value: str) -> str:
    output: list[str] = []
    quote: str | None = None
    pending_space = False
    position = 0
    while position < len(value):
        char = value[position]
        if quote is not None:
            output.append(char)
            if char == quote:
                if position + 1 < len(value) and value[position + 1] == quote:
                    output.append(value[position + 1])
                    position += 2
                    continue
                quote = None
        elif char in {"'", '"'}:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = char
            output.append(char)
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(char.lower())
        position += 1
    return "".join(output).strip()


def _has_local_justification(source: str, start: int) -> bool:
    previous_end = source.rfind("\n", 0, start)
    if previous_end < 0:
        return False
    previous_start = source.rfind("\n", 0, previous_end) + 1
    previous = source[previous_start:previous_end]
    return (
        _APP_READ_JUSTIFICATION_RE.fullmatch(previous) is not None
        or _REFERENTIAL_JUSTIFICATION_RE.fullmatch(previous) is not None
    )
