"""SARJ108: `CREATE INDEX` must use `CONCURRENTLY`.

A plain `CREATE INDEX` takes an `ACCESS EXCLUSIVE`-ish lock that blocks all writes
to the table for the full build — on a large production table that is an outage.
`CREATE INDEX CONCURRENTLY` builds without blocking writes. (It cannot run inside a
transaction block, so such migrations must be marked non-transactional.)

Two guards, from a 24-finding seeded sample of the 1,750 findings this rule
produced over 2,133 deduped `.sql` files (TP 7 / FP 17 — 70.8% wrong).

**Index on a table created in the same file** — 1,117 of 1,750 (63.5%), the
dominant class::

    CREATE TABLE foo (...);
    CREATE INDEX idx_foo_bar ON foo (bar);

The table is brand new: it holds no rows and has no concurrent writers, so
`CONCURRENTLY` buys nothing. Following the advice is worse than ignoring it,
because `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block — taking
it forces an otherwise-atomic migration to become non-transactional, trading a
zero-risk lock for a half-applied-migration risk. Seen throughout the corpus, e.g.
`midday/packages/db/migrations/0010_add_invoice_recurring.sql:73`,
`cal.com/packages/prisma/migrations/20220616072241_app_routing_forms/migration.sql:27`
and `litellm/.../20260321000000_add_mcp_toolsets/migration.sql:16`.

Recall cost measured, not assumed: 12 findings suppressed by this guard were
re-sampled at seed 99 and read by hand — 12 of 12 were an index on a table created
immediately above, 0 true positives. The guard is keyed on the index's *target
table*, so an index-only migration against an existing table — the actual outage
case — is untouched. Three of those are pinned below as still firing:
`documenso/.../20231030055821_add_database_indexes/migration.sql:23`,
`papermark/prisma/migrations/20250915000000_add_performance_indexes/migration.sql:5`,
`formbricks/.../20231107145619_add_indexes/migration.sql:11`.

**Non-Postgres dialect** — 498 of 1,750 (28.3%). `CONCURRENTLY` is a syntax error
in SQLite and MySQL, e.g. `openstatus/packages/db/drizzle/0064_dusty_sunfire.sql:20`.
See `is_postgres` — the dialect-marker and Postgres-only-token populations are
disjoint across the corpus, so this costs no Postgres recall.

The rule is deliberately NOT given the `is_generated_migration` exemption. Unlike
SARJ101/SARJ104, whose fix lives in `schema.prisma` and would be reverted by the
next `prisma migrate`, a missing `CONCURRENTLY` is a production lock risk that
survives regeneration and that a reviewer fixes by hand-editing a `--create-only`
migration before it ships.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, is_postgres, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# `CONCURRENTLY` must come right after `INDEX` (before any `IF NOT EXISTS`).
PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!CONCURRENTLY\b)",
    re.IGNORECASE,
)

# Both table-name patterns are matched against the RAW source, not against
# `mask_sql` output, because the masker blanks `"..."` quoted identifiers — and
# Prisma, which emits the majority of this rule's population, double-quotes every
# table name, so on masked text the name is a run of spaces and the guard silently
# never fires. Each match is instead gated on `masked` being live code at the same
# offset (the masker is length-preserving), which is what keeps a `CREATE TABLE`
# inside a comment or a string from counting.

# The index's target table. Searched forward from the `CREATE INDEX` match and
# bounded by the statement's `;`, so it survives the common multi-line spelling
# where `ON <table>` sits on its own line.
_ON_TABLE_RE = re.compile(r"\bON\s+(?:ONLY\s+)?([A-Za-z0-9_.\"]+)", re.IGNORECASE)

_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)",
    re.IGNORECASE,
)


def _base_name(raw: str) -> str:
    """Reduce a possibly schema-qualified, possibly quoted table name to a bare key.

    Returns:
        The lowercased final name component with quotes stripped.

    """
    return raw.replace('"', "").rsplit(".", 1)[-1].lower()


@final
class IndexConcurrently(Rule):
    """CREATE INDEX without CONCURRENTLY — blocks writes for the whole build."""

    id = "index-concurrently"
    code = "SARJ108"
    description = "CREATE INDEX without CONCURRENTLY — locks the table against writes."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        masked = mask_sql(source)
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
                if created_at is not None and created_at < pos:
                    continue
            line_start = masked.rfind("\n", 0, pos) + 1
            diags.append(
                Diagnostic(
                    path=path,
                    line=masked.count("\n", 0, pos) + 1,
                    col=pos - line_start + 1,
                    code=self.code,
                    message=(
                        "Use `CREATE INDEX CONCURRENTLY` — a plain CREATE INDEX "
                        "locks the table against writes for the whole build."
                    ),
                )
            )
        return diags


def _is_live(masked: str, pos: int) -> bool:
    """Report whether offset `pos` is real SQL rather than a masked comment or literal.

    Returns:
        True when `masked` still holds a character at `pos`.

    """
    return pos < len(masked) and not masked[pos].isspace()


def _target_table(source: str, masked: str, start: int) -> str | None:
    """Name the table an index built from `start` is created on.

    The statement boundary is read from `masked`, so a `;` inside a string or
    comment cannot end the statement early, while the table name is read from
    `source`, so a `"Quoted"` name survives.

    Returns:
        The bare target table name, or None when the statement names none.

    """
    end = masked.find(";", start)
    stmt_end = len(masked) if end == -1 else end
    match = _ON_TABLE_RE.search(source, start, stmt_end)
    if match is None or not _is_live(masked, match.start()):
        return None
    return _base_name(match.group(1))
