"""SARJ111: Enforce NOT VALID on ADD CONSTRAINT in table alterations.

Adding CHECK or FOREIGN KEY constraints directly blocks writes while validating existing rows.
Use `ADD CONSTRAINT ... NOT VALID;` followed by `VALIDATE CONSTRAINT`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


ADD_CONSTRAINT_PATTERN = re.compile(
    r"\bADD\s+CONSTRAINT\b",
    re.IGNORECASE,
)


@final
class AddConstraintNotValid(Rule):
    """ADD CONSTRAINT on existing table missing NOT VALID."""

    id = "add-constraint-not-valid"
    code = "SARJ111"
    description = "ADD CONSTRAINT without NOT VALID blocks writes during full-table validation."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            if "ADD CONSTRAINT" in line.upper() and not re.search(r"\bNOT\s+VALID\b", line, re.IGNORECASE):
                match = ADD_CONSTRAINT_PATTERN.search(line)
                col = match.start() + 1 if match else 1
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=col,
                        code=self.code,
                        message=(
                            "Use `ADD CONSTRAINT ... NOT VALID;` followed by a separate "
                            "`ALTER TABLE ... VALIDATE CONSTRAINT` step to prevent table locks during validation."
                        ),
                    )
                )
        return diags
