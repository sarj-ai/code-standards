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
    is_postgres,
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(
    r"\b(?:VARCHAR|CHARACTER\s+VARYING)\s*\(",
    re.IGNORECASE,
)


@final
class PreferTextOverVarchar(Rule):
    id = "prefer-text-over-varchar"
    code = "SARJ104"
    documentation = RuleDocumentation(
        summary="VARCHAR(n) — use TEXT (+ CHECK length if needed).",
        rationale="PostgreSQL gives VARCHAR(n) no storage or performance advantage, while its length cap obscures a business constraint.",
        remediation="Use TEXT and express a real maximum length with an explicit CHECK constraint when needed.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=("MySQL and SQLite sources are excluded because their VARCHAR behavior differs.",),
        examples=(
            RuleExample(
                example_id="bounded-varchar-column",
                title="Length-limited VARCHAR column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql("migrations/001_users.sql", "CREATE TABLE users (name VARCHAR(255) NOT NULL);\n"),
                ),
                focus_path=PurePosixPath("migrations/001_users.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="text-with-length-check",
                title="Text column with an explicit length constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_users.sql",
                        "CREATE TABLE users (name TEXT NOT NULL CHECK (char_length(name) <= 255));\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_users.sql"),
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
        masked = mask_sql(source)
        if not is_postgres(source):
            return []

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(masked.splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use TEXT (+ CHECK length if needed) — VARCHAR(n) has "
                        "no benefit in Postgres and hides a business rule in DDL."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return redirect_to_model(diags, model_owned=model_owned)
