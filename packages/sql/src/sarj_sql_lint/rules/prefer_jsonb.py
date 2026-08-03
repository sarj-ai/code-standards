"""SARJ106: forbid the non-B `JSON` type and `::json` casts — use JSONB."""

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
