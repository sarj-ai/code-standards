"""SARJ102: DDL statements must be idempotent — migrations must be safe to re-run.

`CREATE TABLE` / `CREATE INDEX` / `ALTER TABLE ... ADD COLUMN` (and the rest of the
common DDL surface) without `IF NOT EXISTS`, or `DROP TABLE` / `DROP INDEX` without
`IF EXISTS`, fail the second time a migration runs. Re-runnable DDL means a
half-applied or replayed migration converges instead of crashing the deploy.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# `(?>\s+)` (atomic) stops the whitespace from backtracking past the negative
# lookahead, and `CONCURRENTLY` lives inside the lookahead for the same reason.
# `CREATE TABLE` allows the `[GLOBAL|LOCAL] {TEMP|TEMPORARY} | UNLOGGED` modifiers.
_CHECKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE TABLE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
    ),
    (
        re.compile(r"\bADD\s+COLUMN(?>\s+)(?!IF\s+NOT\s+EXISTS\b)", re.IGNORECASE),
        "`ADD COLUMN` without `IF NOT EXISTS` — migrations must be safe to re-run.",
    ),
    (
        re.compile(
            r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE INDEX` without `IF NOT EXISTS` — migrations must be safe to re-run.",
    ),
    (
        re.compile(
            r"\bCREATE\s+(?:EXTENSION|SCHEMA|SEQUENCE)(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE EXTENSION`/`SCHEMA`/`SEQUENCE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
    ),
    (
        re.compile(
            r"\bDROP\s+(?:TABLE|INDEX)(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`DROP TABLE`/`DROP INDEX` without `IF EXISTS` — migrations must be safe to re-run.",
    ),
)


@final
class IdempotentDdl(Rule):
    """DDL without IF [NOT] EXISTS — migrations must be safe to re-run."""

    id = "idempotent-ddl"
    code = "SARJ102"
    description = "DDL without IF [NOT] EXISTS — migrations must be safe to re-run."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        diags: list[Diagnostic] = []

        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            line_upper = line.upper()
            if "CREATE" not in line_upper and "DROP" not in line_upper and "ADD" not in line_upper:
                continue
            for pattern, message in _CHECKS:
                diags.extend(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=match.start() + 1,
                        code=self.code,
                        message=message,
                    )
                    for match in pattern.finditer(line)
                )
        return diags
