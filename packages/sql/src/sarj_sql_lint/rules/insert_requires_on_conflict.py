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
    dollar_quoted_lines,
    is_dump_file,
    is_postgres_migration,
    mask_sql,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


# A real insert write pattern matching INSERT INTO with optional column list and write verb.
INSERT_PATTERN = re.compile(
    r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w.\"'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b",
    re.IGNORECASE,
)

# Matches just the INSERT INTO keyword on one line for locating diagnostic position.
INSERT_KEYWORD_PATTERN = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\b", re.IGNORECASE)

# Conflict handling pattern making writes replay-safe across Postgres, MySQL, and SQLite.
ON_CONFLICT_PATTERN = re.compile(
    r"\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b",
    re.IGNORECASE,
)

# A procedural replay guard inside a `DO $$ ... $$` seed block: the block checks
# for the row itself and skips, so `ON CONFLICT` would be dead code.
REPLAY_GUARD_PATTERN = re.compile(r"\bIF\s+(?:NOT\s+)?EXISTS\s*\(", re.IGNORECASE)
INSERT_SELECT_TARGET_PATTERN = re.compile(
    r"\bINSERT\s+INTO\s+(?P<target>[A-Za-z_][\w$]*(?:\s*\.\s*[A-Za-z_][\w$]*)?)\b[\s\S]*?\bSELECT\b",
    re.IGNORECASE,
)


def _guarded_dollar_body_lines(masked: str, source: str) -> frozenset[int]:
    inside = dollar_quoted_lines(source)
    if not inside:
        return frozenset()
    masked_lines = masked.splitlines()
    guarded: set[int] = set()
    run: list[int] = []

    def flush() -> None:
        if not run:
            return
        body = "\n".join(masked_lines[lineno - 1] for lineno in run if lineno <= len(masked_lines))
        if REPLAY_GUARD_PATTERN.search(body):
            guarded.update(run)
        run.clear()

    for lineno in sorted(inside):
        if run and lineno != run[-1] + 1:
            flush()
        run.append(lineno)
    flush()
    return frozenset(guarded)


def _select_filters_existing_target(statement: str) -> bool:
    match = INSERT_SELECT_TARGET_PATTERN.search(statement)
    if match is None:
        return False
    target = re.sub(r"\s+", "", match.group("target")).split(".")[-1]
    guard = re.compile(
        rf"\bWHERE\s+NOT\s+EXISTS\s*\([\s\S]*?\bFROM\s+(?:[A-Za-z_][\w$]*\s*\.\s*)?{re.escape(target)}\b",
        re.IGNORECASE,
    )
    return guard.search(statement, match.end()) is not None


@final
class InsertRequiresOnConflict(Rule):
    id = "insert-requires-on-conflict"
    code = "SARJ105"
    documentation = RuleDocumentation(
        summary="INSERT without ON CONFLICT — migration data writes must be idempotent upserts.",
        rationale="A retried seed migration can duplicate rows or fail on a uniqueness constraint when an insert has no replay behavior.",
        remediation="Add ON CONFLICT with an explicit DO NOTHING or DO UPDATE action.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=("Only PostgreSQL migration paths and explicitly marked PostgreSQL migrations are checked.",),
        examples=(
            RuleExample(
                example_id="non-idempotent-seed-insert",
                title="Seed insert without conflict handling",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql("supabase/migrations/001_seed.sql", "INSERT INTO plan (name) VALUES ('free');\n"),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_seed.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="idempotent-seed-insert",
                title="Seed insert with conflict handling",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_seed.sql",
                        "INSERT INTO plan (name) VALUES ('free') ON CONFLICT (name) DO NOTHING;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_seed.sql"),
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

        masked = mask_sql(source)
        exempt = _guarded_dollar_body_lines(masked, source)
        diags: list[Diagnostic] = []
        for statement in split_statements(masked):
            text = "\n".join(line for _, line in statement)
            if (
                INSERT_PATTERN.search(text) is None
                or ON_CONFLICT_PATTERN.search(text)
                or _select_filters_existing_target(text)
            ):
                continue
            # Point at the line holding `INSERT INTO`; if the keywords are
            # split across lines, fall back to the statement's first line.
            lineno, col = statement[0][0], 1
            for stmt_lineno, line in statement:
                if match := INSERT_KEYWORD_PATTERN.search(line):
                    lineno, col = stmt_lineno, match.start() + 1
                    break
            if lineno in exempt:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=col,
                    code=self.code,
                    message=(
                        "Data writes in migrations must be idempotent upserts — "
                        "add `ON CONFLICT ... DO UPDATE` (or `DO NOTHING`)."
                    ),
                )
            )
        return diags
