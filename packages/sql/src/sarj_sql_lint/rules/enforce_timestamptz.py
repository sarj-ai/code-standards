r"""SARJ101: detect TIMESTAMP columns missing `WITH TIME ZONE`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


# Match TIMESTAMP unless followed by WITH TIME ZONE, allowing an optional (n) precision modifier.
PATTERN = re.compile(
    r"\bTIMESTAMP\b(?!\s*(?:\(\s*\d+\s*\)\s*)?WITH\s+TIME\s+ZONE\b)",
    re.IGNORECASE,
)

_OPENS_LIST_ITEM = frozenset("(,")
_CLOSES_LIST_ITEM = frozenset(",)")


def _is_column_reference(line: str, start: int, end: int) -> bool:
    """Report whether the `TIMESTAMP` token at `[start:end)` is a bare list element."""
    before = line[:start].rstrip()
    after = line[end:].lstrip()
    return bool(before) and before[-1] in _OPENS_LIST_ITEM and bool(after) and after[0] in _CLOSES_LIST_ITEM


@final
class EnforceTimestamptz(Rule):
    """Postgres TIMESTAMP without WITH TIME ZONE — use TIMESTAMPTZ."""

    id = "enforce-timestamptz"
    code = "SARJ101"
    description = "TIMESTAMP without TIME ZONE — use TIMESTAMPTZ."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=start + 1,
                    code=self.code,
                    message=(
                        "Use `TIMESTAMPTZ` (or `TIMESTAMP WITH TIME ZONE`) — "
                        "naive TIMESTAMP discards offset and is rarely correct."
                    ),
                )
                for match in PATTERN.finditer(line)
                if not _is_column_reference(line, start := match.start(), match.end())
            )
        return redirect_to_model(diags, model_owned=model_owned)
