from __future__ import annotations

from bisect import bisect_right
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_PART,
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dbmate_directives,
    dollar_quoted_spans,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    is_postgres,
    mask_sql,
    mask_sql_comments,
    source_location,
)


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_NON_PRODUCTION = frozenset({"test", "tests", "testing", "__tests__", "clickhouse", "d1", "mariadb", "mysql", "sqlite"})
_RELATION = rf"{POSTGRES_IDENTIFIER_PART}(?:\s*\.\s*{POSTGRES_IDENTIFIER_PART}){{0,2}}"
_DROP = re.compile(
    rf"\s*DROP\s+INDEX\s+CONCURRENTLY\s+(?:IF\s+EXISTS\s+)?"
    rf"(?P<targets>{_RELATION}(?:\s*,\s*{_RELATION})*)"
    r"(?:\s+(?P<option>CASCADE|RESTRICT))?\s*",
    re.IGNORECASE,
)
_REFRESH = re.compile(
    rf"\s*REFRESH\s+MATERIALIZED\s+VIEW\s+CONCURRENTLY\s+{_RELATION}\s+WITH\s+NO\s+DATA\s*",
    re.IGNORECASE,
)
_CREATE_HEAD = re.compile(r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b", re.IGNORECASE)
_TX_MODE = (
    r"(?:ISOLATION\s+LEVEL\s+(?:SERIALIZABLE|REPEATABLE\s+READ|READ\s+COMMITTED|READ\s+UNCOMMITTED)"
    r"|READ\s+(?:WRITE|ONLY)|(?:NOT\s+)?DEFERRABLE)"
)
_BEGIN = re.compile(
    rf"\s*(?:BEGIN(?:\s+(?:WORK|TRANSACTION))?|START\s+TRANSACTION)"
    rf"(?:\s+{_TX_MODE}(?:(?:\s*,\s*|\s+){_TX_MODE})*)?\s*",
    re.IGNORECASE,
)
_END = re.compile(
    r"\s*(?:COMMIT|END|ROLLBACK|ABORT)(?:\s+(?:WORK|TRANSACTION))?"
    r"(?:\s+AND\s+(?P<no>NO\s+)?(?P<chain>CHAIN))?\s*",
    re.IGNORECASE,
)
_BEGIN_ATOMIC = re.compile(r"\bBEGIN\s+ATOMIC\b", re.IGNORECASE)
_PREPARE = re.compile(r"\s*PREPARE\s+TRANSACTION\b", re.IGNORECASE)
_NON_NEWLINE = re.compile(r"[^\r\n]")


class _Statement(NamedTuple):
    start: int
    text: str


@final
class InvalidConcurrentDdl(Rule):
    id = "invalid-concurrent-ddl"
    code = "SARJ125"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Keep concurrent PostgreSQL DDL in supported execution contexts.",
        rationale=(
            "PostgreSQL rejects concurrent index creation and removal inside a transaction block. "
            "Concurrent index removal also rejects multiple targets and CASCADE, and a concurrent "
            "materialized-view refresh cannot request WITH NO DATA."
        ),
        remediation=(
            "Run concurrent index commands outside a transaction, using transaction:false for the relevant "
            "dbmate section. Drop one index per concurrent command without CASCADE. Choose either a "
            "concurrent populated refresh or a nonconcurrent WITH NO DATA refresh. Preserve deployment "
            "and atomicity requirements when changing transaction boundaries."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored PostgreSQL migrations are checked; tests, fixtures, dumps and recognized generator-owned migrations are excluded.",
            "Transaction proof comes from explicit BEGIN/START TRANSACTION or a valid dbmate up/down directive. COMMIT/END/ROLLBACK/ABORT, AND [NO] CHAIN and section boundaries are tracked; ROLLBACK TO a savepoint keeps the transaction active. Unknown caller transactions and other migration runners are not inferred.",
            "Only parseable CREATE INDEX CONCURRENTLY statements and complete DROP INDEX or REFRESH MATERIALIZED VIEW command forms are inspected. Dollar-quoted procedural and scalar bodies are ignored; SQL-standard BEGIN ATOMIC routine bodies cause file-level abstention. Dynamic SQL, REINDEX and external catalog restrictions are not inferred.",
            "One finding per command combines all demonstrated restrictions. No automatic transaction or DDL rewrite is safe.",
        ),
        examples=(
            RuleExample(
                example_id="transactional-concurrent-index",
                title="A concurrent index build cannot execute in the runner's transaction",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_index.sql",
                        "-- migrate:up\nCREATE INDEX CONCURRENTLY account_email ON account(email);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_index.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nontransactional-concurrent-index",
                title="The runner explicitly executes the concurrent index outside a transaction",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_index.sql",
                        "-- migrate:up transaction:false\nCREATE INDEX CONCURRENTLY account_email ON account(email);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_index.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="unsupported-concurrent-drop-options",
                title="A concurrent index drop supports one target without CASCADE",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_remove.sql", "DROP INDEX CONCURRENTLY IF EXISTS account_a, account_b CASCADE;\n"
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_remove.sql"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="incompatible-refresh-options",
                title="A concurrent refresh cannot leave the view unpopulated",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/003_refresh.sql", "REFRESH MATERIALIZED VIEW CONCURRENTLY summary WITH NO DATA;\n"
                    ),
                ),
                focus_path=PurePosixPath("migrations/003_refresh.sql"),
                expected_count=1,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "CONCURRENTLY" not in source.upper():
            return []
        if (
            {part.casefold() for part in path.parts} & _NON_PRODUCTION
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
            or not is_migration_source(path, source)
            or not is_postgres(source)
        ):
            return []
        if "ATOMIC" in source.upper() and _BEGIN_ATOMIC.search(mask_sql(source, mask_dollar_literals=True)):
            return []
        directives = dbmate_directives(source)
        boundaries = tuple(directive.match.start() for directive in directives)
        section = -1
        transactional = False
        findings: list[Diagnostic] = []
        for statement in _statements(source):
            current_section = bisect_right(boundaries, statement.start) - 1
            if current_section != section:
                section = current_section
                transactional = directives[section].transactional if section >= 0 else False
            text = statement.text
            if _BEGIN.fullmatch(text) is not None:
                transactional = True
            elif (ended := _END.fullmatch(text)) is not None:
                transactional = transactional and ended.group("chain") is not None and ended.group("no") is None
            elif _PREPARE.match(text) is not None:
                # PREPARE TRANSACTION ends the current transaction. Its transaction
                # identifier and externally prepared transactions need no inference.
                transactional = False
            elif reasons := _invalid_reasons(text, transactional=transactional):
                location = source_location(source, statement.start)
                findings.append(
                    Diagnostic(
                        path,
                        location.line,
                        location.column,
                        self.code,
                        " ".join(reasons),
                        severity=DefaultLevel.WARNING,
                    )
                )
        return findings


def _statements(source: str) -> Iterator[_Statement]:
    uncommented_chars = list(mask_sql_comments(source))
    for start, end in dollar_quoted_spans(source):
        uncommented_chars[start:end] = _NON_NEWLINE.sub(" ", source[start:end])
    uncommented = "".join(uncommented_chars)
    masked = mask_sql(uncommented, mask_dollar_literals=True)
    start = 0
    for end in (*[match.start() for match in re.finditer(r";", masked)], len(masked)):
        text = uncommented[start:end]
        if text.strip():
            leading = len(text) - len(text.lstrip())
            yield _Statement(start + leading, text[leading:])
        start = end + 1


def _invalid_reasons(text: str, *, transactional: bool) -> list[str]:
    if (dropped := _DROP.fullmatch(text)) is not None:
        reasons: list[str] = []
        if transactional:
            reasons.append("`DROP INDEX CONCURRENTLY` cannot execute inside a transaction block.")
        if "," in mask_sql(dropped.group("targets")):
            reasons.append("`DROP INDEX CONCURRENTLY` accepts only one index per statement.")
        if (dropped.group("option") or "").upper() == "CASCADE":
            reasons.append("`DROP INDEX CONCURRENTLY` does not support `CASCADE`.")
        return reasons
    if _REFRESH.fullmatch(text) is not None:
        return ["`REFRESH MATERIALIZED VIEW CONCURRENTLY` cannot be combined with `WITH NO DATA`."]
    if transactional and _CREATE_HEAD.match(text) is not None and _is_concurrent_create(text):
        return ["`CREATE INDEX CONCURRENTLY` cannot execute inside a transaction block."]
    return []


def _is_concurrent_create(text: str) -> bool:
    try:
        parsed = parse_postgres(text)
    except SqlglotError, RecursionError:
        return False
    return (
        len(parsed) == 1
        and isinstance(parsed[0], exp.Create)
        and parsed[0].args.get("kind") == "INDEX"
        and parsed[0].args.get("concurrently") is True
        and parsed[0].find(exp.Command) is None
    )
