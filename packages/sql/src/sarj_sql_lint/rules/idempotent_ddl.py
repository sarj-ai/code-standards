"""SARJ102: DDL statements must be idempotent — migrations must be safe to re-run.

`CREATE TABLE` / `CREATE INDEX` / `ALTER TABLE ... ADD COLUMN` (and the rest of the
common DDL surface) without `IF NOT EXISTS`, or `DROP TABLE` / `DROP INDEX` without
`IF EXISTS`, fail the second time a migration runs. Re-runnable DDL means a
half-applied or replayed migration converges instead of crashing the deploy.

The detection logic is CLEAN — a 24-finding seeded sample of the 3,158 findings
over 2,133 deduped `.sql` files read TP 3 / FP 1 / arguable 20, a 4.2% outright
error rate, the lowest of the twelve SQL rules. Nothing about *what* it matches
changed. Two scope guards were added, both about where the advice can be taken.

**MySQL supports neither `CREATE INDEX IF NOT EXISTS` nor
`ADD COLUMN IF NOT EXISTS`, and its `DROP INDEX` has no `IF EXISTS`.** Demanding
them there asks for a syntax error, e.g.
`unkey/web/internal/db/drizzle/0000_dazzling_colonel_america.sql:396`. Those three
checks are gated on `is_mysql`; the other three are not, because MySQL *does*
support `CREATE TABLE IF NOT EXISTS`, `CREATE SCHEMA IF NOT EXISTS` and
`DROP TABLE IF EXISTS`. The gate deliberately uses `is_mysql` rather than
`not is_postgres`: **SQLite does support `CREATE TABLE/INDEX IF NOT EXISTS`**, so
SQLite findings are true positives and must survive. This is why the two dialect
predicates exist separately in `rule_base`.

**Generator-owned migrations.** A Prisma- or Drizzle-emitted `CREATE TABLE "Foo"`
cannot be given `IF NOT EXISTS` — the generator does not offer the option, the
file is a build artifact of `schema.prisma`, and Prisma checksums applied
migrations in `_prisma_migrations` so `migrate deploy` errors on drift rather than
replaying them. Re-run safety there is the migration runner's ledger, not the DDL.
See `is_generated_migration`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    is_mysql,
    is_sqlite,
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


# `(?>\s+)` (atomic) stops the whitespace from backtracking past the negative
# lookahead, and `CONCURRENTLY` lives inside the lookahead for the same reason.
# `CREATE TABLE` allows the `[GLOBAL|LOCAL] {TEMP|TEMPORARY} | UNLOGGED` modifiers.
#
# The third element is False for a check whose `IF [NOT] EXISTS` form MySQL does
# not implement, so demanding it there would be demanding a syntax error.
_CHECKS: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (
        re.compile(
            r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE TABLE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        True,
    ),
    (
        re.compile(r"\bADD\s+COLUMN(?>\s+)(?!IF\s+NOT\s+EXISTS\b)", re.IGNORECASE),
        "`ADD COLUMN` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        False,
    ),
    (
        re.compile(
            r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE INDEX` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        False,
    ),
    (
        re.compile(
            r"\bCREATE\s+(?:EXTENSION|SCHEMA|SEQUENCE)(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE EXTENSION`/`SCHEMA`/`SEQUENCE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        True,
    ),
    (
        re.compile(r"\bDROP\s+TABLE(?>\s+)(?!IF\s+EXISTS\b)", re.IGNORECASE),
        "`DROP TABLE`/`DROP INDEX` without `IF EXISTS` — migrations must be safe to re-run.",
        True,
    ),
    (
        re.compile(r"\bDROP\s+INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+EXISTS\b)", re.IGNORECASE),
        "`DROP TABLE`/`DROP INDEX` without `IF EXISTS` — migrations must be safe to re-run.",
        False,
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
        model_owned = is_generated_migration(path, source)

        masked = mask_sql(source)
        if is_mysql(source):
            checks = [check for check in _CHECKS if check[2]]
        elif is_sqlite(source):
            # SQLite has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` syntax.
            checks = [check for index, check in enumerate(_CHECKS) if index != 1]
        else:
            checks = list(_CHECKS)

        diags: list[Diagnostic] = []

        for lineno, line in enumerate(masked.splitlines(), start=1):
            line_upper = line.upper()
            if "CREATE" not in line_upper and "DROP" not in line_upper and "ADD" not in line_upper:
                continue
            for pattern, message, _mysql_supported in checks:
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
        return redirect_to_model(diags, model_owned=model_owned)
