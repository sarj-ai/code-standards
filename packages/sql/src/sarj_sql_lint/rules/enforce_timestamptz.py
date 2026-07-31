r"""SARJ101: detect TIMESTAMP columns missing `WITH TIME ZONE`.

Postgres `TIMESTAMP` without `WITH TIME ZONE` discards offset on INSERT,
silently producing wrong timestamps for non-UTC clients. Use TIMESTAMPTZ.

This is a loud-and-correct rule and is deliberately not weakened beyond the one
guard below: a 25-finding seeded sample of the 793 findings over 2,133 deduped
`.sql` files read TP 20 / FP 5, and the population rate of the FP class is nearer
3% than the sample's 20%.

**`timestamp` used as a column NAME, not a type.** `\\bTIMESTAMP\\b` matches any
bare identifier, and `timestamp` is a conventional column name in ClickHouse DDL
(`PARTITION BY toYYYYMM(timestamp)`, `ORDER BY (org_id, timestamp, api_key_id)`)
and in CTE column lists (`prefect/tests/scripts/populate_database.sql:59` —
`WITH states (TYPE, name, timestamp, state_details)`). The two uses are told apart
by position: a *type* is preceded by a column name, while a bare column reference
in a list is bracketed by `(`/`,` on the left and `,`/`)` on the right. Measured on
the corpus, the predicate partitions the population cleanly — 815 type-position
occurrences, 23 column-reference occurrences, no overlap — so the guard costs zero
recall. `created_at TIMESTAMP,` and `ts TIMESTAMP)` keep firing, because the
character before the keyword is part of the column name.

The rule also stops reporting on pg_dump snapshots (`is_dump_file`) and on
generator-owned migrations (`is_generated_migration`): the fix for a Prisma-emitted
naive timestamp is `@db.Timestamptz` in `schema.prisma`, and an edit to the
migration is reverted by the next `prisma migrate`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


# `\b...\b` already excludes TIMESTAMPTZ (no boundary before TZ). An optional
# precision modifier `(n)` is allowed before WITH TIME ZONE so the lookahead does
# not misfire on `TIMESTAMP(3) WITH TIME ZONE`.
PATTERN = re.compile(
    r"\bTIMESTAMP\b(?!\s*(?:\(\s*\d+\s*\)\s*)?WITH\s+TIME\s+ZONE\b)",
    re.IGNORECASE,
)

_OPENS_LIST_ITEM = frozenset("(,")
_CLOSES_LIST_ITEM = frozenset(",)")


def _is_column_reference(line: str, start: int, end: int) -> bool:
    """Report whether the `TIMESTAMP` token at `[start:end)` is a bare list element.

    A type always follows a column name, so its left neighbour is an identifier
    character. A `timestamp` that is bracketed by `(`/`,` on the left *and* `,`/`)`
    on the right carries no name and is therefore a reference to a column called
    `timestamp`, not a type.

    Returns:
        True when the token is a bare element of a parenthesised list.

    """
    before = line[:start].rstrip()
    after = line[end:].lstrip()
    return bool(before) and before[-1] in _OPENS_LIST_ITEM and bool(after) and after[0] in _CLOSES_LIST_ITEM


@final
class EnforceTimestamptz(Rule):
    """Postgres TIMESTAMP without WITH TIME ZONE — use TIMESTAMPTZ."""

    id = "enforce-timestamptz"
    code = "SARJ101"
    description = "TIMESTAMP without TIME ZONE — use TIMESTAMPTZ."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use `TIMESTAMPTZ` (or `TIMESTAMP WITH TIME ZONE`) — "
                        "naive TIMESTAMP discards offset and is rarely correct."
                    ),
                )
                for match in PATTERN.finditer(line)
                if not _is_column_reference(line, match.start(), match.end())
            )
        return redirect_to_model(diags, model_owned=model_owned)
