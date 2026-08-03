"""SARJ107: forbid `OFFSET` pagination — use cursor-based pagination."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# Match OFFSET followed by a value or parameter token across supported SQL dialects.
PATTERN = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)",
    re.IGNORECASE,
)


@final
class NoLimitOffset(Rule):
    """OFFSET pagination — use cursor pagination instead."""

    id = "no-limit-offset"
    code = "SARJ107"
    description = "OFFSET pagination — use cursor pagination (WHERE id > :cursor)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use cursor pagination (WHERE id > :cursor ORDER BY id "
                        "LIMIT n) — OFFSET scans and discards every skipped row."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return diags
