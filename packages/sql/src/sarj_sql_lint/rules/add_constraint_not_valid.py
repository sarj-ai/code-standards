"""SARJ111: Enforce NOT VALID on ADD CONSTRAINT (CHECK/FK) in table alterations.

Adding CHECK or FOREIGN KEY constraints on existing tables blocks writes during full-table validation.
Use `ADD CONSTRAINT ... NOT VALID;` followed by a separate `VALIDATE CONSTRAINT` step.
Note: Postgres does not support NOT VALID for UNIQUE, PRIMARY KEY, or EXCLUDE constraints.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


ADD_CONSTRAINT_KEYWORD = re.compile(r"\bADD\s+CONSTRAINT\b", re.IGNORECASE)
TARGET_KIND_PATTERN = re.compile(r"\b(CHECK|FOREIGN\s+KEY)\b", re.IGNORECASE)
NOT_VALID_PATTERN = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)


@final
class AddConstraintNotValid(Rule):
    """ADD CONSTRAINT (CHECK / FK) on existing table missing NOT VALID."""

    id = "add-constraint-not-valid"
    code = "SARJ111"
    description = "ADD CONSTRAINT (CHECK/FK) without NOT VALID blocks writes during full-table validation."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked = mask_sql(source)

        matches = list(ADD_CONSTRAINT_KEYWORD.finditer(masked))
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(masked)
            semi_idx = masked.find(";", start, end)
            if semi_idx != -1:
                end = semi_idx

            clause = masked[start:end]
            if TARGET_KIND_PATTERN.search(clause) and not NOT_VALID_PATTERN.search(clause):
                lineno = masked[:start].count("\n") + 1
                col = start - masked.rfind("\n", 0, start)
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=max(1, col),
                        code=self.code,
                        message=(
                            "Use `ADD CONSTRAINT ... NOT VALID;` followed by a separate "
                            "`ALTER TABLE ... VALIDATE CONSTRAINT` step to prevent table locks during validation."
                        ),
                    )
                )

        return diags
