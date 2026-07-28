"""SARJ108: `CREATE INDEX` must use `CONCURRENTLY`.

A plain `CREATE INDEX` takes an `ACCESS EXCLUSIVE`-ish lock that blocks all writes
to the table for the full build — on a large production table that is an outage.
`CREATE INDEX CONCURRENTLY` builds without blocking writes. (It cannot run inside a
transaction block, so such migrations must be marked non-transactional.)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# `CONCURRENTLY` must come right after `INDEX` (before any `IF NOT EXISTS`).
PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!CONCURRENTLY\b)",
    re.IGNORECASE,
)


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

        diags: list[Diagnostic] = []

        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use `CREATE INDEX CONCURRENTLY` — a plain CREATE INDEX "
                        "locks the table against writes for the whole build."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return diags
