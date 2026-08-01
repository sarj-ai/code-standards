"""SARJ104: forbid `VARCHAR(n)` / `CHARACTER VARYING(n)` — use TEXT.

In Postgres, VARCHAR(n) has no performance benefit over TEXT; the length
cap is a hidden business rule baked into the schema that fails with an
opaque error and needs a table rewrite-risking ALTER to change. Use TEXT,
and add an explicit CHECK (char_length(col) <= n) if a length limit is a
real domain constraint.

This was the worst-behaved rule in the registry: a 25-finding seeded sample of the
520 findings over 2,133 deduped `.sql` files read TP 3 / FP 21 — 84% wrong. Three
guards, in descending order of yield.

**The advice is false outside Postgres** — 42.5% of the pre-dedupe population was
MySQL, where `TEXT` cannot carry a `DEFAULT`, is stored off-page, and is subject to
an index-prefix limit, so "use TEXT" is not a neutral style preference but actively
harmful schema advice, e.g. `unkey/pkg/mysql/schema/deployments.sql:10` and
`.../environments.sql:8`. Teradata is caught by the same guard where it is marked,
e.g. `airflow/providers/teradata/tests/system/teradata/create_table.sql:20`. The
docstring's own premise names Postgres; the rule now checks that the file is
Postgres before applying it.

**pg_dump schema snapshots** — 41.7% of the pre-dedupe population. `is_dump_file`
already existed in `rule_base` and already recognised `schema.sql` by name; this
rule simply never called it. A dump is a rendering of a schema that already exists,
so a diagnostic on it asks for an edit to a file that is regenerated on every dump.

**Generator-owned migrations.** The fix for a `VARCHAR(n)` emitted by Prisma is
`@db.Text` in `schema.prisma`, not an edit to the migration — see
`is_generated_migration`.

Together these are three statements of one idea: the rule is a *Postgres schema
authoring* rule, and it should only speak where the schema is being authored, in
Postgres, by hand.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    is_postgres,
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(
    r"\b(?:VARCHAR|CHARACTER\s+VARYING)\s*\(",
    re.IGNORECASE,
)


@final
class PreferTextOverVarchar(Rule):
    """VARCHAR(n) / CHARACTER VARYING(n) — use TEXT (+ CHECK length if needed)."""

    id = "prefer-text-over-varchar"
    code = "SARJ104"
    description = "VARCHAR(n) — use TEXT (+ CHECK length if needed)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)
        masked = mask_sql(source)
        if not is_postgres(source):
            return []

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(masked.splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use TEXT (+ CHECK length if needed) — VARCHAR(n) has "
                        "no benefit in Postgres and hides a business rule in DDL."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return redirect_to_model(diags, model_owned=model_owned)
