from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
from typing import NamedTuple, final, override

from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_PART,
    SQL_WHITESPACE,
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_mysql,
    mask_sql_literals_and_comments,
    normalize_sql_identifier,
    sql_relation_key,
)
from sarj_sql_lint.rules._index_analysis import parse_indexes


RESERVED_KEYWORDS = frozenset({"foreign", "key", "constraint", "alter", "table", "create", "add", "column"})


type _TableKey = tuple[str, ...]


class _IndexedColumns(NamedTuple):
    table: _TableKey
    columns: tuple[str, ...]


_QUALIFIED_IDENTIFIER = (
    rf"{POSTGRES_IDENTIFIER_PART}(?:\s*\.\s*{POSTGRES_IDENTIFIER_PART})*(?![A-Za-z0-9_$\u0080-\U0010ffff]|\s*\.)"
)
_IDENTIFIER_LIST = rf"{POSTGRES_IDENTIFIER_PART}(?:\s*,\s*{POSTGRES_IDENTIFIER_PART})*"
_IDENTIFIER_RE = re.compile(POSTGRES_IDENTIFIER_PART)
_COLUMN_KEY = re.compile(
    rf"(?P<column>{POSTGRES_IDENTIFIER_PART})(?:\s+(?:ASC|DESC))?(?:\s+NULLS\s+(?:FIRST|LAST))?",
    re.IGNORECASE,
)
_EMPTY_PREDICATE = re.compile(r"[\s(]*false[\s)]*", re.IGNORECASE | re.ASCII)
TABLE_SCOPE_PATTERN = re.compile(
    rf"\b(?:CREATE|ALTER)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:ONLY\s+)?({_QUALIFIED_IDENTIFIER})",
    re.IGNORECASE,
)
TABLE_FK_PATTERN = re.compile(
    rf"\bFOREIGN\s+KEY\s*\(\s*({_IDENTIFIER_LIST})\s*\)\s*REFERENCES\s+"
    rf"{_QUALIFIED_IDENTIFIER}(?:\s*\([^)]*\))?",
    re.IGNORECASE,
)
TABLE_PK_OR_UNIQUE_PATTERN = re.compile(
    rf"\b(?:PRIMARY\s+KEY|UNIQUE)\s*\(\s*({_IDENTIFIER_LIST})\s*\)",
    re.IGNORECASE,
)
INLINE_COLUMN_PATTERN = re.compile(
    rf"(?:\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?)?"
    rf"(?<![A-Za-z0-9_$\u0080-\U0010ffff])({POSTGRES_IDENTIFIER_PART})(?=\s)[\s\S]*?\bREFERENCES\s+{_QUALIFIED_IDENTIFIER}",
    re.IGNORECASE,
)
PRIMARY_OR_UNIQUE_KEYWORD = re.compile(r"\b(PRIMARY\s+KEY|UNIQUE)\b", re.IGNORECASE)
INLINE_PK_OR_UNIQUE_PATTERN = re.compile(
    rf"(?:\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?)?"
    rf"(?<![A-Za-z0-9_$\u0080-\U0010ffff])({POSTGRES_IDENTIFIER_PART})(?=\s)[\s\S]*?\b(?:PRIMARY\s+KEY|UNIQUE)\b",
    re.IGNORECASE,
)
_FK_CLEAN_PATTERN = re.compile(
    rf"\bFOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+{_QUALIFIED_IDENTIFIER}(?:\([^)]*\))?", re.IGNORECASE
)
_INDEX_REQUIRING_ACTION_RE = re.compile(
    r"\bON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|SET\s+NULL|SET\s+DEFAULT)\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    clean = name.strip(SQL_WHITESPACE)
    match = _COLUMN_KEY.fullmatch(clean)
    return normalize_sql_identifier(match.group("column")) if match is not None else clean


def _column_names(value: str) -> tuple[str, ...]:
    return tuple(_normalize_name(match.group()) for match in _IDENTIFIER_RE.finditer(value))


def _collect_indexes(source: str) -> dict[_TableKey, set[tuple[str, ...]]]:
    indexed_cols: dict[_TableKey, set[tuple[str, ...]]] = {}
    for index in parse_indexes(source, include_executable_bodies=True):
        if _EMPTY_PREDICATE.fullmatch(index.predicate) is not None:
            continue
        full_table = sql_relation_key(index.table)
        cols = tuple(_normalize_name(column) for column in index.keys)
        if cols:
            indexed_cols.setdefault(full_table, set()).add(cols)

    masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
    for stmt in masked.split(";"):
        _collect_constraint_indexes(stmt, indexed_cols)
    return indexed_cols


# Directory names marking the root of a migration tree where an index in any migration covers FKs across the tree.
_MIGRATION_ROOT_NAMES = frozenset({"migrations", "migration", "migrate", "drizzle"})

# Bounds on the sibling scan, so a pathological tree cannot turn a per-file lint
# into a repo-wide one.
_MAX_TREE_FILES = 600
_MAX_TREE_BYTES = 1_000_000


@lru_cache(maxsize=64)
def _tree_indexes(  # sarj-noqa: SARJ023 — bounded tree helpers stay adjacent.
    root: Path,
) -> frozenset[_IndexedColumns]:
    indexes: set[_IndexedColumns] = set()
    try:
        candidates = sorted(root.rglob("*.sql"))[:_MAX_TREE_FILES]
    except OSError:
        return frozenset()
    for candidate in candidates:
        try:
            if candidate.stat().st_size > _MAX_TREE_BYTES:
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for table, cols in _collect_indexes(text).items():
            indexes.update(_IndexedColumns(table, index) for index in cols if index)
    return frozenset(indexes)


def _sibling_indexes(path: Path, table: _TableKey) -> set[tuple[str, ...]]:
    try:
        if not path.is_file():
            return set()
    except OSError:
        return set()
    root = _migration_root(path)
    if root is None:
        return set()
    return {columns for indexed_table, columns in _tree_indexes(root) if _same_relation(indexed_table, table)}


def _same_relation(left: _TableKey, right: _TableKey) -> bool:
    return left == right or (left[-1] == right[-1] and (len(left) == 1 or len(right) == 1))


def _migration_root(path: Path) -> Path | None:  # sarj-noqa: SARJ023 — bounded tree helpers stay adjacent.
    for parent in path.parents:
        if parent.name.lower() in _MIGRATION_ROOT_NAMES:
            return parent
    return None


def _has_covering_index(indexes: set[tuple[str, ...]], columns: tuple[str, ...]) -> bool:
    return any(_index_covers(index, columns) for index in indexes)


def _index_covers(index: tuple[str, ...], columns: tuple[str, ...]) -> bool:
    return len(index) >= len(columns) and set(index[: len(columns)]) == set(columns)


@dataclass(frozen=True)
class _StmtContext:
    path: Path
    masked: str
    stmt: str
    char_offset: int
    full_table: str
    header_end: int
    is_dump: bool


@final
class RequireFkIndex(Rule):
    id = "require-fk-index"
    code = "SARJ112"
    documentation = RuleDocumentation(
        summary="Cascading or set-value FOREIGN KEY action lacks a child-table index.",
        rationale=(
            "PostgreSQL does not automatically index referencing columns, so cascading deletes/updates and SET NULL/DEFAULT "
            "actions may scan and lock the child table."
        ),
        remediation="Create an index whose leading columns cover the foreign-key columns on the child table.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only CASCADE, SET NULL, and SET DEFAULT actions are checked; ordinary NO ACTION/RESTRICT foreign keys stay silent.",
            "Explicit schemas and quoted identifier case remain distinct; mixed qualification is unresolved and may refer to the same relation.",
            "Literal FALSE partial indexes cannot cover foreign keys. Other partial predicates retain conservative legacy coverage; arbitrary implication and migration-time index drops are not evaluated.",
            "Unicode escape identifiers (U&) and server-side identifier truncation are not resolved.",
            "A bounded scan includes indexes from sibling files in the same migration tree.",
            "Schema dumps are excluded; add the owning change to an authored migration.",
        ),
        examples=(
            RuleExample(
                example_id="unindexed-foreign-key",
                title="Foreign key without a child-table index",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql",
                        "CREATE TABLE orders (customer_id BIGINT REFERENCES customer(id) ON DELETE CASCADE);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_orders.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="indexed-foreign-key",
                title="Foreign key covered by an index",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql",
                        "CREATE TABLE orders (customer_id BIGINT REFERENCES customer(id) ON DELETE CASCADE);\nCREATE INDEX orders_customer_id_idx ON orders(customer_id);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_orders.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_mysql(source) or is_dump_file(source, path):
            return []
        diags: list[Diagnostic] = []
        masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
        indexed_cols_by_table = _collect_indexes(source)
        is_dump = is_dump_file(source, path)

        char_offset = 0
        for stmt in masked.split(";"):
            if "REFERENCES" in stmt.upper() and (table_match := TABLE_SCOPE_PATTERN.search(stmt)):
                full_table = normalize_sql_identifier(table_match.group(1))
                table = sql_relation_key(table_match.group(1))
                table_indexes = {
                    columns
                    for indexed_table, indexes in indexed_cols_by_table.items()
                    if _same_relation(indexed_table, table)
                    for columns in indexes
                }
                table_indexes |= _sibling_indexes(path, table)

                ctx = _StmtContext(path, masked, stmt, char_offset, full_table, table_match.end(), is_dump)
                diags.extend(self._check_fk_constraints(ctx, table_indexes))

            char_offset += len(stmt) + 1
        return diags

    def _check_fk_constraints(
        self,
        ctx: _StmtContext,
        indexes: set[tuple[str, ...]],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []

        fk_matches = tuple(TABLE_FK_PATTERN.finditer(ctx.stmt))
        for position, fk_match in enumerate(fk_matches):
            boundary = fk_matches[position + 1].start() if position + 1 < len(fk_matches) else len(ctx.stmt)
            boundary = min(boundary, _clause_end(ctx.stmt, fk_match.end()))
            if _INDEX_REQUIRING_ACTION_RE.search(ctx.stmt, fk_match.end(), boundary) is None:
                continue
            fk_cols = _column_names(fk_match.group(1))
            if fk_cols and not _has_covering_index(indexes, fk_cols):
                # `fk_match.start()`, NOT `ctx.stmt.find(fk_match.group(0))` — the
                # latter re-finds the clause by value and resolves to the first
                # identical one, mis-attributing the line and so making the
                # finding unsuppressable by the line-keyed `-- sarj-noqa`.
                match_offset = ctx.char_offset + fk_match.start()
                lineno = ctx.masked[:match_offset].count("\n") + 1
                col_pos = match_offset - ctx.masked.rfind("\n", 0, match_offset)
                diags.append(
                    Diagnostic(
                        path=ctx.path,
                        line=lineno,
                        col=max(1, col_pos),
                        code=self.code,
                        message=_message(", ".join(fk_cols), ctx.full_table, is_dump=ctx.is_dump),
                    )
                )

        # Mask table-level FK definitions before inspecting inline column references
        body = ctx.stmt[ctx.header_end :]
        body = _FK_CLEAN_PATTERN.sub(lambda m: " " * len(m.group(0)), body)

        # Align segment_start with source using header_end and fixed-length substitutions.
        segment_start = ctx.header_end
        for segment in body.split(","):
            if _is_index_requiring_inline_reference(segment) and (col_match := INLINE_COLUMN_PATTERN.search(segment)):
                col_name = _normalize_name(col_match.group(1))
                if col_name not in RESERVED_KEYWORDS and not _has_covering_index(indexes, (col_name,)):
                    # Point at the column token itself, not the segment start,
                    # so a multi-line column definition lands on its own line.
                    col_offset = ctx.char_offset + segment_start + col_match.start(1)
                    lineno = ctx.masked[:col_offset].count("\n") + 1
                    col_pos = col_offset - ctx.masked.rfind("\n", 0, col_offset)
                    diags.append(
                        Diagnostic(
                            path=ctx.path,
                            line=lineno,
                            col=max(1, col_pos),
                            code=self.code,
                            message=_message(col_name, ctx.full_table, is_dump=ctx.is_dump),
                        )
                    )
            segment_start += len(segment) + 1
        return diags


def _message(column: str, table: str, *, is_dump: bool) -> str:
    head = (
        f"Foreign key column `{column}` on table `{table}` should have a corresponding `CREATE INDEX` "
        "to prevent full table scans and lock contention during parent row deletes."
    )
    if is_dump:
        return f"{head} This file is a schema dump — add the index in a migration, not here."
    return head


def _clause_end(statement: str, start: int) -> int:
    depth = 0
    for position in range(start, len(statement)):
        char = statement[position]
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return position
            depth -= 1
        elif char == "," and depth == 0:
            return position
    return len(statement)


def _is_index_requiring_inline_reference(segment: str) -> bool:
    upper = segment.upper()
    return (
        "REFERENCES" in upper
        and "FOREIGN KEY" not in upper
        and TABLE_FK_PATTERN.search(segment) is None
        and PRIMARY_OR_UNIQUE_KEYWORD.search(segment) is None
        and _INDEX_REQUIRING_ACTION_RE.search(segment) is not None
    )


def _collect_constraint_indexes(stmt: str, indexed_cols: dict[_TableKey, set[tuple[str, ...]]]) -> None:
    table_match = TABLE_SCOPE_PATTERN.search(stmt)
    if not table_match:
        return
    full_table = sql_relation_key(table_match.group(1))
    for pk_match in TABLE_PK_OR_UNIQUE_PATTERN.finditer(stmt):
        pk_cols = _column_names(pk_match.group(1))
        if pk_cols:
            indexed_cols.setdefault(full_table, set()).add(pk_cols)
    body = stmt[table_match.end() :]
    for segment in body.split(","):
        if TABLE_PK_OR_UNIQUE_PATTERN.search(segment):
            continue
        inline_match = INLINE_PK_OR_UNIQUE_PATTERN.search(segment)
        if inline_match is None:
            continue
        column = _normalize_name(inline_match.group(1))
        if column in RESERVED_KEYWORDS:
            continue
        indexed_cols.setdefault(full_table, set()).add((column,))
