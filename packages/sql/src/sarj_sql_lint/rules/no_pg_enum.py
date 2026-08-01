"""SARJ103: forbid `CREATE TYPE ... AS ENUM` — use TEXT + CHECK constraint.

Postgres enums can't be altered transactionally: adding a value can't run
inside the same transaction that uses it, removing or reordering values is
effectively impossible, and renames ripple through every dependent object.
A TEXT column with a CHECK constraint gives the same integrity guarantee
and migrates with a plain `ALTER TABLE ... DROP/ADD CONSTRAINT`.
Schema dumps are exempt (`is_dump_file`). A pg_dump snapshot is a rendering of a
schema that already exists: the diagnostic asks for an edit to a file that the
next `pg_dump` regenerates, and the defect it names, if real, has to be fixed in a
migration anyway. This exemption already guarded SARJ102, SARJ108 and SARJ110;
`is_dump_file` accounted for 41.7% of the pre-dedupe population of the rules that
were not calling it.

Generator-owned migrations are exempt (`is_generated_migration`). Prisma, Drizzle
and Atlas compile a model down to SQL, so the fix belongs in `schema.prisma` (or
the Drizzle schema module) and an edit to the emitted migration is reverted by the
next generate — and applied migrations are immutable by construction, since Prisma
checksums them in `_prisma_migrations` and `migrate deploy` errors on drift.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    locate,
    mask_sql,
    redirect_to_model,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


# Matched at statement level (DOTALL) so a `CREATE TYPE` whose `AS ENUM` lands on
# a later line is still caught.
_CREATE_ENUM_RE = re.compile(r"\bCREATE\s+TYPE\b.*?\bAS\s+ENUM\b", re.IGNORECASE | re.DOTALL)
_ALTER_ADD_VALUE_RE = re.compile(r"\bALTER\s+TYPE\b.*?\bADD\s+VALUE\b", re.IGNORECASE | re.DOTALL)


@final
class NoPgEnum(Rule):
    """CREATE TYPE ... AS ENUM — use TEXT + CHECK constraint instead."""

    id = "no-pg-enum"
    code = "SARJ103"
    description = "CREATE TYPE ... AS ENUM — use TEXT + CHECK constraint instead."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        for statement in split_statements(mask_sql(source)):
            text = "\n".join(t for _, t in statement)
            for pattern in (_CREATE_ENUM_RE, _ALTER_ADD_VALUE_RE):
                match = pattern.search(text)
                if match is None:
                    continue
                line, col = locate(statement, match.start())
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=self.code,
                        message=("Use TEXT + CHECK constraint — PG enums can't be altered transactionally."),
                    )
                )
        return redirect_to_model(diags, model_owned=model_owned)
