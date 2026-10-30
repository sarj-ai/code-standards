from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from heapq import nsmallest
import os
from pathlib import Path, PurePosixPath
import re
from stat import S_ISREG
from typing import TYPE_CHECKING, NamedTuple, final, override

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
    source_location,
    sql_code_matches,
    sql_relation_key,
)
from sarj_sql_lint.rules._index_analysis import parse_indexes


if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


RESERVED_KEYWORDS = frozenset({"foreign", "key", "constraint", "alter", "table", "create", "add", "column"})


type _TableKey = tuple[str, ...]


class _IndexedColumns(NamedTuple):
    table: _TableKey
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _FileIndexes:
    path: Path
    identity: _FileIdentity
    indexes: frozenset[_IndexedColumns]


class _GapKind(StrEnum):
    TRAVERSAL = "traversal"
    CLASSIFICATION = "classification"
    STAT = "stat"
    READ = "read"
    OWNER = "owner"
    BYTE_LIMIT = "byte-limit"
    FILE_LIMIT = "file-limit"
    ENTRY_LIMIT = "entry-limit"


@dataclass(frozen=True, slots=True)
class _IndexGap:
    kind: _GapKind
    path: Path | None
    identity: _FileIdentity | None


@dataclass(frozen=True, slots=True)
class _IndexScan:
    files: tuple[_FileIndexes, ...]
    gaps: tuple[_IndexGap, ...]


@dataclass(frozen=True, slots=True)
class _IndexEvidence:
    indexes: frozenset[_IndexedColumns]
    complete: bool


@dataclass(slots=True)
class _DiscoveryBudget:
    visited: int = 0
    limit_hit: bool = False


_INDEX_SNAPSHOTS: ContextVar[dict[Path, _IndexScan] | None] = ContextVar("sql_index_analysis_snapshots", default=None)


@contextmanager
def index_analysis_session() -> Generator[None]:
    token = _INDEX_SNAPSHOTS.set({})
    try:
        yield
    finally:
        _INDEX_SNAPSHOTS.reset(token)


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
_STATEMENT_DELIMITER = re.compile(r";")
_COLUMN_DELIMITER = re.compile(r",")
_CLAUSE_DELIMITER = re.compile(r"[(),]")
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
    for _, stmt in _segments(masked, _STATEMENT_DELIMITER):
        _collect_constraint_indexes(stmt, indexed_cols)
    return indexed_cols


# Directory names marking the root of a migration tree where an index in any migration covers FKs across the tree.
_MIGRATION_ROOT_NAMES = frozenset({"migrations", "migration", "migrate", "drizzle"})

# Bounds on the sibling scan, so a pathological tree cannot turn a per-file lint
# into a repo-wide one.
_MAX_TREE_FILES = 600
# Count every directory entry, including non-SQL files, before retaining or classifying it.
_MAX_TREE_ENTRIES = 12_000
_MAX_TREE_BYTES = 1_000_000
_MAX_CACHED_SOURCE_LENGTH = 16_384
_MAX_SNAPSHOT_ROOTS = 64


def _tree_indexes(  # sarj-noqa: SARJ023 — bounded tree helpers stay adjacent.
    root: Path,
    *,
    current_path: Path,
    current_file: _FileIdentity,
) -> _IndexEvidence:
    try:
        root = root.resolve()
        current_path = current_path.resolve()
    except OSError:
        return _IndexEvidence(frozenset(), complete=False)
    snapshots = _INDEX_SNAPSHOTS.get()
    scan = None if snapshots is None else snapshots.get(root)
    if scan is None:
        scan = _scan_tree_indexes(root)
        if snapshots is not None and len(snapshots) < _MAX_SNAPSHOT_ROOTS:
            snapshots[root] = scan
    owners = _snapshot_current_paths(scan.files, current_path, current_file)
    indexes = frozenset(
        index
        for file in scan.files
        if file.path not in owners and file.identity != current_file
        for index in file.indexes
    )
    complete = all(_gap_is_current(gap, owners, current_file) for gap in scan.gaps)
    return _IndexEvidence(indexes, complete)


def _gap_is_current(gap: _IndexGap, owners: frozenset[Path], current_file: _FileIdentity) -> bool:
    if gap.kind in {_GapKind.TRAVERSAL, _GapKind.FILE_LIMIT, _GapKind.ENTRY_LIMIT}:
        return False
    return gap.path in owners or gap.identity == current_file


def _snapshot_current_paths(files: tuple[_FileIndexes, ...], current: Path, identity: _FileIdentity) -> frozenset[Path]:
    owners = {current}
    spelling = str(current).casefold()
    candidates = {file.path for file in files if str(file.path).casefold() == spelling}
    # Case-folding only selects spellings to probe; live physical identity proves each owner.
    for candidate in candidates - owners:
        try:
            metadata = candidate.stat()
        except OSError:
            continue
        if _FileIdentity(metadata.st_dev, metadata.st_ino) == identity:
            owners.add(candidate)
    return frozenset(owners)


def _scan_tree_indexes(root: Path) -> _IndexScan:
    files: list[_FileIndexes] = []
    gaps: list[_IndexGap] = []
    candidates = nsmallest(_MAX_TREE_FILES + 1, _migration_sql_paths(root, gaps))
    if len(candidates) > _MAX_TREE_FILES:
        gaps.append(_IndexGap(_GapKind.FILE_LIMIT, None, None))
    for candidate in candidates[:_MAX_TREE_FILES]:
        try:
            metadata = candidate.stat()
        except OSError:
            gaps.append(_IndexGap(_GapKind.STAT, candidate, None))
            continue
        if not S_ISREG(metadata.st_mode):
            continue
        identity = _FileIdentity(metadata.st_dev, metadata.st_ino)
        if metadata.st_size > _MAX_TREE_BYTES:
            gaps.append(_IndexGap(_GapKind.BYTE_LIMIT, candidate, identity))
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            gaps.append(_IndexGap(_GapKind.READ, candidate, identity))
            continue
        try:
            owner = candidate.resolve() if candidate.is_symlink() else candidate
        except OSError:
            gaps.append(_IndexGap(_GapKind.OWNER, candidate, identity))
            continue
        files.append(_FileIndexes(owner, identity, _source_indexes(text)))
    return _IndexScan(tuple(files), tuple(gaps))


def _migration_sql_paths(root: Path, gaps: list[_IndexGap]) -> Iterator[Path]:
    directories = [root]
    budget = _DiscoveryBudget()
    while directories:
        directory = directories.pop()
        try:
            with os.scandir(directory) as entries:
                yield from _directory_paths(entries, directories, gaps, budget)
        except OSError:
            gaps.append(_IndexGap(_GapKind.TRAVERSAL, directory, None))
        if budget.limit_hit:
            return


def _directory_paths(
    entries: Iterator[os.DirEntry[str]], directories: list[Path], gaps: list[_IndexGap], budget: _DiscoveryBudget
) -> Iterator[Path]:
    for entry in entries:
        # One lookahead distinguishes an exhausted budget from a complete tree.
        if budget.visited >= _MAX_TREE_ENTRIES:
            gaps.append(_IndexGap(_GapKind.ENTRY_LIMIT, None, None))
            budget.limit_hit = True
            return
        budget.visited += 1
        path = _sql_entry_path(entry, directories, gaps)
        if path is not None:
            yield path


def _sql_entry_path(entry: os.DirEntry[str], directories: list[Path], gaps: list[_IndexGap]) -> Path | None:
    is_directory = _entry_is_directory(entry, gaps)
    if is_directory is None:
        return None
    path = Path(entry.path)
    if is_directory:
        directories.append(path)
    return path if path.match("*.sql") else None


def _entry_is_directory(entry: os.DirEntry[str], gaps: list[_IndexGap]) -> bool | None:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        gaps.append(_IndexGap(_GapKind.CLASSIFICATION, Path(entry.path), None))
        return None


def _source_indexes(source: str) -> frozenset[_IndexedColumns]:
    if len(source) > _MAX_CACHED_SOURCE_LENGTH:
        return _index_entries(source)
    return _cached_source_indexes(source)


@lru_cache(maxsize=_MAX_TREE_FILES)
def _cached_source_indexes(source: str) -> frozenset[_IndexedColumns]:
    return _index_entries(source)


def _index_entries(source: str) -> frozenset[_IndexedColumns]:
    return frozenset(
        _IndexedColumns(table, columns)
        for table, indexes in _collect_indexes(source).items()
        for columns in indexes
        if columns
    )


def _sibling_indexes(path: Path, table: _TableKey) -> _IndexEvidence:
    root = _migration_root(path)
    if root is None:
        return _IndexEvidence(frozenset(), complete=True)
    try:
        metadata = path.stat()
    except FileNotFoundError:
        # Pure source checks can use a virtual migration path without a live tree.
        try:
            root.stat()
        except FileNotFoundError:
            return _IndexEvidence(frozenset(), complete=True)
        except OSError:
            pass
        return _IndexEvidence(frozenset(), complete=False)
    except OSError:
        return _IndexEvidence(frozenset(), complete=False)
    if not S_ISREG(metadata.st_mode):
        return _IndexEvidence(frozenset(), complete=False)
    evidence = _tree_indexes(root, current_path=path, current_file=_FileIdentity(metadata.st_dev, metadata.st_ino))
    return _IndexEvidence(
        frozenset(index for index in evidence.indexes if _same_relation(index.table, table)), evidence.complete
    )


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
            (
                "Sibling discovery classifies at most 12,000 directory entries, with one lookahead to detect exhaustion, "
                "and parses at most 600 SQL candidates."
            ),
            "Complete discovery selects the lexicographically first 600 SQL candidates in the migration tree.",
            (
                "Unavailable or budget-excluded sibling evidence, including exhausted directory discovery, prevents a "
                "missing-index proof; known indexes remain usable."
            ),
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

        for char_offset, stmt in _segments(masked, _STATEMENT_DELIMITER):
            if "REFERENCES" in stmt.upper() and (table_match := TABLE_SCOPE_PATTERN.search(stmt)):
                full_table = normalize_sql_identifier(table_match.group(1))
                table = sql_relation_key(table_match.group(1))
                table_indexes = self._local_table_indexes(indexed_cols_by_table, table)
                siblings = _sibling_indexes(path, table)
                table_indexes.update(index.columns for index in siblings.indexes)

                ctx = _StmtContext(path, masked, stmt, char_offset, full_table, table_match.end(), is_dump)
                if siblings.complete:
                    diags.extend(self._check_fk_constraints(ctx, table_indexes))

        return diags

    @staticmethod
    def _local_table_indexes(
        indexed_cols_by_table: dict[_TableKey, set[tuple[str, ...]]], table: _TableKey
    ) -> set[tuple[str, ...]]:
        return {
            columns
            for indexed_table, indexes in indexed_cols_by_table.items()
            if _same_relation(indexed_table, table)
            for columns in indexes
        }

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
                location = source_location(ctx.masked, match_offset)
                diags.append(
                    Diagnostic(
                        path=ctx.path,
                        line=location.line,
                        col=location.column,
                        code=self.code,
                        message=_message(", ".join(fk_cols), ctx.full_table, is_dump=ctx.is_dump),
                    )
                )

        # Mask table-level FK definitions before inspecting inline column references
        body = ctx.stmt[ctx.header_end :]
        body = _FK_CLEAN_PATTERN.sub(lambda m: " " * len(m.group(0)), body)

        # Align segment_start with source using header_end and fixed-length substitutions.
        for relative_start, segment in _segments(body, _COLUMN_DELIMITER):
            segment_start = ctx.header_end + relative_start
            if _is_index_requiring_inline_reference(segment) and (col_match := INLINE_COLUMN_PATTERN.search(segment)):
                col_name = _normalize_name(col_match.group(1))
                if col_name not in RESERVED_KEYWORDS and not _has_covering_index(indexes, (col_name,)):
                    # Point at the column token itself, not the segment start,
                    # so a multi-line column definition lands on its own line.
                    col_offset = ctx.char_offset + segment_start + col_match.start(1)
                    location = source_location(ctx.masked, col_offset)
                    diags.append(
                        Diagnostic(
                            path=ctx.path,
                            line=location.line,
                            col=location.column,
                            code=self.code,
                            message=_message(col_name, ctx.full_table, is_dump=ctx.is_dump),
                        )
                    )
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
    for match in sql_code_matches(_CLAUSE_DELIMITER, statement):
        position = match.start()
        if position < start:
            continue
        char = match.group()
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
    for _, segment in _segments(body, _COLUMN_DELIMITER):
        if TABLE_PK_OR_UNIQUE_PATTERN.search(segment):
            continue
        inline_match = INLINE_PK_OR_UNIQUE_PATTERN.search(segment)
        if inline_match is None:
            continue
        column = _normalize_name(inline_match.group(1))
        if column in RESERVED_KEYWORDS:
            continue
        indexed_cols.setdefault(full_table, set()).add((column,))


def _segments(source: str, delimiter: re.Pattern[str]) -> Iterator[tuple[int, str]]:
    start = 0
    for match in sql_code_matches(delimiter, source):
        yield start, source[start : match.start()]
        start = match.end()
    yield start, source[start:]
