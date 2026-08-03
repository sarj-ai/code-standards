"""SARJ109: `gen_random_uuid()` in a migration — use `uuidv7()`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, is_generated_migration, mask_sql, redirect_to_model


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)

_MESSAGE = (
    "`gen_random_uuid()` generates a random UUIDv4 — use `uuidv7()` (Postgres 18). "
    "Random keys scatter inserts across every B-tree leaf page; UUIDv7 is "
    "time-ordered, so inserts append to the index's right edge."
)


@final
class PreferUuidv7Default(Rule):
    """`gen_random_uuid()` default — use the time-ordered `uuidv7()`."""

    id = "prefer-uuidv7-default"
    code = "SARJ109"
    description = "`gen_random_uuid()` emits a random UUIDv4 — use `uuidv7()` so keys are time-ordered."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every `gen_random_uuid(` call in real (unmasked) SQL."""
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)
        return redirect_to_model(
            [
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=_MESSAGE,
                )
                for lineno, line in enumerate(mask_sql(source).splitlines(), start=1)
                for match in PATTERN.finditer(line)
            ],
            model_owned=model_owned,
        )
