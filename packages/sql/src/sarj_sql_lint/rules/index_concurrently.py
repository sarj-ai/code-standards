"""SARJ108: `CREATE INDEX` must use `CONCURRENTLY`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import Diagnostic, Rule, is_dump_file, is_postgres, mask_sql


if TYPE_CHECKING:
    from pathlib import Path


# `CONCURRENTLY` must come right after `INDEX` (before any `IF NOT EXISTS`).
PATTERN = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?>\s+)(?!CONCURRENTLY\b)",
    re.IGNORECASE,
)

# Match table-name patterns against raw source to preserve quoted identifiers, gating on live code in masked text.

# Search for target table forward from CREATE INDEX up to statement semicolon boundary.
_ON_TABLE_RE = re.compile(r"\bON\s+(?:ONLY\s+)?([A-Za-z0-9_.\"]+)", re.IGNORECASE)

_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)",
    re.IGNORECASE,
)


def _base_name(raw: str) -> str:
    """Reduce a possibly schema-qualified, possibly quoted table name to a bare key."""
    return raw.replace('"', "").rsplit(".", 1)[-1].lower()


@final
class IndexConcurrently(Rule):
    """CREATE INDEX without CONCURRENTLY — blocks writes for the whole build."""

    id = "index-concurrently"
    code = "SARJ108"
    description = "CREATE INDEX without CONCURRENTLY — locks the table against writes."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        masked = mask_sql(source)
        if not is_postgres(source):
            return []

        created: dict[str, int] = {}
        for match in _CREATE_TABLE_RE.finditer(source):
            if _is_live(masked, match.start()):
                created.setdefault(_base_name(match.group(1)), match.start())

        diags: list[Diagnostic] = []
        for match in PATTERN.finditer(masked):
            pos = match.start()
            target = _target_table(source, masked, match.end())
            if target is not None:
                created_at = created.get(target)
                if created_at is not None and created_at < pos:
                    continue
            line_start = masked.rfind("\n", 0, pos) + 1
            diags.append(
                Diagnostic(
                    path=path,
                    line=masked.count("\n", 0, pos) + 1,
                    col=pos - line_start + 1,
                    code=self.code,
                    message=(
                        "Use `CREATE INDEX CONCURRENTLY` — a plain CREATE INDEX "
                        "locks the table against writes for the whole build."
                    ),
                )
            )
        return diags


def _is_live(masked: str, pos: int) -> bool:
    """Report whether offset `pos` is real SQL rather than a masked comment or literal."""
    return pos < len(masked) and not masked[pos].isspace()


def _target_table(source: str, masked: str, start: int) -> str | None:
    """Name the table an index built from `start` is created on."""
    end = masked.find(";", start)
    stmt_end = len(masked) if end == -1 else end
    match = _ON_TABLE_RE.search(source, start, stmt_end)
    if match is None or not _is_live(masked, match.start()):
        return None
    return _base_name(match.group(1))
