"""SARJ110: Require lock_timeout or statement_timeout before migration DDL.

DDL operations like ALTER TABLE or CREATE INDEX can hang waiting for heavy lock
acquisitions, blocking production queries. Migrations with DDL must set lock_timeout
or statement_timeout prior to executing the DDL.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TIMEOUT_PATTERN = re.compile(r"\bSET\s+(?:LOCAL\s+)?(lock_timeout|statement_timeout)\b", re.IGNORECASE)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing SET [LOCAL] lock_timeout or statement_timeout prior to DDL."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        masked = mask_sql(source)
        ddl_match = DDL_PATTERN.search(masked)
        if not ddl_match:
            return []

        # Check if timeout setting exists BEFORE the first DDL statement
        pre_ddl_content = masked[: ddl_match.start()]
        if TIMEOUT_PATTERN.search(pre_ddl_content):
            return []

        lineno = masked[: ddl_match.start()].count("\n") + 1
        return [
            Diagnostic(
                path=path,
                line=lineno,
                col=1,
                code=self.code,
                message=(
                    "Migration containing DDL (`ALTER TABLE`/`CREATE INDEX`) must set "
                    "`SET [LOCAL] lock_timeout = ...` or `statement_timeout = ...` prior to DDL statements."
                ),
            )
        ]
