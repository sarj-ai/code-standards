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

ASSIGNMENT_PATTERN = re.compile(
    r"\b(SET\s+LOCAL|SET|RESET)\s+(lock_timeout|statement_timeout)(?:\s*(?:=|\bTO\b)\s*([^\s;]+))?",
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

            active_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
            tx_ends = [c.end() for c in TX_END_PATTERN.finditer(masked, 0, ddl_start)]

            for match in ASSIGNMENT_PATTERN.finditer(source, 0, ddl_start):
                match_pos = match.start()

                # Verify assignment is not inside a comment
                if masked[match_pos:match_pos+3].strip() == "" and "--" in source[:match_pos].splitlines()[-1]:
                    continue

                is_local = "LOCAL" in match.group(1).upper()
                expired_by_tx = is_local and any(t > match_pos for t in tx_ends)
                if expired_by_tx:
                    continue

                target_var = match.group(2).lower()
                cmd = match.group(1).upper()
                val = (match.group(3) or "").strip().strip(";")

                if "RESET" in cmd:
                    active_timeouts[target_var] = False
                elif val and POSITIVE_VAL_PATTERN.match(val):
                    active_timeouts[target_var] = True
                else:
                    active_timeouts[target_var] = False

            if not any(active_timeouts.values()):
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
