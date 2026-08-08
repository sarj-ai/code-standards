"""SARJ111: Enforce NOT VALID on ADD CONSTRAINT (CHECK/FK) in table alterations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_postgres_migration,
    locate,
    mask_sql,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


ALTER_ADD_VALIDATING_CONSTRAINT = re.compile(
    r"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>[a-zA-Z0-9_\"\.-]+)\s+"
    r"ADD\s+(?:CONSTRAINT\s+[a-zA-Z0-9_\"\.-]+\s+)?(?:CHECK|FOREIGN\s+KEY)\b",
    re.IGNORECASE,
)
CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>[a-zA-Z0-9_\"\.-]+)",
    re.IGNORECASE,
)
NOT_VALID_PATTERN = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)


def _table_key(raw: str) -> str:
    """Normalize an unambiguous qualified identifier for same-file comparison."""
    return ".".join(part.strip('"').lower() for part in raw.split("."))


@final
class AddConstraintNotValid(Rule):
    """ADD CONSTRAINT (CHECK / FK) on existing table missing NOT VALID."""

    id = "add-constraint-not-valid"
    code = "SARJ111"
    description = "ADD CONSTRAINT (CHECK/FK) without NOT VALID blocks writes during full-table validation."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_migration(path, source):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql(source)
        created_tables: set[str] = set()
        for statement in split_statements(masked):
            text = "\n".join(fragment for _, fragment in statement)
            created_tables.update(_table_key(created.group("table")) for created in CREATE_TABLE.finditer(text))
            for match in ALTER_ADD_VALIDATING_CONSTRAINT.finditer(text):
                if _table_key(match.group("table")) in created_tables or NOT_VALID_PATTERN.search(text) is not None:
                    continue
                location = locate(statement, match.start())
                diags.append(
                    Diagnostic(
                        path=path,
                        line=location.line,
                        col=location.column,
                        code=self.code,
                        message=(
                            "Use `ADD CONSTRAINT ... NOT VALID;` followed by a separate "
                            "`ALTER TABLE ... VALIDATE CONSTRAINT` step to prevent table locks during validation."
                        ),
                    )
                )

        return diags
