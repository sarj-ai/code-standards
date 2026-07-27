"""SARJ110: Require lock_timeout or statement_timeout in migration DDL.

DDL operations like ALTER TABLE or CREATE INDEX can hang waiting for heavy lock
acquisitions, blocking production queries. Migrations with DDL must explicitly set
lock_timeout or statement_timeout.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TIMEOUT_PATTERN = re.compile(r"\bSET\s+(lock_timeout|statement_timeout)\b", re.IGNORECASE)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing SET lock_timeout or SET statement_timeout."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        masked = mask_sql(source)
        if not DDL_PATTERN.search(masked):
            return []

        if TIMEOUT_PATTERN.search(masked):
            return []

        first_ddl = DDL_PATTERN.search(masked)
        lineno = masked[: first_ddl.start()].count("\n") + 1 if first_ddl else 1
        return [
            Diagnostic(
                path=path,
                line=lineno,
                col=1,
                code=self.code,
                message=(
                    "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set "
                    "`SET lock_timeout = ...` or `SET statement_timeout = ...` to prevent hanging lock acquisitions."
                ),
            )
        ]
