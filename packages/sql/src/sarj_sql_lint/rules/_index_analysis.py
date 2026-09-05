from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, NamedTuple

from sarj_sql_lint.rule_base import (
    declared_dialect,
    dollar_quoted_spans,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    mask_sql_literals_and_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_IDENTIFIER_PART = r'(?:"(?:""|[^"\n])+"|[A-Za-z_][A-Za-z0-9_$]*)'
_QUALIFIED_IDENTIFIER = rf"{_IDENTIFIER_PART}(?:\s*\.\s*{_IDENTIFIER_PART})*"
_IDENTIFIER_PART_RE = re.compile(_IDENTIFIER_PART)
_CREATE_INDEX_RE = re.compile(
    rf"\bCREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?(?:(?P<name>{_QUALIFIED_IDENTIFIER})\s+)?ON\s+"
    rf"(?P<only>ONLY\s+)?(?P<table>{_QUALIFIED_IDENTIFIER})\s*"
    rf"(?:USING\s+(?P<method>{_IDENTIFIER_PART})\s*)?\(",
    re.IGNORECASE,
)
_INCLUDE_RE = re.compile(r"\bINCLUDE\s*\(", re.IGNORECASE)
_WITH_RE = re.compile(r"\bWITH\s*\(", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_NON_PRODUCTION_INDEX_PARTS = frozenset({"test", "tests", "testing", "__tests__"})
_NULLS_DISTINCT_RE = re.compile(r"NULLS\s+(?:NOT\s+)?DISTINCT\b", re.IGNORECASE)
_TABLESPACE_RE = re.compile(rf"TABLESPACE\s+(?P<tablespace>{_QUALIFIED_IDENTIFIER})", re.IGNORECASE)
_DROP_INDEX_RE = re.compile(
    r"\bDROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?",
    re.IGNORECASE,
)
_QUOTED_IDENTIFIER_RE = re.compile(r'"(?P<body>(?:""|[^"\n])+)"')
_SAFE_UNQUOTED_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_$]*")
_DOLLAR_QUOTE_START_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_AFTER_NULLS_STAGE = 2
_AFTER_WITH_STAGE = 3
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
_UNIQUENESS_JUSTIFICATION_RE = re.compile(
    r"^\s*--\s*index-justification:\s*uniqueness-constraint:\s*[^\s;\n](?:[^;\n]*[^\s;\n])?;\s*"
    r"(?:evidence:\s*https?://\S+|ticket:\s*(?-i:[A-Z][A-Z0-9]+-\d+))\s*$",
    re.IGNORECASE,
)


class IndexSignature(NamedTuple):
    unique: bool
    only: bool
    table: str
    method: str
    keys: tuple[str, ...]
    include: tuple[str, ...]
    nulls_distinct: str
    storage_parameters: tuple[str, ...]
    tablespace: str
    predicate: str


class IndexSuffix(NamedTuple):
    include_open: int | None
    include_close: int | None
    nulls_distinct: str
    storage_open: int | None
    storage_close: int | None
    tablespace: str
    where_start: int | None


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    start: int
    line: int
    column: int
    name: str
    table: str
    method: str
    only: bool
    keys: tuple[str, ...]
    include: tuple[str, ...]
    nulls_distinct: str
    storage_parameters: tuple[str, ...]
    tablespace: str
    predicate: str
    unique: bool
    justified: bool

    @property
    def signature(self) -> IndexSignature:
        return IndexSignature(
            self.unique,
            self.only,
            self.table,
            self.method,
            self.keys,
            self.include,
            self.nulls_distinct,
            self.storage_parameters,
            self.tablespace,
            self.predicate,
        )


@dataclass(frozen=True, slots=True)
class IndexDrop:
    start: int
    names: tuple[str, ...]


type IndexOperation = IndexDefinition | IndexDrop


def authored_indexes(path: Path, source: str) -> tuple[IndexDefinition, ...]:
    if not _is_authored_index_source(path, source):
        return ()
    return parse_indexes(source)


def authored_index_operations(path: Path, source: str) -> tuple[IndexOperation, ...]:
    if not _is_authored_index_source(path, source):
        return ()
    masked = _mask_dollar_quoted_bodies(source, mask_sql_literals_and_comments(source))
    return tuple(sorted((*parse_indexes(source), *_parse_drops(masked)), key=lambda operation: operation.start))


def _is_authored_index_source(path: Path, source: str) -> bool:
    parts = {part.lower() for part in path.parts}
    return not (
        parts & _NON_PRODUCTION_INDEX_PARTS
        or (declared_dialect(source) not in {None, "postgresql"})
        or is_dump_file(source, path)
        or not is_migration_source(path, source)
        or is_generated_migration(path, source)
    )


def authored_secondary_indexes(path: Path, source: str) -> tuple[IndexDefinition, ...]:
    return tuple(index for index in authored_indexes(path, source) if not index.unique)


def parse_indexes(source: str) -> tuple[IndexDefinition, ...]:
    masked = _mask_dollar_quoted_bodies(source, mask_sql_literals_and_comments(source))
    quoted_identifier_spans = _quoted_identifier_spans(masked)
    indexes: list[IndexDefinition] = []
    for match in _CREATE_INDEX_RE.finditer(masked):
        if _inside_spans(match.start(), quoted_identifier_spans):
            continue
        unique = match.group("unique") is not None
        opening = match.end() - 1
        closing = _matching_paren(masked, opening)
        if closing is None:
            continue
        statement_end = _statement_end(masked, closing)
        suffix = _parse_index_suffix(masked, closing + 1, statement_end)
        if suffix is None:
            continue
        include: tuple[str, ...] = ()
        if suffix.include_open is not None and suffix.include_close is not None:
            include = _split_elements(source[suffix.include_open + 1 : suffix.include_close])
        storage_parameters: tuple[str, ...] = ()
        if suffix.storage_open is not None and suffix.storage_close is not None:
            storage_parameters = _split_elements(source[suffix.storage_open + 1 : suffix.storage_close])
        predicate = ""
        if suffix.where_start is not None:
            predicate = _normalize_sql(source[suffix.where_start : statement_end])
        line_start = source.rfind("\n", 0, match.start()) + 1
        indexes.append(
            IndexDefinition(
                start=match.start(),
                line=source.count("\n", 0, match.start()) + 1,
                column=match.start() - line_start + 1,
                name=_normalize_identifier(match.group("name") or "<unnamed>"),
                table=_normalize_identifier(match.group("table")),
                method=_normalize_identifier(match.group("method") or "btree"),
                only=match.group("only") is not None,
                keys=_split_elements(source[opening + 1 : closing]),
                include=include,
                nulls_distinct=suffix.nulls_distinct or ("nulls distinct" if unique else ""),
                storage_parameters=storage_parameters,
                tablespace=suffix.tablespace,
                predicate=predicate,
                unique=unique,
                justified=_has_local_justification(source, match.start(), unique=unique),
            )
        )
    return tuple(indexes)


def _mask_dollar_quoted_bodies(source: str, masked: str) -> str:
    output = list(masked)
    for start, end in dollar_quoted_spans(source):
        # PostgreSQL permits `$` inside an unquoted identifier. The shared
        # scanner has already rejected tags following letters/digits/`_`, but
        # a second `$` can otherwise make `name$$suffix$$` look like a dollar
        # literal. Restore that identifier text rather than masking it.
        if start > 0 and _is_identifier_character(source[start - 1]):
            output[start:end] = source[start:end]
            continue
        for position in range(start, end):
            if output[position] != "\n":
                output[position] = " "
    return "".join(output)


def _parse_drops(masked: str) -> tuple[IndexDrop, ...]:
    quoted_identifier_spans = _quoted_identifier_spans(masked)
    drops: list[IndexDrop] = []
    for match in _DROP_INDEX_RE.finditer(masked):
        if _inside_spans(match.start(), quoted_identifier_spans):
            continue
        statement_end = _statement_end(masked, match.end())
        body = re.sub(r"\s+(?:CASCADE|RESTRICT)\s*$", "", masked[match.end() : statement_end], flags=re.IGNORECASE)
        raw_names = _split_identifier_list(body)
        if not raw_names or any(re.fullmatch(_QUALIFIED_IDENTIFIER, name) is None for name in raw_names):
            continue
        drops.append(IndexDrop(match.start(), tuple(_normalize_identifier(name) for name in raw_names)))
    return tuple(drops)


def index_namespace_key(index: IndexDefinition) -> str | None:
    if index.name == "<unnamed>":
        return None
    name_parts = _identifier_components(index.name)
    name_part = next(iter(name_parts), None)
    if name_part is None:
        return None
    if len(name_parts) > 1:
        return ".".join(name_parts)
    table_parts = _identifier_components(index.table)
    return ".".join((*table_parts[:-1], name_part))


def drop_namespace_keys(drop: IndexDrop, active_keys: set[str]) -> frozenset[str]:
    resolved: set[str] = set()
    for name in drop.names:
        parts = _identifier_components(name)
        part = next(iter(parts), None)
        if part is None:
            continue
        if len(parts) > 1:
            resolved.add(".".join(parts))
            continue
        candidates: set[str] = set()
        for key in active_keys:
            key_parts = _identifier_components(key)
            if next(reversed(key_parts), None) == part:
                candidates.add(key)
        if len(candidates) == 1:
            resolved.update(candidates)
    return frozenset(resolved)


def _parse_index_suffix(masked: str, start: int, end: int) -> IndexSuffix | None:
    cursor = start
    stage = 0
    include_open: int | None = None
    include_close: int | None = None
    nulls_distinct = ""
    storage_open: int | None = None
    storage_close: int | None = None
    tablespace = ""
    while True:
        cursor = _skip_space(masked, cursor, end)
        if cursor == end:
            return IndexSuffix(
                include_open,
                include_close,
                nulls_distinct,
                storage_open,
                storage_close,
                tablespace,
                None,
            )
        include = _INCLUDE_RE.match(masked, cursor, end)
        storage = _WITH_RE.match(masked, cursor, end)
        if include is not None:
            if stage > 0:
                return None
            opening = include.end() - 1
            closing = _matching_paren(masked, opening, end)
            if closing is None:
                return None
            include_open = opening
            include_close = closing
            cursor = closing + 1
            stage = 1
            continue
        if (match := _NULLS_DISTINCT_RE.match(masked, cursor, end)) is not None:
            if stage > 1:
                return None
            cursor = match.end()
            nulls_distinct = _normalize_sql(match.group(0))
            stage = 2
            continue
        if storage is not None:
            if stage > _AFTER_NULLS_STAGE:
                return None
            opening = storage.end() - 1
            closing = _matching_paren(masked, opening, end)
            if closing is None:
                return None
            storage_open = opening
            storage_close = closing
            cursor = closing + 1
            stage = _AFTER_WITH_STAGE
            continue
        if (match := _TABLESPACE_RE.match(masked, cursor, end)) is not None:
            if stage > _AFTER_WITH_STAGE:
                return None
            cursor = match.end()
            tablespace = _normalize_identifier(match.group("tablespace"))
            stage = 4
            continue
        if (match := _WHERE_RE.match(masked, cursor, end)) is not None:
            predicate = masked[match.end() : end]
            if not predicate.strip() or not _has_balanced_parentheses(predicate):
                return None
            return IndexSuffix(
                include_open,
                include_close,
                nulls_distinct,
                storage_open,
                storage_close,
                tablespace,
                match.end(),
            )
        return None


def _skip_space(value: str, start: int, end: int) -> int:
    while start < end and value[start].isspace():
        start += 1
    return start


def _matching_paren(masked: str, opening: int, end: int | None = None) -> int | None:
    depth = 0
    position = opening
    limit = len(masked) if end is None else end
    while position < limit:
        char = masked[position]
        if char == '"':
            position = _quoted_identifier_end(masked, position, limit)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return None


def _quoted_identifier_end(value: str, start: int, end: int) -> int:
    cursor = start + 1
    while cursor < end:
        if value[cursor] != '"':
            cursor += 1
            continue
        if cursor + 1 < end and value[cursor + 1] == '"':
            cursor += 2
            continue
        return cursor + 1
    return end


def _has_balanced_parentheses(value: str) -> bool:
    depth = 0
    cursor = 0
    while cursor < len(value):
        if value[cursor] == '"':
            quoted_end = _closed_quoted_identifier_end(value, cursor, len(value))
            if quoted_end is None:
                return False
            cursor = quoted_end
            continue
        if value[cursor] == "(":
            depth += 1
        elif value[cursor] == ")":
            depth -= 1
            if depth < 0:
                return False
        cursor += 1
    return depth == 0


def _closed_quoted_identifier_end(value: str, start: int, end: int) -> int | None:
    cursor = start + 1
    while cursor < end:
        if value[cursor] != '"':
            cursor += 1
            continue
        if cursor + 1 < end and value[cursor + 1] == '"':
            cursor += 2
            continue
        return cursor + 1
    return None


def _quoted_identifier_spans(value: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(value):
        if value[cursor] != '"':
            cursor += 1
            continue
        quoted_end = _closed_quoted_identifier_end(value, cursor, len(value))
        end = len(value) if quoted_end is None else quoted_end
        spans.append((cursor, end))
        cursor = end
    return tuple(spans)


def _inside_spans(position: int, spans: tuple[tuple[int, int], ...]) -> bool:
    return any(start < position < end for start, end in spans)


def _statement_end(masked: str, start: int) -> int:
    cursor = start
    while cursor < len(masked):
        if masked[cursor] == '"':
            cursor = _quoted_identifier_end(masked, cursor, len(masked))
            continue
        if masked[cursor] == ";":
            return cursor
        cursor += 1
    return len(masked)


def _split_identifier_list(value: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    cursor = 0
    while cursor < len(value):
        if value[cursor] == '"':
            cursor = _quoted_identifier_end(value, cursor, len(value))
            continue
        if value[cursor] == ",":
            parts.append(value[start:cursor].strip())
            start = cursor + 1
        cursor += 1
    parts.append(value[start:].strip())
    return tuple(parts)


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
        elif char == "$" and (dollar_end := _dollar_quoted_literal_end(value, position)) is not None:
            position = dollar_end
            continue
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
        elif char == "$" and (dollar_end := _dollar_quoted_literal_end(value, position)) is not None:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(value[position:dollar_end])
            position = dollar_end
            continue
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


def _dollar_quoted_literal_end(value: str, start: int) -> int | None:
    if start > 0 and _is_identifier_character(value[start - 1]):
        return None
    delimiter_match = _DOLLAR_QUOTE_START_RE.match(value, start)
    if delimiter_match is None:
        return None
    delimiter = delimiter_match.group(0)
    closing = value.find(delimiter, delimiter_match.end())
    return None if closing < 0 else closing + len(delimiter)


def _is_identifier_character(char: str) -> bool:
    return char.isalnum() or char in {"_", "$"}


def _normalize_identifier(value: str) -> str:
    normalized = re.sub(r"\s*\.\s*", ".", _normalize_sql(value))

    def unquote_when_equivalent(match: re.Match[str]) -> str:
        body = match.group("body")
        return body if _SAFE_UNQUOTED_IDENTIFIER_RE.fullmatch(body) is not None else match.group(0)

    return _QUOTED_IDENTIFIER_RE.sub(unquote_when_equivalent, normalized)


def _identifier_components(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _IDENTIFIER_PART_RE.finditer(value))


def _has_local_justification(source: str, start: int, *, unique: bool) -> bool:
    previous_end = source.rfind("\n", 0, start)
    if previous_end < 0:
        return False
    previous_start = source.rfind("\n", 0, previous_end) + 1
    previous = source[previous_start:previous_end]
    return (
        _APP_READ_JUSTIFICATION_RE.fullmatch(previous) is not None
        or _REFERENTIAL_JUSTIFICATION_RE.fullmatch(previous) is not None
        or (unique and _UNIQUENESS_JUSTIFICATION_RE.fullmatch(previous) is not None)
    )
