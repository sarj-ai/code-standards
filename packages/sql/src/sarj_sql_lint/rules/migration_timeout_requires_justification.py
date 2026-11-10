from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    NON_POSTGRES_SQL_PARTS,
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_explicit_dump_file,
    is_generated_migration,
    is_migration_source,
    is_postgres,
    source_location,
)
from sarj_sql_lint.rules._migration_timeouts import migration_timeout_controls


if TYPE_CHECKING:
    from pathlib import Path


@final
class MigrationTimeoutRequiresJustification(Rule):
    id = "migration-timeout-requires-justification"
    code = "SARJ131"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Require an explicit operational reason for migration timeout settings.",
        rationale=(
            "Routine SET/RESET timeout headers duplicate session policy and change migration failure behavior "
            "without recording why a migration needs a different deadline or lock wait."
        ),
        remediation=(
            "Review and remove unnecessary timeout bookkeeping, or put a standalone "
            "`-- timeout-justification: <setting> -- <operational reason>` immediately before each justified "
            "statement. The setting must match; reviewers assess the reason. Do not remove a timeout merely "
            "because its reason is missing."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct top-level SET, SET LOCAL, SET SESSION and RESET of statement_timeout, lock_timeout, idle_in_transaction_session_timeout, idle_session_timeout, transaction_timeout and deadlock_timeout in authored PostgreSQL migrations, including forward and rollback sections.",
            "Every named timeout control needs its own immediately preceding standalone directive with a matching setting and nonempty alphanumeric reason. Blank lines, mismatched settings, ordinary prose, block comments and generic sarj-noqa do not waive it. The adequacy of a reason requires review.",
            "Explicit dump headers/names, generator-owned migrations, queries/scripts and test fixtures are excluded. Two SET-to-zero headers alone do not establish a dump for this rule.",
            "Dollar/string-quoted bodies and dynamic set_config calls, ALTER ROLE/DATABASE policy, RESET ALL, escaped Unicode setting identifiers and SQL-standard BEGIN ATOMIC bodies are not inferred. Files with BEGIN ATOMIC abstain. Analysis stops before COPY FROM STDIN.",
            "This is an explicit source-policy contract, not proof that a timeout is unsafe. Existing migrations use normal reviewed baselines at adoption; no historical migration is rewritten. No automatic SQL fix is offered because deadlines, exceptions, cancellation and session state require operational review.",
        ),
        examples=(
            RuleExample(
                example_id="unjustified-set",
                scenario="set-timeout",
                title="A timeout header has no operational reason",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "SET statement_timeout = '10min';\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="justified-set",
                scenario="set-timeout",
                title="The reviewed backfill records why it needs a different deadline",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- timeout-justification: statement_timeout -- bounded backfill exceeds the session default\nSET statement_timeout = '10min';\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="unjustified-reset",
                scenario="reset-timeout",
                title="A reset also changes the session's timeout behavior",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "RESET lock_timeout;\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="justified-reset",
                scenario="reset-timeout",
                title="Cleanup records the setting it restores",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- timeout-justification: lock_timeout -- restore the session default after the reviewed lock override\nRESET lock_timeout;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            not is_migration_source(path, source)
            or not is_postgres(source)
            or is_explicit_dump_file(source, path)
            or is_generated_migration(path, source)
            or {part.lower() for part in path.parts}
            & (NON_POSTGRES_SQL_PARTS | {"test", "tests", "testing", "__tests__"})
        ):
            return []
        findings: list[Diagnostic] = []
        for control in migration_timeout_controls(source):
            if control.justification is not None:
                continue
            location = source_location(source, control.offset)
            findings.append(
                Diagnostic(
                    path,
                    location.line,
                    location.column,
                    self.code,
                    f"Migration timeout `{control.setting}` needs a scoped operational reason; add "
                    f"`-- timeout-justification: {control.setting} -- <why>` immediately before this statement, "
                    "or review whether the timeout bookkeeping should be removed.",
                )
            )
        return findings
