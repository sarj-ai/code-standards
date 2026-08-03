"""SARJ110: Require lock_timeout or statement_timeout before migration DDL."""

from __future__ import annotations

import operator
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, is_postgres, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


DDL_PATTERN = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.IGNORECASE)
TX_END_PATTERN = re.compile(r"\b(COMMIT|ROLLBACK)\b", re.IGNORECASE)

# Match SET/RESET/set_config assignments for lock_timeout or statement_timeout.
ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:SET\s+(?:(?:LOCAL|SESSION)\s+)?|RESET\s+)(lock_timeout|statement_timeout)\b(?:\s*(?:=|\bTO\b)\s*('[\s\S]*?'|\"[^\"]*\"|[^\s;]+))?|set_config\s*\(\s*'?(lock_timeout|statement_timeout)'?\s*,\s*('[\s\S]*?'|\"[^\"]*\"|[^\s,;]+)",
    re.IGNORECASE,
)
POSITIVE_VAL_PATTERN = re.compile(
    r"^['\"]?\s*(?:[0-9]*\.?[0-9]+\s*(?:[a-zA-Z]+\s*)?|[1-9]\d*)\s*['\"]?$", re.IGNORECASE
)


@final
class RequireLockTimeout(Rule):
    """DDL migration missing statement or lock timeout setting prior to DDL."""

    id = "require-lock-timeout"
    code = "SARJ110"
    description = "DDL migration missing positive SET [LOCAL] lock_timeout or statement_timeout prior to DDL."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql(source)
        if not is_postgres(source):
            return []

        events: list[tuple[int, str, re.Match[str]]] = []
        # Match raw quoted values, then require the assignment's offset to remain live after masking SQL noise.
        for match in ASSIGNMENT_PATTERN.finditer(source):
            start_pos = match.start()
            if masked[start_pos : start_pos + 3].strip():
                events.append((start_pos, "ASSIGNMENT", match))
        events.extend((match.start(), "TX_END", match) for match in TX_END_PATTERN.finditer(masked))
        events.extend((match.start(), "DDL", match) for match in DDL_PATTERN.finditer(masked))

        events.sort(key=operator.itemgetter(0))

        active_global_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        active_local_timeouts: dict[str, bool] = {"lock_timeout": False, "statement_timeout": False}
        # Report once per contiguous run of DDL under one timeout state, re-arming on state-changing events.
        reported_for_current_state = False

        for pos, event_type, match in events:
            if event_type != "DDL":
                reported_for_current_state = False
            if event_type == "ASSIGNMENT":
                cmd = match.group(0).upper()
                is_local = "LOCAL" in cmd
                target_var = (match.group(1) or match.group(3) or "").lower()
                val = (match.group(2) or match.group(4) or "").strip().strip(";")

                is_active = (
                    False
                    if "RESET" in cmd
                    else (
                        bool(val)
                        and POSITIVE_VAL_PATTERN.match(val) is not None
                        and val not in {"0", "'0'", "'0s'", "'0ms'"}
                    )
                )

                if is_local:
                    active_local_timeouts[target_var] = is_active
                else:
                    active_global_timeouts[target_var] = is_active
            elif event_type == "TX_END":
                active_local_timeouts = {"lock_timeout": False, "statement_timeout": False}
            elif event_type == "DDL":
                has_timeout = any(active_global_timeouts.values()) or any(active_local_timeouts.values())
                if not has_timeout and not reported_for_current_state:
                    reported_for_current_state = True
                    lineno = masked[:pos].count("\n") + 1
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
