from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

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
    is_generated_migration,
    is_migration_source,
    is_mysql,
    is_sqlite,
    locate,
    mask_sql,
    redirect_to_model,
    split_statements,
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
    id = "idempotent-ddl"
    code = "SARJ102"
    documentation = RuleDocumentation(
        summary="DDL without IF [NOT] EXISTS — migrations must be safe to re-run.",
        rationale="A partially applied migration may be retried, so unconditional object creation or removal can fail before recovery completes.",
        remediation="Use the supported IF NOT EXISTS or IF EXISTS form for the DDL statement.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=("Dialect-specific DDL forms are checked only where the guard syntax is supported.",),
        examples=(
            RuleExample(
                example_id="unguarded-table-creation",
                title="Table creation that fails on replay",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001_orders.sql", "CREATE TABLE orders (id BIGINT PRIMARY KEY);\n"),),
                focus_path=PurePosixPath("migrations/001_orders.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guarded-table-creation",
                title="Replay-safe table creation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql", "CREATE TABLE IF NOT EXISTS orders (id BIGINT PRIMARY KEY);\n"
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
        if is_dump_file(source, path) or not is_migration_source(path, source):
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

        for statement in split_statements(masked):
            text = "\n".join(fragment for _, fragment in statement)
            text_upper = text.upper()
            if "CREATE" not in text_upper and "DROP" not in text_upper and "ADD" not in text_upper:
                continue
            for check in checks:
                for match in check.pattern.finditer(text):
                    location = locate(statement, match.start())
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=location.line,
                            col=location.column,
                            code=self.code,
                            message=check.message,
                        )
                    )
        return redirect_to_model(diags, model_owned=model_owned)
