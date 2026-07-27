"""SARJ112: Require index on Foreign Key column.

Postgres does NOT automatically index foreign key columns. Deleting rows from a parent table
triggers a full sequential scan on the child table if the FK is unindexed, locking the child table.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


FK_PATTERN = re.compile(
    r"\bFOREIGN\s+KEY\s*\(\s*([a-zA-Z0-9_]+)\s*\)\s*REFERENCES\b",
    re.IGNORECASE,
)


@final
class RequireFkIndex(Rule):
    """Foreign key column without corresponding index."""

    id = "require-fk-index"
    code = "SARJ112"
    description = "FOREIGN KEY column missing index — causes full-table scans and locks on parent row deletes."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked = mask_sql(source)
        for lineno, line in enumerate(masked.splitlines(), start=1):
            match = FK_PATTERN.search(line)
            if match:
                fk_col = match.group(1)
                col_idx_pattern = re.compile(rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b.*\b{re.escape(fk_col)}\b", re.IGNORECASE)
                if not col_idx_pattern.search(masked):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=lineno,
                            col=match.start() + 1,
                            code=self.code,
                            message=(
                                f"Foreign key column `{fk_col}` should have a corresponding `CREATE INDEX` "
                                "to prevent full table scans and lock contention during parent row deletes."
                            ),
                        )
                    )
        return diags
