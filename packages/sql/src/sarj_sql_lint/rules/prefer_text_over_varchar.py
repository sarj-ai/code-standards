"""SARJ104: forbid `VARCHAR(n)` / `CHARACTER VARYING(n)` — use TEXT."""

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
