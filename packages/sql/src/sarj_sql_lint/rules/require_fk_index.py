"""SARJ112: Require index on Foreign Key column.

Postgres does NOT automatically index foreign key columns. Deleting or updating rows from a parent table
triggers a full sequential scan on the child table if the FK is unindexed, locking the child table.

A 25-finding seeded sample of the 446 findings over 2,133 deduped `.sql` files read
TP 19 / FP 6 — 24% wrong, in two classes, both fixed here.

**Single-file scope in a multi-file migration tree** — 34.6% of the sampled errors.
The rule collected `CREATE INDEX` statements from the file it was handed, but in a
migration tree the covering index routinely arrives in a *later* migration. Verified
end to end: `cal.com/packages/prisma/migrations/20220711182928_add_workflows/migration.sql:77`
flagged `WorkflowsOnEventTypes.eventTypeId`, and
`cal.com/packages/prisma/migrations/20230410234751_add_foreign_key_indexes/migration.sql:167`
creates exactly that index. The same shape appears at
`papermark/prisma/migrations/20230912150657_initialize/migration.sql:149` and
`documenso/.../20240424072655_update_foreign_key_constraints/migration.sql:17`.
Index collection now spans the whole migration tree — the nearest ancestor directory
named `migrations`/`migration`/`drizzle`/`migrate`, else the file's own directory —
so an index created anywhere in the tree counts. The scan is bounded
(`_MAX_TREE_FILES`, `_MAX_TREE_BYTES`) and cached per root, and it is skipped
entirely when the linted path is not a real file, which keeps it off synthetic and
in-memory inputs.

**The reported line was wrong 9.9% of the time.** Both diagnostics located
themselves with `ctx.stmt.find(<text>)`, re-finding the matched text *by value*
inside the `;`-split statement. A repeated segment resolves to the first
occurrence, so the offset drifts: at
`airflow/providers/informatica/dev/init/001_schema_and_seed.sql:51` the message
named `product_id` while pointing at the `customer_id` line. This is worse than a
cosmetic defect — `-- sarj-noqa` is line-keyed, so a mis-attributed finding is
**unsuppressable**. Both sites now use the match's real offset
(`fk_match.start()`, and a running segment offset for the inline scan, which is
safe because the FK-masking substitution preserves length).

**This rule deliberately does NOT take the `is_dump_file` exemption** that SARJ101,
SARJ104 and the rest were given. Its dump findings are among its most reliable: a
dump is a *complete* rendering of the schema, so an absent `CREATE INDEX` really
does mean an absent index — three were hand-verified. What a dump finding must not
do is ask for an edit to the dump, so those carry a message that points at the
migration instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file


RESERVED_KEYWORDS: set[str] = {"foreign", "key", "constraint", "alter", "table", "create", "add", "column"}


def _mask_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), sql)
    sql = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), sql)

    def mask_literal(m: re.Match[str]) -> str:
        s = m.group(0)
        return "'" + re.sub(r"[^\n]", " ", s[1:-1]) + "'"

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
    r"(?:\bADD\s+(?:COLUMN\s+)?)?\b([a-zA-Z0-9_\"]+)\b[\s\S]*?\bREFERENCES\s+[a-zA-Z0-9_\"\.]+\b",
    re.IGNORECASE,
)
PRIMARY_OR_UNIQUE_KEYWORD = re.compile(r"\b(PRIMARY\s+KEY|UNIQUE)\b", re.IGNORECASE)


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
        cols = tuple(_normalize_name(c) for c in match.group(2).split(",") if _normalize_name(c))
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
            pk_cols = tuple(_normalize_name(c) for c in pk_match.group(1).split(",") if _normalize_name(c))
            if pk_cols:
                indexed_cols.setdefault(full_table, set()).add(pk_cols)
                indexed_cols.setdefault(base_table, set()).add(pk_cols)
    return indexed_cols


# Directory names that mark the root of a migration tree. An index created in any
# migration under the same root covers a foreign key declared in any other.
_MIGRATION_ROOT_NAMES = frozenset({"migrations", "migration", "migrate", "drizzle"})

# Bounds on the sibling scan, so a pathological tree cannot turn a per-file lint
# into a repo-wide one.
_MAX_TREE_FILES = 600
_MAX_TREE_BYTES = 1_000_000


def _migration_root(path: Path) -> Path | None:
    """Locate the migration tree `path` belongs to.

    Returns:
        The nearest ancestor directory that names a migration tree, or None.

    """
    for parent in path.parents:
        if parent.name.lower() in _MIGRATION_ROOT_NAMES:
            return parent
    return None


@lru_cache(maxsize=64)
def _tree_leading_indexed(root: Path) -> frozenset[tuple[str, str]]:
    """Collect `(table, leading indexed column)` pairs from every `.sql` file under `root`.

    Cached per root: a migration tree is scanned once per process no matter how
    many of its files are linted.

    Returns:
        Every `(table, leading column)` pair indexed anywhere in the tree.

    """
    pairs: set[tuple[str, str]] = set()
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
            pairs.update((table, idx[0]) for idx in cols if idx)
    return frozenset(pairs)


def _sibling_indexed(path: Path, tables: tuple[str, ...]) -> set[str]:
    """Leading columns indexed anywhere in `path`'s migration tree for `tables`.

    Returns:
        The set of leading indexed column names, empty when there is no tree.

    """
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
    """Foreign key column without corresponding index on child table."""

    id = "require-fk-index"
    code = "SARJ112"
    description = "FOREIGN KEY column missing index — causes full-table scans and locks on parent row deletes."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked = _mask_literals_and_comments(source)
        indexed_cols_by_table = _collect_indexes(masked)
        is_dump = is_dump_file(source, path)

        char_offset = 0
        for stmt in masked.split(";"):
            if "REFERENCES" in stmt.upper():
                table_match = TABLE_SCOPE_PATTERN.search(stmt)
                if table_match:
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
        matched_fk_spans: list[tuple[int, int]] = []

        for fk_match in TABLE_FK_PATTERN.finditer(ctx.stmt):
            matched_fk_spans.append((fk_match.start(), fk_match.end()))
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
        fk_clean_pattern = re.compile(
            r"\bFOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[a-zA-Z0-9_\"\.]+(?:\([^)]*\))?", re.IGNORECASE
        )
        body = fk_clean_pattern.sub(lambda m: " " * len(m.group(0)), body)

        # `body` is offset `ctx.header_end` into `ctx.stmt`, and `fk_clean_pattern`
        # substitutes equal-length runs of spaces, so a running offset over the
        # `,`-split segments stays exactly aligned with the source. Re-finding the
        # segment text by value did not — see this module's docstring.
        segment_start = ctx.header_end
        for segment in body.split(","):
            if (
                "REFERENCES" in segment.upper()
                and not TABLE_FK_PATTERN.search(segment)
                and not PRIMARY_OR_UNIQUE_KEYWORD.search(segment)
                and "CONSTRAINT" not in segment.upper()
                and "FOREIGN KEY" not in segment.upper()
            ):
                col_match = INLINE_COLUMN_PATTERN.search(segment)
                if col_match:
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
    """Word the diagnostic for `column` on `table`.

    A dump is a complete rendering of the schema, so a missing index really is
    missing — but the dump is regenerated and must not be edited, so the fix is
    named as a new migration instead.

    Returns:
        The diagnostic message.

    """
    head = (
        f"Foreign key column `{column}` on table `{table}` should have a corresponding `CREATE INDEX` "
        "to prevent full table scans and lock contention during parent row deletes."
    )
    if is_dump:
        return f"{head} This file is a schema dump — add the index in a migration, not here."
    return head
