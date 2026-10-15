from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_PART,
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dbmate_transactional,
    is_dump_file,
    is_postgres,
    mask_sql,
    mask_sql_comments,
    source_location,
    sql_relation_key,
)


if TYPE_CHECKING:
    from pathlib import Path


# `CONCURRENTLY` must come right after `INDEX` (before any `IF NOT EXISTS`).
PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!CONCURRENTLY\b)",
    re.IGNORECASE,
)

# Match table-name patterns against raw source to preserve quoted identifiers, gating on live code in masked text.

# Search for target table forward from CREATE INDEX up to statement semicolon boundary.
_QUALIFIED_IDENTIFIER = (
    rf"{POSTGRES_IDENTIFIER_PART}(?:\s*\.\s*{POSTGRES_IDENTIFIER_PART})*(?![A-Za-z0-9_$\u0080-\U0010ffff]|\s*\.)"
)
_ON_TABLE_RE = re.compile(
    rf"(?<![A-Za-z0-9_$\u0080-\U0010ffff])ON\s+(?:ONLY\s+)?({_QUALIFIED_IDENTIFIER})", re.IGNORECASE
)

_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?({_QUALIFIED_IDENTIFIER})",
    re.IGNORECASE,
)


@final
class IndexConcurrently(Rule):
    id = "index-concurrently"
    code = "SARJ108"
    documentation = RuleDocumentation(
        summary="CREATE INDEX without CONCURRENTLY — locks the table against writes.",
        rationale="Building an index normally blocks writes to an existing PostgreSQL table for the duration of the build.",
        remediation="Use CREATE INDEX CONCURRENTLY in a nontransactional migration.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The same-file CREATE TABLE exemption preserves explicit schema differences and quoted identifier case.",
            "Explicit pg_temp and pg_temp_N targets are exempt because temporary tables cannot block writes from other sessions.",
            "Valid catalog qualifiers use schema/relation identity; the current database is not resolved.",
            "Mixed qualified/unqualified references with the same relation name remain potentially fresh; search_path is not resolved. UTF-8 names use ASCII-only unquoted case folding; escaped Unicode identifiers and server-side name truncation are not resolved.",
            "Conditional creation and transaction boundaries are not re-evaluated by the same-file exemption.",
        ),
        examples=(
            RuleExample(
                example_id="blocking-index-build",
                title="Blocking index build on an existing table",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_email_index.sql", "CREATE INDEX users_email_idx ON users(email);\n"
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_email_index.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concurrent-index-build",
                title="Concurrent index build",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_email_index.sql", "CREATE INDEX CONCURRENTLY users_email_idx ON users(email);\n"
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_email_index.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="scalar-dollar-data",
                title="SQL keywords inside scalar dollar data are not executed",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_data.sql",
                        "SELECT $data$CREATE INDEX orders_idx ON orders(id);$data$;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_data.sql"),
                expected_count=0,
                public=True,
                scenario="dollar-quoted-sql",
            ),
            RuleExample(
                example_id="executable-dollar-body",
                title="Executable dollar-quoted migration SQL remains checked",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_body.sql",
                        "DO $$ BEGIN CREATE INDEX orders_idx ON orders(id); END $$;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_body.sql"),
                expected_count=1,
                public=True,
                scenario="dollar-quoted-sql",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        masked = mask_sql(source, mask_dollar_literals=True)
        uncommented = mask_sql_comments(source)
        if not is_postgres(source):
            return []

        created: dict[tuple[str, ...], int] = {}
        created_by_basename: dict[str, int] = {}
        for match in _CREATE_TABLE_RE.finditer(uncommented):
            if _is_live(masked, match.start()):
                name = sql_relation_key(match.group(1))
                created.setdefault(name, match.start())
                created_by_basename.setdefault(name[-1], match.start())

        diags: list[Diagnostic] = []
        for match in PATTERN.finditer(masked):
            pos = match.start()
            target = _target_table(uncommented, masked, match.end())
            if target is not None:
                if target[:-1] == ("pg_temp",):
                    continue
                created_at = (
                    created_by_basename.get(target[-1], pos)
                    if len(target) == 1
                    else min(created.get(target, pos), created.get(target[-1:], pos))
                )
                # A newly created table has no concurrent writers; CONCURRENTLY would make this migration nontransactional.
                if created_at < pos:
                    continue
            location = source_location(source, pos)
            diags.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message=(
                        "Set `transaction:false` on this section’s `-- migrate:up` or `-- migrate:down` directive, replace `SET LOCAL` "
                        "timeouts with session `SET`/`RESET`, and use `CREATE INDEX CONCURRENTLY` — "
                        "dbmate otherwise runs it in a transaction where CONCURRENTLY is illegal."
                        if dbmate_transactional(source, pos) is True
                        else "Use `CREATE INDEX CONCURRENTLY` — a plain CREATE INDEX locks the table against writes for the whole build."
                    ),
                )
            )
        return diags


def _is_live(masked: str, pos: int) -> bool:
    return pos < len(masked) and not masked[pos].isspace()


def _target_table(source: str, masked: str, start: int) -> tuple[str, ...] | None:
    end = masked.find(";", start)
    stmt_end = len(masked) if end == -1 else end
    return next(
        (
            sql_relation_key(match.group(1))
            for match in _ON_TABLE_RE.finditer(source, start, stmt_end)
            if _is_live(masked, match.start())
        ),
        None,
    )
