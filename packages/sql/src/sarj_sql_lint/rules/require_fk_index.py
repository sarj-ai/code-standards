"""SARJ112: Require index on Foreign Key column.

Postgres does NOT automatically index foreign key columns. Deleting or updating rows from a parent table
triggers a full sequential scan on the child table if the FK is unindexed, locking the child table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule


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


@dataclass(frozen=True)
class _StmtContext:
    path: Path
    masked: str
    stmt: str
    char_offset: int
    full_table: str
    header_end: int


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

                    ctx = _StmtContext(path, masked, stmt, char_offset, full_table, table_match.end())
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
                match_offset = ctx.char_offset + ctx.stmt.find(fk_match.group(0))
                lineno = ctx.masked[:match_offset].count("\n") + 1
                col_pos = match_offset - ctx.masked.rfind("\n", 0, match_offset)
                diags.append(
                    Diagnostic(
                        path=ctx.path,
                        line=lineno,
                        col=max(1, col_pos),
                        code=self.code,
                        message=(
                            f"Foreign key column `{leading_col}` on table `{ctx.full_table}` should have a corresponding `CREATE INDEX` "
                            "to prevent full table scans and lock contention during parent row deletes."
                        ),
                    )
                )

        # Mask table-level FK definitions before inspecting inline column references
        body = ctx.stmt[ctx.header_end :]
        fk_clean_pattern = re.compile(
            r"\bFOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[a-zA-Z0-9_\"\.]+(?:\([^)]*\))?", re.IGNORECASE
        )
        body = fk_clean_pattern.sub(lambda m: " " * len(m.group(0)), body)

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
                        segment_offset = ctx.char_offset + ctx.stmt.find(segment)
                        lineno = ctx.masked[:segment_offset].count("\n") + 1
                        diags.append(
                            Diagnostic(
                                path=ctx.path,
                                line=lineno,
                                col=1,
                                code=self.code,
                                message=(
                                    f"Foreign key column `{col_name}` on table `{ctx.full_table}` should have a corresponding `CREATE INDEX` "
                                    "to prevent full table scans and lock contention during parent row deletes."
                                ),
                            )
                        )
        return diags
