"""SARJ110: Require lock_timeout or statement_timeout before migration DDL.

DDL operations like ALTER TABLE or CREATE INDEX can hang waiting for heavy lock
acquisitions, blocking production queries. Migrations with DDL must set lock_timeout
or statement_timeout prior to executing each DDL block.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TIMEOUT_PATTERN = re.compile(r"\bSET\s+(?:LOCAL\s+)?(lock_timeout|statement_timeout)\b", re.IGNORECASE)
COMMIT_PATTERN = re.compile(r"\bCOMMIT\b", re.IGNORECASE)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing SET [LOCAL] lock_timeout or statement_timeout prior to DDL."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        masked = mask_sql(source)

        for ddl_match in DDL_PATTERN.finditer(masked):
            ddl_start = ddl_match.start()
            commits = [c.end() for c in COMMIT_PATTERN.finditer(masked, 0, ddl_start)]
            block_start = commits[-1] if commits else 0

            block_content = masked[block_start:ddl_start]
            if not TIMEOUT_PATTERN.search(block_content):
                lineno = masked[:ddl_start].count("\n") + 1
                diags.append(
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
                )

        return diags
