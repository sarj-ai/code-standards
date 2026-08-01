"""SARJ106: forbid the non-B `JSON` type and `::json` casts — use JSONB.

Plain `json` stores raw text: every read re-parses, no indexing (GIN),
no containment operators, and duplicate keys / whitespace are preserved
so equality is unreliable. JSONB is the right default for every column
and cast; the word boundary in the pattern keeps `JSONB` itself, and
identifiers like `json_build_object`, from matching.
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
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


# \b...\b does not match JSONB (B is a word char) nor json_* identifiers
# (underscore is a word char), but catches both `JSON` column types and
# `::json` casts such as `DEFAULT '{}'::json`.
PATTERN = re.compile(r"\bJSON\b", re.IGNORECASE)


@final
class PreferJsonb(Rule):
    """JSON column type or ::json cast — use JSONB."""

    id = "prefer-jsonb"
    code = "SARJ106"
    description = "JSON column type or ::json cast — use JSONB."

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
                        "Use JSONB — plain JSON has no indexing or containment operators and re-parses on every read."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return redirect_to_model(diags, model_owned=model_owned)
