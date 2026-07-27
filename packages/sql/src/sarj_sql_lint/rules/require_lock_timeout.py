"""SARJ110: Require lock_timeout or statement_timeout before migration DDL.

DDL operations like ALTER TABLE or CREATE INDEX can hang waiting for heavy lock
acquisitions, blocking production queries. Migrations with DDL must set a positive lock_timeout
or statement_timeout prior to executing each DDL block.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TX_END_PATTERN = re.compile(r"\b(COMMIT|ROLLBACK)\b", re.IGNORECASE)

TIMEOUT_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:SET\s+(?:LOCAL\s+)?|RESET\s+)(lock_timeout|statement_timeout)(?:\s*(?:=|\bTO\b)\s*([^\s;]+))?",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(r"^['\"]?(?:[1-9]\d*|[1-9]\d*[a-zA-Z]+)['\"]?$", re.IGNORECASE)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing positive SET [LOCAL] lock_timeout or statement_timeout prior to DDL."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked = mask_sql(source)

        for ddl_match in DDL_PATTERN.finditer(masked):
            ddl_start = ddl_match.start()
            tx_ends = [c.end() for c in TX_END_PATTERN.finditer(masked, 0, ddl_start)]
            block_start = tx_ends[-1] if tx_ends else 0

            block_source = source[block_start:ddl_start]
            assignments = list(TIMEOUT_ASSIGNMENT_PATTERN.finditer(block_source))

            has_active_timeout = False
            if assignments:
                last = assignments[-1]
                cmd = last.group(0).upper()
                val = (last.group(2) or "").strip()
                if "RESET" not in cmd and val and POSITIVE_VAL_PATTERN.match(val):
                    has_active_timeout = True

            if not has_active_timeout:
                lineno = masked[:ddl_start].count("\n") + 1
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=1,
                        code=self.code,
                        message=(
                            "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set "
                            "a positive `SET [LOCAL] lock_timeout = ...` or `statement_timeout = ...` prior to DDL statements."
                        ),
                    )
                )

        return diags
