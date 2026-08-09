"""SARJ110: Require lock_timeout or statement_timeout before migration DDL."""

from __future__ import annotations

from decimal import Decimal
import operator
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
    dollar_quoted_lines,
    has_dbmate_directive,
    is_dump_file,
    is_postgres_migration,
    mask_sql,
)


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(
    r"\b(ALTER\s+(?:TABLE|TYPE)|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+(?:INDEX|TABLE)|REINDEX(?:\s+(?:DATABASE|INDEX|SCHEMA|SYSTEM|TABLE))?|TRUNCATE(?:\s+TABLE)?)\b",
    re.IGNORECASE,
)
TX_END_PATTERN = re.compile(r"\b(COMMIT|ROLLBACK)\b", re.IGNORECASE)
SECTION_BOUNDARY_PATTERN = re.compile(
    r"^\s*--\s*(?:migrate:down(?:\s+transaction:false)?|\+goose\s+down)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Match SET/RESET/set_config assignments for lock_timeout or statement_timeout.
ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:SET\s+(?:(?:LOCAL|SESSION)\s+)?|RESET\s+)(lock_timeout|statement_timeout)\b(?:\s*(?:=|\bTO\b)\s*('[\s\S]*?'|\"[^\"]*\"|[^\s;]+))?|set_config\s*\(\s*'?(lock_timeout|statement_timeout)'?\s*,\s*('[\s\S]*?'|\"[^\"]*\"|[^\s,;]+)\s*,\s*(true|false)\s*\)",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(r"^['\"]?\s*(?P<number>[0-9]*\.?[0-9]+)\s*(?:[a-zA-Z]+\s*)?['\"]?$", re.IGNORECASE)


def _positive_timeout(value: str) -> bool:
    """Accept the deliberately small timeout grammar only when its number is positive."""
    match = POSITIVE_VAL_PATTERN.fullmatch(value)
    return match is not None and Decimal(match.group("number")) > 0


def _section_boundary_events(source: str) -> list[tuple[int, str, re.Match[str]]]:
    """Return live migration-runner section boundaries as state-machine events."""
    dollar_lines = dollar_quoted_lines(source)
    return [
        (boundary_offset, "SECTION_BOUNDARY", match)
        for match in SECTION_BOUNDARY_PATTERN.finditer(source)
        if source.count("\n", 0, (boundary_offset := match.start())) + 1 not in dollar_lines
    ]


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    documentation = RuleDocumentation(
        summary="DDL migration missing positive SET [LOCAL] lock_timeout or statement_timeout prior to DDL.",
        rationale="Unbounded lock waits can stall production traffic indefinitely when migration DDL contends with active transactions.",
        remediation="Set a short positive lock_timeout or statement_timeout before the DDL statement.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=("Only PostgreSQL migration paths and explicitly marked PostgreSQL migrations are checked.",),
        examples=(
            RuleExample(
                example_id="unbounded-ddl-lock-wait",
                title="DDL without a positive timeout",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql("supabase/migrations/001_users.sql", "ALTER TABLE users ADD COLUMN note TEXT;\n"),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bounded-ddl-lock-wait",
                title="DDL preceded by a positive lock timeout",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_users.sql",
                        "SET lock_timeout = '3s';\nALTER TABLE users ADD COLUMN note TEXT;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_users.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_migration(path, source):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql(source)
        nontransactional = has_dbmate_directive(source, "no-transaction")

        events: list[tuple[int, str, re.Match[str]]] = []
        # Match raw quoted values, then require the assignment's offset to remain live after masking SQL noise.
        for match in ASSIGNMENT_PATTERN.finditer(source):
            start_pos = match.start()
            if masked[start_pos : start_pos + 3].strip():
                events.append((start_pos, "ASSIGNMENT", match))
        events.extend((match.start(), "TX_END", match) for match in TX_END_PATTERN.finditer(masked))
        events.extend(_section_boundary_events(source))
        events.extend((match.start(), "DDL", match) for match in DDL_PATTERN.finditer(masked))

        events.sort(key=operator.itemgetter(0))

        active_global_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        active_local_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        # Report once per contiguous run of DDL under one timeout state, re-arming on state-changing events.
        reported_for_current_state = False

        for pos, event_type, match in events:
            if event_type != "DDL":
                reported_for_current_state = False
            if event_type == "ASSIGNMENT":
                cmd = match.group(0).upper()
                is_local = "LOCAL" in cmd or (match.group(5) or "").lower() == "true"
                target_var = (match.group(1) or match.group(3) or "").lower()
                val = (match.group(2) or match.group(4) or "").strip().strip(";")

                is_active = False if "RESET" in cmd else (bool(val) and _positive_timeout(val))

                if is_local:
                    active_local_timeouts[target_var] = is_active and not nontransactional
                else:
                    active_global_timeouts[target_var] = is_active
            elif event_type == "TX_END":
                active_local_timeouts = {"lock_timeout": False, "statement_timeout": False}
            elif event_type == "SECTION_BOUNDARY":
                # Up/down sections are separate migration-runner invocations.
                # Neither session nor transaction-local settings cross the boundary.
                active_global_timeouts = {"lock_timeout": False, "statement_timeout": False}
                active_local_timeouts = {"lock_timeout": False, "statement_timeout": False}
            elif event_type == "DDL":
                has_timeout = any(active_global_timeouts.values()) or any(active_local_timeouts.values())
                if not has_timeout and not reported_for_current_state:
                    reported_for_current_state = True
                    lineno = masked[:pos].count("\n") + 1
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=lineno,
                            col=1,
                            code=self.code,
                            message=(
                                "A nontransactional migration containing DDL must set a positive session "
                                "`SET lock_timeout = ...` or `statement_timeout = ...` before DDL and `RESET` it afterward; "
                                "`SET LOCAL` has no effective transaction scope here."
                                if nontransactional
                                else "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set a positive `SET [LOCAL] lock_timeout = ...` or `statement_timeout = ...` prior to DDL statements."
                            ),
                        )
                    )

        return diags
