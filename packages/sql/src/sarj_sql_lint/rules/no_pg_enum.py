"""SARJ103: forbid `CREATE TYPE ... AS ENUM` — use TEXT + CHECK constraint."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
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
    documentation = RuleDocumentation(
        summary="CREATE TYPE ... AS ENUM — use TEXT + CHECK constraint instead.",
        rationale=(
            "PostgreSQL enums make ordinary value changes operationally awkward and couple application evolution to "
            "database type migrations."
        ),
        remediation="Store the value as TEXT and constrain the allowed values with an explicit CHECK expression.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "PostgreSQL dump files are excluded.",
            "Generated migrations still report, but diagnostics direct the edit to the owning schema model.",
        ),
        examples=(
            RuleExample(
                example_id="postgres-enum-type",
                title="PostgreSQL enum type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_status.sql",
                        "CREATE TYPE call_status AS ENUM ('pending', 'active', 'completed');\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_status.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="text-check-constraint",
                title="Text column with an explicit value constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_status.sql",
                        "CREATE TABLE call (\n"
                        "    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'completed'))\n"
                        ");\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_status.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

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
