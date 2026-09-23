from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_generated_migration,
    is_postgres_source,
    locate,
    mask_sql,
    redirect_to_model,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


_CHECK_START = re.compile(r"\bCHECK\s*\(", re.IGNORECASE)
_JSON_SHAPE_FUNCTION = re.compile(r"\bJSONB?_(?:TYPEOF|ARRAY_LENGTH)\s*\(", re.IGNORECASE)
_CLOSED_TEXT_VALUES = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*\s+IN\s*\(\s+,\s+(?:,\s+)*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _application_schema_checks(source: str) -> list[int]:
    findings: list[int] = []
    for match in _CHECK_START.finditer(source):
        opening_parenthesis = match.end() - 1
        depth = 0
        for index in range(opening_parenthesis, len(source)):
            character = source[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    expression = source[opening_parenthesis + 1 : index]
                    if _JSON_SHAPE_FUNCTION.search(expression) or _CLOSED_TEXT_VALUES.fullmatch(expression):
                        findings.append(match.start())
                    break
    return findings


@final
class NoApplicationSchemaCheck(Rule):
    id = "no-application-schema-check"
    code = "SARJ118"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Keep JSON shape and closed application value sets out of database CHECK constraints.",
        rationale=(
            "A database CHECK that repeats an application-owned JSON schema or enum-like value set creates two "
            "validators that can drift and turn an otherwise valid application deployment into failed writes."
        ),
        remediation=(
            "Remove the application-schema CHECK and validate the JSON payload or closed value set with the typed "
            "application boundary before writing it. Keep relational constraints such as foreign keys, uniqueness, "
            "nullability, and cross-column invariants in the database."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only PostgreSQL CHECK expressions that call JSON_TYPEOF, JSONB_TYPEOF, JSON_ARRAY_LENGTH, or JSONB_ARRAY_LENGTH are reported.",
            "Enum-like checks are reported only for a simple column IN a list of at least two string literals.",
            "JSON operators and cross-column consistency checks are not inferred because their ownership can be ambiguous.",
            "Dump files are excluded; generated migrations redirect findings to their owning model when identifiable.",
        ),
        examples=(
            RuleExample(
                example_id="json-array-shape-check",
                title="Database duplicates a JSON array schema",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_execution_plan.sql",
                        "CREATE TABLE execution_plan (\n"
                        "    outcomes JSONB NOT NULL CHECK (\n"
                        "        JSONB_TYPEOF(outcomes) = 'array'\n"
                        "        AND JSONB_ARRAY_LENGTH(outcomes) BETWEEN 1 AND 10\n"
                        "    )\n"
                        ");\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_execution_plan.sql"),
                expected_count=1,
                public=True,
                scenario="json-shape",
            ),
            RuleExample(
                example_id="application-owned-json-shape",
                title="Application schema owns the JSON document contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_execution_plan.sql",
                        "CREATE TABLE execution_plan (\n"
                        "    call_id UUID PRIMARY KEY REFERENCES call (id),\n"
                        "    outcomes JSONB NOT NULL\n"
                        ");\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_execution_plan.sql"),
                expected_count=0,
                public=True,
                scenario="json-shape",
            ),
            RuleExample(
                example_id="closed-status-values-check",
                title="Database duplicates an application enum",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_call.sql",
                        "CREATE TABLE call (status TEXT NOT NULL CHECK (status IN ('queued', 'completed')));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_call.sql"),
                expected_count=1,
                public=True,
                scenario="closed-values",
            ),
            RuleExample(
                example_id="application-owned-status-values",
                title="Application enum owns the closed value set",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_call.sql",
                        "CREATE TABLE call (status TEXT NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_call.sql"),
                expected_count=0,
                public=True,
                scenario="closed-values",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)
        diagnostics: list[Diagnostic] = []
        for statement in split_statements(mask_sql(source)):
            text = "\n".join(fragment for _, fragment in statement)
            for offset in _application_schema_checks(text):
                line, col = locate(statement, offset)
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=self.code,
                        message=(
                            "Application schema validation belongs in the typed application boundary; remove this "
                            "JSON-shape or closed-value CHECK while retaining relational database invariants."
                        ),
                    )
                )
        return redirect_to_model(diagnostics, model_owned=model_owned)
