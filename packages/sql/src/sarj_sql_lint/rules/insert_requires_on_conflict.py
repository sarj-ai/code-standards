"""SARJ105: `INSERT INTO` in a migration must carry conflict handling."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, dollar_quoted_lines, is_dump_file, mask_sql, split_statements


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


def _guarded_dollar_body_lines(masked: str, source: str) -> frozenset[int]:
    """1-based line numbers inside a dollar-quoted body that guards its own replay."""
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


@final
class InsertRequiresOnConflict(Rule):
    """INSERT INTO in a migration without ON CONFLICT — must be an idempotent upsert."""

    id = "insert-requires-on-conflict"
    code = "SARJ105"
    description = "INSERT without ON CONFLICT — migration data writes must be idempotent upserts."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        masked = mask_sql(source)
        exempt = _guarded_dollar_body_lines(masked, source)
        diags: list[Diagnostic] = []
        for statement in split_statements(masked):
            text = "\n".join(line for _, line in statement)
            if INSERT_PATTERN.search(text) is None or ON_CONFLICT_PATTERN.search(text):
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
