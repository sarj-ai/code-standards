from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_CONTINUATION,
    POSTGRES_IDENTIFIER_PART,
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
    mask_sql_literals_and_comments,
    quoted_identifier_spans,
    redirect_to_model,
    split_statements,
    sql_code_matches,
)
from sarj_sql_lint.rules._copy_input import sql_before_copy_input


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_sql_lint.rule_base import SourceLocation


_DDL_START = rf"(?<!{POSTGRES_IDENTIFIER_CONTINUATION})"


@dataclass(frozen=True, slots=True)
class DdlCheck:
    pattern: re.Pattern[str]
    message: str
    mysql_supported: bool
    sqlite_supported: bool = True
    autofix_supported: bool = True


_CHECKS = (
    DdlCheck(
        re.compile(
            rf"{_DDL_START}CREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.ASCII | re.IGNORECASE,
        ),
        "`CREATE TABLE` without `IF NOT EXISTS` — use the supported existence guard.",
        mysql_supported=True,
    ),
    DdlCheck(
        re.compile(rf"{_DDL_START}ADD\s+COLUMN(?>\s+)(?!IF\s+NOT\s+EXISTS\b)", re.ASCII | re.IGNORECASE),
        "`ADD COLUMN` without `IF NOT EXISTS` — use the supported existence guard.",
        mysql_supported=False,
        sqlite_supported=False,
    ),
    DdlCheck(
        re.compile(
            rf"{_DDL_START}CREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS\b)",
            re.ASCII | re.IGNORECASE,
        ),
        "`CREATE INDEX` without `IF NOT EXISTS` — use the supported existence guard.",
        mysql_supported=False,
    ),
    DdlCheck(
        re.compile(
            rf"{_DDL_START}CREATE\s+SCHEMA(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.ASCII | re.IGNORECASE,
        ),
        "`CREATE SCHEMA` without `IF NOT EXISTS` — use the supported existence guard.",
        mysql_supported=True,
        sqlite_supported=False,
    ),
    DdlCheck(
        re.compile(
            rf"{_DDL_START}CREATE\s+(?:EXTENSION|(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?SEQUENCE|"
            r"MATERIALIZED\s+VIEW|FOREIGN\s+TABLE|COLLATION|SERVER|USER\s+MAPPING)"
            r"(?>\s+)(?!IF\s+NOT\s+EXISTS\b)",
            re.ASCII | re.IGNORECASE,
        ),
        "`CREATE` statement without `IF NOT EXISTS` — use the supported existence guard.",
        mysql_supported=False,
        sqlite_supported=False,
    ),
    DdlCheck(
        re.compile(rf"{_DDL_START}CREATE\s+STATISTICS(?>\s+)(?!IF\s+NOT\s+EXISTS\b)", re.ASCII | re.IGNORECASE),
        "`CREATE STATISTICS` without `IF NOT EXISTS` — use the supported existence guard; name unnamed statistics explicitly.",
        mysql_supported=False,
        sqlite_supported=False,
        autofix_supported=False,
    ),
    DdlCheck(
        re.compile(rf"{_DDL_START}DROP\s+TABLE(?>\s+)(?!IF\s+EXISTS\b)", re.ASCII | re.IGNORECASE),
        "`DROP TABLE` without `IF EXISTS` — use the supported existence guard.",
        mysql_supported=True,
    ),
    DdlCheck(
        re.compile(rf"{_DDL_START}DROP\s+INDEX(?>\s+)(?!(?:CONCURRENTLY\s+)?IF\s+EXISTS\b)", re.ASCII | re.IGNORECASE),
        "`DROP INDEX` without `IF EXISTS` — use the supported existence guard.",
        mysql_supported=False,
    ),
    DdlCheck(
        re.compile(rf"{_DDL_START}DROP\s+VIEW(?>\s+)(?!IF\s+EXISTS\b)", re.ASCII | re.IGNORECASE),
        "`DROP VIEW` without `IF EXISTS` — use the supported existence guard.",
        mysql_supported=True,
    ),
    DdlCheck(
        re.compile(
            rf"{_DDL_START}DROP\s+(?>ACCESS\s+METHOD|AGGREGATE|CAST|COLLATION|CONVERSION|DATABASE|DOMAIN|"
            r"EVENT\s+TRIGGER|EXTENSION|FOREIGN\s+(?:DATA\s+WRAPPER|TABLE)|FUNCTION|GROUP|"
            r"(?:PROCEDURAL\s+)?LANGUAGE|MATERIALIZED\s+VIEW|OPERATOR(?:\s+(?:CLASS|FAMILY))?|"
            r"POLICY|PROCEDURE|PUBLICATION|ROLE|ROUTINE|RULE|SCHEMA|SEQUENCE|SERVER|STATISTICS|"
            r"SUBSCRIPTION|TABLESPACE|TEXT\s+SEARCH\s+(?:CONFIGURATION|DICTIONARY|PARSER|TEMPLATE)|"
            r"TRANSFORM|TRIGGER|TYPE|USER(?:\s+MAPPING)?)"
            r"(?>\s+)(?!IF\s+EXISTS\b)",
            re.ASCII | re.IGNORECASE,
        ),
        "`DROP` statement without `IF EXISTS` — use the supported existence guard.",
        mysql_supported=False,
        sqlite_supported=False,
    ),
    DdlCheck(
        re.compile(
            rf"{_DDL_START}DROP\s+(?:COLUMN|CONSTRAINT|ATTRIBUTE)(?>\s+)(?!IF\s+EXISTS\b)", re.ASCII | re.IGNORECASE
        ),
        "`DROP COLUMN`/`CONSTRAINT`/`ATTRIBUTE` without `IF EXISTS` — use the supported existence guard.",
        mysql_supported=False,
        sqlite_supported=False,
    ),
)

_IDENTIFIER = rf"{POSTGRES_IDENTIFIER_PART}(?:\s*\.\s*{POSTGRES_IDENTIFIER_PART})*"
_ALTER_TABLE = re.compile(
    rf"{_DDL_START}ALTER\s+(?:FOREIGN\s+)?TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{_IDENTIFIER}(?:\s*\*)?\s+",
    re.ASCII | re.IGNORECASE,
)
_IMPLICIT_COLUMN = re.compile(
    r"(?P<operation>ADD|DROP)\s+"
    r"(?!COLUMN\b|CONSTRAINT\b|IF\b|CHECK\b|UNIQUE\b|PRIMARY\b|FOREIGN\b|EXCLUDE\b)"
    rf"{POSTGRES_IDENTIFIER_PART}(?![\w$])",
    re.ASCII | re.IGNORECASE,
)
_DROP_GENERATED = re.compile(
    rf"ALTER\s+(?:COLUMN\s+)?{POSTGRES_IDENTIFIER_PART}\s+"
    r"DROP\s+(?:IDENTITY|EXPRESSION)\b(?!\s+IF\s+EXISTS\b)",
    re.ASCII | re.IGNORECASE,
)


@final
class IdempotentDdl(Rule):
    id = "idempotent-ddl"
    code = "SARJ102"
    documentation = RuleDocumentation(
        summary="DDL omits a supported IF [NOT] EXISTS guard.",
        rationale="Supported existence guards help replay DDL after partial application. A transactional migration runner such as dbmate owns version tracking and rollback; this rule does not require every statement to be independently replayable.",
        remediation="Use the native IF NOT EXISTS or IF EXISTS form where this rule supports it. Keep ADD CONSTRAINT as plain DDL in versioned transactional migrations; do not synthesize catalog-query DO blocks or catch duplicate-object errors solely for replay.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Checks native guards on table/index/schema/extension/sequence creation, materialized views, foreign tables, statistics, collations, servers and user mappings; PostgreSQL DROP object families; and ADD/DROP COLUMN, DROP CONSTRAINT/ATTRIBUTE and DROP IDENTITY/EXPRESSION.",
            "CREATE TYPE, CREATE DOMAIN, ADD CONSTRAINT and rename operations have no native replay guard and are excluded. CREATE OR REPLACE is not required because replacing an existing definition changes behavior. An outer ALTER TABLE IF EXISTS does not guard missing columns and is not required.",
            "Dialect-specific DDL forms are checked only where the guard syntax is supported. Existence guards do not verify that an existing object's definition matches the intended schema.",
            "Analysis stops at COPY FROM STDIN because raw data framing and commands after its terminator are not modeled.",
            "Safe fixes add only supported PostgreSQL existence guards to parseable authored DDL. They intentionally make an existing or absent object a no-op on replay; dumps, generator-owned files, unsupported syntax and other dialects remain unchanged.",
        ),
        examples=(
            RuleExample(
                example_id="unguarded-table-creation",
                title="Table creation that fails on replay",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001_orders.sql", "CREATE TABLE orders (id BIGINT PRIMARY KEY);\n"),),
                fixed_files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql", "CREATE TABLE IF NOT EXISTS orders (id BIGINT PRIMARY KEY);\n"
                    ),
                ),
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
            RuleExample(
                example_id="unguarded-index-creation",
                title="An index creation that fails when replayed",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql", "CREATE INDEX CONCURRENTLY orders_total ON orders (total);\n"
                    ),
                ),
                fixed_files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_total ON orders (total);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_orders.sql"),
                expected_count=1,
                public=True,
                scenario="index-existence",
            ),
            RuleExample(
                example_id="guarded-index-creation",
                title="A replay-safe concurrent index creation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_orders.sql",
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_total ON orders (total);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_orders.sql"),
                expected_count=0,
                public=True,
                scenario="index-existence",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        source = sql_before_copy_input(source)
        if is_dump_file(source, path) or not is_migration_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)

        findings = _native_guard_findings(source)
        if not (is_mysql(source) or is_sqlite(source)):
            for statement in split_statements(mask_sql_literals_and_comments(source, mask_dollar_literals=True)):
                text = "\n".join(fragment for _, fragment in statement)
                findings.extend(
                    (locate(statement, offset), message) for offset, message in _table_action_findings(text)
                )
        diags = [
            Diagnostic(path=path, line=location.line, col=location.column, code=self.code, message=message)
            for location, message in findings
        ]
        return redirect_to_model(diags, model_owned=model_owned)


def _native_guard_findings(source: str) -> list[tuple[SourceLocation, str]]:
    checks = ddl_checks(source)
    findings: list[tuple[SourceLocation, str]] = []
    for statement in split_statements(mask_sql(source, mask_dollar_literals=True)):
        text = "\n".join(fragment for _, fragment in statement)
        text_upper = text.upper()
        if "CREATE" not in text_upper and "DROP" not in text_upper and "ADD" not in text_upper:
            continue
        for check in checks:
            findings.extend((locate(statement, match.start()), check.message) for match in check.pattern.finditer(text))
    return findings


def ddl_checks(source: str) -> list[DdlCheck]:
    if is_mysql(source):
        return [check for check in _CHECKS if check.mysql_supported]
    if is_sqlite(source):
        return [check for check in _CHECKS if check.sqlite_supported]
    return list(_CHECKS)


def _table_action_findings(text: str) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for table in sql_code_matches(_ALTER_TABLE, text):
        for start, end in _action_ranges(text, table.end()):
            action = text[start:end]
            if match := _IMPLICIT_COLUMN.match(action):
                operation = match.group("operation").upper()
                guard = "IF NOT EXISTS" if operation == "ADD" else "IF EXISTS"
                findings.append((start, f"`{operation} COLUMN` without `{guard}` — use the supported existence guard."))
            elif _DROP_GENERATED.match(action):
                findings.append(
                    (
                        start,
                        "`DROP IDENTITY`/`DROP EXPRESSION` without `IF EXISTS` — use the supported existence guard.",
                    )
                )
    return findings


def _action_ranges(text: str, start: int) -> list[tuple[int, int]]:
    identifiers = dict(quoted_identifier_spans(text))
    ranges: list[tuple[int, int]] = []
    depth = 0
    cursor = start
    while cursor < len(text):
        if end := identifiers.get(cursor):
            cursor = end
            continue
        char = text[cursor]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            ranges.append((start, cursor))
            start = cursor + 1
        cursor += 1
    ranges.append((start, len(text)))
    return [(left + len(text[left:right]) - len(text[left:right].lstrip()), right) for left, right in ranges]
