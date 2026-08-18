from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
from typing import NamedTuple, final, override

from sarj_sql_lint.rule_base import (
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
)


RESERVED_KEYWORDS = frozenset({"foreign", "key", "constraint", "alter", "table", "create", "add", "column"})


class _IndexedColumn(NamedTuple):
    table: str
    column: str


def _mask_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), sql)
    sql = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), sql)

    def mask_literal(m: re.Match[str]) -> str:
        s = m.group(0)
        return f"'{re.sub(r'[^\n]', ' ', s[1:-1])}'"

    return re.sub(r"'(?:''|[^'])*'", mask_literal, sql)


CREATE_INDEX_PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?[\s\S]*?\bON\s+(?:ONLY\s+)?([a-zA-Z0-9_\"\.]+)\s*(?:USING\s+[a-zA-Z0-9_]+\s*)?\(\s*([\s\S]*?)\)",
    re.IGNORECASE,
)
TABLE_SCOPE_PATTERN = re.compile(
    r"\b(?:CREATE|ALTER)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:ONLY\s+)?([a-zA-Z0-9_\"\.]+)",
    re.IGNORECASE,
)
TABLE_FK_PATTERN = re.compile(
    r"\bFOREIGN\s+KEY\s*\(\s*([a-zA-Z0-9_,\s\"]+)\s*\)\s*REFERENCES\b",
    re.IGNORECASE,
)
TABLE_PK_OR_UNIQUE_PATTERN = re.compile(
    r"\b(?:PRIMARY\s+KEY|UNIQUE)\s*\(\s*([a-zA-Z0-9_,\s\"]+)\s*\)",
    re.IGNORECASE,
)
INLINE_COLUMN_PATTERN = re.compile(
    r"(?:\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?)?\b([a-zA-Z0-9_\"]+)\b[\s\S]*?\bREFERENCES\s+[a-zA-Z0-9_\"\.]+\b",
    re.IGNORECASE,
)
PRIMARY_OR_UNIQUE_KEYWORD = re.compile(r"\b(PRIMARY\s+KEY|UNIQUE)\b", re.IGNORECASE)
INLINE_PK_OR_UNIQUE_PATTERN = re.compile(
    r"(?:\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?)?\b([a-zA-Z0-9_\"]+)\b[\s\S]*?\b(?:PRIMARY\s+KEY|UNIQUE)\b",
    re.IGNORECASE,
)
_FK_CLEAN_PATTERN = re.compile(
    r'\bFOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[a-zA-Z0-9_"\.]+(?:\([^)]*\))?', re.IGNORECASE
)


def _normalize_name(name: str) -> str:
    clean = name.strip()
    clean = re.sub(r"\s+(?:ASC|DESC|NULLS\s+FIRST|NULLS\s+LAST)\b.*", "", clean, flags=re.IGNORECASE)
    clean = clean.replace('"', "").strip()
    return clean.lower()


def _collect_indexes(masked: str) -> dict[str, set[tuple[str, ...]]]:
    indexed_cols: dict[str, set[tuple[str, ...]]] = {}
    for match in CREATE_INDEX_PATTERN.finditer(masked):
        full_table = _normalize_name(match.group(1))
        base_table = full_table.split(".")[-1]
        cols = tuple(normalized for column in match.group(2).split(",") if (normalized := _normalize_name(column)))
        if cols:
            indexed_cols.setdefault(full_table, set()).add(cols)
            indexed_cols.setdefault(base_table, set()).add(cols)

    for stmt in masked.split(";"):
        table_match = TABLE_SCOPE_PATTERN.search(stmt)
        if not table_match:
            continue
        full_table = _normalize_name(table_match.group(1))
        base_table = full_table.split(".")[-1]
        for pk_match in TABLE_PK_OR_UNIQUE_PATTERN.finditer(stmt):
            pk_cols = tuple(
                normalized for column in pk_match.group(1).split(",") if (normalized := _normalize_name(column))
            )
            if pk_cols:
                indexed_cols.setdefault(full_table, set()).add(pk_cols)
                indexed_cols.setdefault(base_table, set()).add(pk_cols)
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
            indexed_cols.setdefault(base_table, set()).add((column,))
    return indexed_cols


# Directory names marking the root of a migration tree where an index in any migration covers FKs across the tree.
_MIGRATION_ROOT_NAMES = frozenset({"migrations", "migration", "migrate", "drizzle"})

# Bounds on the sibling scan, so a pathological tree cannot turn a per-file lint
# into a repo-wide one.
_MAX_TREE_FILES = 600
_MAX_TREE_BYTES = 1_000_000


def _migration_root(path: Path) -> Path | None:  # sarj-noqa: SARJ023 — bounded tree helpers stay adjacent.
    for parent in path.parents:
        if parent.name.lower() in _MIGRATION_ROOT_NAMES:
            return parent
    return None


@lru_cache(maxsize=64)
def _tree_leading_indexed(  # sarj-noqa: SARJ023 — bounded tree helpers stay adjacent.
    root: Path,
) -> frozenset[_IndexedColumn]:
    pairs: set[_IndexedColumn] = set()
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
        for table, cols in _collect_indexes(_mask_literals_and_comments(text)).items():
            pairs.update(_IndexedColumn(table, idx[0]) for idx in cols if idx)
    return frozenset(pairs)


def _sibling_indexed(path: Path, tables: tuple[str, ...]) -> set[str]:
    if not tables:
        return set()
    try:
        if not path.is_file():
            return set()
    except OSError:
        return set()
    root = _migration_root(path)
    if root is None:
        return set()
    wanted = set(tables)
    return {col for table, col in _tree_leading_indexed(root) if table in wanted}


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
        summary="FOREIGN KEY column missing index — causes full-table scans and locks on parent row deletes.",
        rationale="PostgreSQL does not automatically index referencing columns, so parent updates and deletes may scan the child table.",
        remediation="Create an index whose leading columns cover the foreign-key columns on the child table.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=("A bounded scan includes indexes from sibling files in the same migration tree.",),
        examples=(
            RuleExample(
                example_id="unindexed-foreign-key",
                title="Foreign key without a child-table index",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql",
                        "CREATE TABLE orders (customer_id BIGINT REFERENCES customer(id));\n",
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
                        "CREATE TABLE orders (customer_id BIGINT REFERENCES customer(id));\nCREATE INDEX orders_customer_id_idx ON orders(customer_id);\n",
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
        if is_mysql(source):
            return []
        diags: list[Diagnostic] = []
        masked = _mask_literals_and_comments(source)
        indexed_cols_by_table = _collect_indexes(masked)
        is_dump = is_dump_file(source, path)

        char_offset = 0
        for stmt in masked.split(";"):
            if "REFERENCES" in stmt.upper() and (table_match := TABLE_SCOPE_PATTERN.search(stmt)):
                full_table = _normalize_name(table_match.group(1))
                base_table = full_table.split(".")[-1]
                table_indexes = indexed_cols_by_table.get(full_table, set()) | indexed_cols_by_table.get(
                    base_table, set()
                )
                leading_indexed = {idx[0] for idx in table_indexes if idx}
                leading_indexed |= _sibling_indexed(path, (full_table, base_table))

                ctx = _StmtContext(path, masked, stmt, char_offset, full_table, table_match.end(), is_dump)
                diags.extend(self._check_fk_constraints(ctx, leading_indexed))

            char_offset += len(stmt) + 1
        return diags

    def _check_fk_constraints(
        self,
        ctx: _StmtContext,
        leading_indexed: set[str],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []

        for fk_match in TABLE_FK_PATTERN.finditer(ctx.stmt):
            fk_cols = tuple(_normalize_name(c) for c in fk_match.group(1).split(","))
            leading_col = fk_cols[0] if fk_cols else ""
            if leading_col and leading_col not in leading_indexed:
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
                        message=_message(leading_col, ctx.full_table, is_dump=ctx.is_dump),
                    )
                )

        # Mask table-level FK definitions before inspecting inline column references
        body = ctx.stmt[ctx.header_end :]
        body = _FK_CLEAN_PATTERN.sub(lambda m: " " * len(m.group(0)), body)

        # Align segment_start with source using header_end and fixed-length substitutions.
        segment_start = ctx.header_end
        for segment in body.split(","):
            if (
                "REFERENCES" in segment.upper()
                and not TABLE_FK_PATTERN.search(segment)
                and not PRIMARY_OR_UNIQUE_KEYWORD.search(segment)
                and "FOREIGN KEY" not in segment.upper()
            ) and (col_match := INLINE_COLUMN_PATTERN.search(segment)):
                col_name = _normalize_name(col_match.group(1))
                if col_name not in RESERVED_KEYWORDS and col_name not in leading_indexed:
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
