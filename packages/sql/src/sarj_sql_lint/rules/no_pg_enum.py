"""SARJ103: forbid `CREATE TYPE ... AS ENUM` — use TEXT + CHECK constraint."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    Diagnostic,
    Rule,
    is_dump_file,
    is_generated_migration,
    locate,
    mask_sql,
    redirect_to_model,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


# Matched at statement level (DOTALL) so a `CREATE TYPE` whose `AS ENUM` lands on
# a later line is still caught.
_CREATE_ENUM_RE = re.compile(r"\bCREATE\s+TYPE\b.*?\bAS\s+ENUM\b", re.IGNORECASE | re.DOTALL)
_ALTER_ADD_VALUE_RE = re.compile(r"\bALTER\s+TYPE\b.*?\bADD\s+VALUE\b", re.IGNORECASE | re.DOTALL)


@final
class NoPgEnum(Rule):
    """Forbid CREATE TYPE AS ENUM in favor of TEXT with CHECK constraint."""

    id = "no-pg-enum"
    code = "SARJ103"
    description = "CREATE TYPE ... AS ENUM — use TEXT + CHECK constraint instead."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        for statement in split_statements(mask_sql(source)):
            text = "\n".join(t for _, t in statement)
            for pattern in (_CREATE_ENUM_RE, _ALTER_ADD_VALUE_RE):
                match = pattern.search(text)
                if match is None:
                    continue
                line, col = locate(statement, match.start())
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=self.code,
                        message=("Use TEXT + CHECK constraint — PG enums can't be altered transactionally."),
                    )
                )
        return redirect_to_model(diags, model_owned=model_owned)
