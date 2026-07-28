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
    r"\b(SET\s+LOCAL|SET|RESET)\s+(lock_timeout|statement_timeout)(?:\s*(?:=|\bTO\b)\s*([^\s;]+(?:[\s']+[^\s;]+)*))?",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(r"^['\"]?\s*(?:[0-9]*\.?[0-9]+\s*(?:[a-zA-Z]+\s*)?|[1-9]\d*)\s*['\"]?$", re.IGNORECASE)


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
                start_pos = match.start()
                if not masked[start_pos : start_pos + 3].strip():
                    continue

                is_local = "LOCAL" in match.group(1).upper()
                if is_local and any(match.start() < t < ddl_start for t in tx_ends):
                    continue

                target_var = match.group(2).lower()
                cmd = match.group(1).upper()
                val = (match.group(3) or "").strip().strip(";")

                if "RESET" in cmd:
                    active_timeouts[target_var] = False
                elif val and POSITIVE_VAL_PATTERN.match(val) and val not in {"0", "'0'", "'0s'", "'0ms'"}:
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
