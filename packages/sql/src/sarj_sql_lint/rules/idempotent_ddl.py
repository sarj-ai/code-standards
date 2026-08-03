"""SARJ102: DDL statements must be idempotent — migrations must be safe to re-run."""

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


# Rule checks tuple of (pattern, code_description, supported_by_mysql).
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
