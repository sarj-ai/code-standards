"""SARJ106: forbid the non-B `JSON` type and `::json` casts — use JSONB."""

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
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


# \b...\b does not match JSONB (B is a word char) nor json_* identifiers
# (underscore is a word char), but catches both `JSON` column types and
# `::json` casts such as `DEFAULT '{}'::json`.
PATTERN = re.compile(r"\bJSON\b", re.IGNORECASE)


@final
class PreferJsonb(Rule):
    """JSON column type or ::json cast — use JSONB."""

    id = "prefer-jsonb"
    code = "SARJ106"
    documentation = RuleDocumentation(
        summary="JSON column type or ::json cast — use JSONB.",
        rationale=(
            "JSONB supports indexing and containment operators and avoids reparsing the stored document on every read."
        ),
        remediation="Declare JSONB columns and use jsonb casts for JSON document values.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "PostgreSQL dump files are excluded.",
            "JSON tokens inside comments, string literals, and longer identifiers are ignored.",
        ),
        examples=(
            RuleExample(
                example_id="json-column",
                title="Plain JSON column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_documents.sql",
                        "CREATE TABLE document (metadata JSON NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_documents.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="jsonb-column",
                title="Indexable JSONB column",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_documents.sql",
                        "CREATE TABLE document (metadata JSONB NOT NULL DEFAULT '{}'::jsonb);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_documents.sql"),
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
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use JSONB — plain JSON has no indexing or containment operators and re-parses on every read."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return redirect_to_model(diags, model_owned=model_owned)
