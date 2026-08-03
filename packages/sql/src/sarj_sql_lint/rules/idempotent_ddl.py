"""SARJ102: DDL statements must be idempotent — migrations must be safe to re-run."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _DdlCheck:
    pattern: re.Pattern[str]
    message: str
    mysql_supported: bool
    sqlite_supported: bool = True


_CHECKS = (
    _DdlCheck(
        re.compile(
            r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE TABLE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        mysql_supported=True,
    ),
    _DdlCheck(
        re.compile(r"\bADD\s+COLUMN(?>\s+)(?!IF\s+NOT\s+EXISTS\b)", re.IGNORECASE),
        "`ADD COLUMN` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        mysql_supported=False,
        sqlite_supported=False,
    ),
    _DdlCheck(
        re.compile(
            r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE INDEX` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        mysql_supported=False,
    ),
    _DdlCheck(
        re.compile(
            r"\bCREATE\s+(?:EXTENSION|SCHEMA|SEQUENCE)(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        ),
        "`CREATE EXTENSION`/`SCHEMA`/`SEQUENCE` without `IF NOT EXISTS` — migrations must be safe to re-run.",
        mysql_supported=True,
    ),
    _DdlCheck(
        re.compile(r"\bDROP\s+TABLE(?>\s+)(?!IF\s+EXISTS\b)", re.IGNORECASE),
        "`DROP TABLE`/`DROP INDEX` without `IF EXISTS` — migrations must be safe to re-run.",
        mysql_supported=True,
    ),
    _DdlCheck(
        re.compile(r"\bDROP\s+INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+EXISTS\b)", re.IGNORECASE),
        "`DROP TABLE`/`DROP INDEX` without `IF EXISTS` — migrations must be safe to re-run.",
        mysql_supported=False,
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
            checks = [check for check in _CHECKS if check.mysql_supported]
        elif is_sqlite(source):
            checks = [check for check in _CHECKS if check.sqlite_supported]
        else:
            checks = list(_CHECKS)

        diags: list[Diagnostic] = []

        for lineno, line in enumerate(masked.splitlines(), start=1):
            line_upper = line.upper()
            if "CREATE" not in line_upper and "DROP" not in line_upper and "ADD" not in line_upper:
                continue
            for check in checks:
                diags.extend(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=match.start() + 1,
                        code=self.code,
                        message=check.message,
                    )
                    for match in check.pattern.finditer(line)
                )
        return redirect_to_model(diags, model_owned=model_owned)
