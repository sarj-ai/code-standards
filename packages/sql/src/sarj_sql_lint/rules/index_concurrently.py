from __future__ import annotations

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
    dbmate_transactional,
    is_dump_file,
    is_postgres,
    mask_sql,
    source_location,
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
_ON_TABLE_RE = re.compile(r"\bON\s+(?:ONLY\s+)?([A-Za-z0-9_.\"]+)", re.IGNORECASE)

_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)",
    re.IGNORECASE,
)


def _base_name(raw: str) -> str:
    return raw.replace('"', "").rsplit(".", 1)[-1].lower()


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
            "Indexes on tables created earlier in the same file are exempt because no concurrent writers exist yet.",
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
        if not is_postgres(source):
            return []

        created: dict[str, int] = {}
        for match in _CREATE_TABLE_RE.finditer(source):
            if _is_live(masked, match.start()):
                created.setdefault(_base_name(match.group(1)), match.start())

        diags: list[Diagnostic] = []
        for match in PATTERN.finditer(masked):
            pos = match.start()
            target = _target_table(source, masked, match.end())
            if target is not None:
                created_at = created.get(target)
                # A newly created table has no concurrent writers; CONCURRENTLY would make this migration nontransactional.
                if created_at is not None and created_at < pos:
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


def _target_table(source: str, masked: str, start: int) -> str | None:
    end = masked.find(";", start)
    stmt_end = len(masked) if end == -1 else end
    match = _ON_TABLE_RE.search(source, start, stmt_end)
    if match is None or not _is_live(masked, match.start()):
        return None
    return _base_name(match.group(1))
