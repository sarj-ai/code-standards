"""SARJ112: Require index on Foreign Key column.

Postgres does NOT automatically index foreign key columns. Deleting or updating rows from a parent table
triggers a full sequential scan on the child table if the FK is unindexed, locking the child table.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path


def _mask_literals_and_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), sql)
    sql = re.sub(r"/\*[\s\S]*?\*/", lambda m: " " * len(m.group(0)), sql)
    sql = re.sub(r"'(?:''|[^'])*'", lambda m: " " * len(m.group(0)), sql)
    return sql


CREATE_INDEX_PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b[\s\S]*?\bON\s+([a-zA-Z0-9_\"\.]+)\s*(?:USING\s+[a-zA-Z0-9_]+\s*)?\(\s*([a-zA-Z0-9_,\s\"]+)\)",
    re.IGNORECASE,
)
TABLE_SCOPE_PATTERN = re.compile(
    r"\b(?:CREATE|ALTER)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_\"\.]+)",
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
    r"(?:\bADD\s+(?:COLUMN\s+)?)?\b([a-zA-Z0-9_\"]+)\b\s+[a-zA-Z0-9_\"\.]+(?:\([^)]*\))?[^\n;,]*?\bREFERENCES\s+[a-zA-Z0-9_\"\.]+\b",
    re.IGNORECASE,
)
PRIMARY_OR_UNIQUE_KEYWORD = re.compile(r"\b(PRIMARY\s+KEY|UNIQUE)\b", re.IGNORECASE)


def _normalize_name(name: str) -> str:
    return name.strip('"').lower()


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

        indexed_cols_by_table: dict[str, set[tuple[str, ...]]] = {}

        for match in CREATE_INDEX_PATTERN.finditer(masked):
            table = _normalize_name(match.group(1))
            cols_raw = match.group(2)
            cols = tuple(_normalize_name(c) for c in cols_raw.split(","))
            if cols:
                indexed_cols_by_table.setdefault(table, set()).add(cols)
                if "." in table:
                    base_table = table.split(".")[-1]
                    indexed_cols_by_table.setdefault(base_table, set()).add(cols)

        statements = masked.split(";")
        char_offset = 0

        for stmt in statements:
            if "REFERENCES" in stmt.upper():
                table_match = TABLE_SCOPE_PATTERN.search(stmt)
                if table_match:
                    full_table = _normalize_name(table_match.group(1))
                    base_table = full_table.split(".")[-1]
                    table_indexes = indexed_cols_by_table.get(full_table, set())
                    if not table_indexes and "." in full_table:
                        table_indexes = indexed_cols_by_table.get(base_table, set())
                    leading_indexed_cols = {idx[0] for idx in table_indexes if idx}

                    for pk_u_match in TABLE_PK_OR_UNIQUE_PATTERN.finditer(stmt):
                        raw_pk_cols = pk_u_match.group(1)
                        pk_cols = [_normalize_name(c) for c in raw_pk_cols.split(",")]
                        if pk_cols:
                            leading_indexed_cols.add(pk_cols[0])

                    for fk_match in TABLE_FK_PATTERN.finditer(stmt):
                        raw_cols = fk_match.group(1)
                        fk_cols = tuple(_normalize_name(c) for c in raw_cols.split(","))
                        leading_fk_col = fk_cols[0] if fk_cols else ""
                        if leading_fk_col and leading_fk_col not in leading_indexed_cols:
                            match_offset = char_offset + stmt.find(fk_match.group(0))
                            lineno = masked[:match_offset].count("\n") + 1
                            col_pos = match_offset - masked.rfind("\n", 0, match_offset)
                            diags.append(
                                Diagnostic(
                                    path=path,
                                    line=lineno,
                                    col=max(1, col_pos),
                                    code=self.code,
                                    message=(
                                        f"Foreign key column `{leading_fk_col}` on table `{full_table}` should have a corresponding `CREATE INDEX` "
                                        "to prevent full table scans and lock contention during parent row deletes."
                                    ),
                                )
                            )

                    header_end = table_match.end()
                    body = stmt[header_end:]

                    for line in body.splitlines():
                        if "REFERENCES" in line.upper() and not TABLE_FK_PATTERN.search(line):
                            if PRIMARY_OR_UNIQUE_KEYWORD.search(line):
                                continue
                            col_match = INLINE_COLUMN_PATTERN.search(line)
                            if col_match:
                                col_name = _normalize_name(col_match.group(1))
                                if col_name not in ("foreign", "key", "constraint", "alter", "table", "create", "add", "column") and col_name not in leading_indexed_cols:
                                    line_offset = char_offset + stmt.find(line)
                                    lineno = masked[:line_offset].count("\n") + 1
                                    diags.append(
                                        Diagnostic(
                                            path=path,
                                            line=lineno,
                                            col=1,
                                            code=self.code,
                                            message=(
                                                f"Foreign key column `{col_name}` on table `{full_table}` should have a corresponding `CREATE INDEX` "
                                                "to prevent full table scans and lock contention during parent row deletes."
                                            ),
                                        )
                                    )

            char_offset += len(stmt) + 1

        return diags
