from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_CONTINUATION,
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
    mask_sql_literals_and_comments,
    redirect_to_model,
    split_statements,
    sql_code_matches,
)


if TYPE_CHECKING:
    from pathlib import Path


_CHECK_START = re.compile(rf"(?<!{POSTGRES_IDENTIFIER_CONTINUATION})(?ai:CHECK)[ \t\r\n\f\v]*\(")
_JSON_SHAPE_FUNCTION = re.compile(
    rf'(?<!{POSTGRES_IDENTIFIER_CONTINUATION})(?:(?ai:JSONB?_(?:TYPEOF|ARRAY_LENGTH))\b|(?-i:"jsonb?_(?:typeof|array_length)"))[ \t\r\n\f\v]*\(',
    re.IGNORECASE,
)


def _application_schema_checks(source: str) -> list[int]:
    if _CHECK_START.search(source) is None:
        return []
    findings: list[int] = []
    code = mask_sql(source, mask_dollar_literals=True) if '"' in source else source
    for match in sql_code_matches(_CHECK_START, source):
        opening_parenthesis = match.end() - 1
        depth = 0
        for index in range(opening_parenthesis, len(source)):
            character = code[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    expression = source[opening_parenthesis + 1 : index]
                    if next(sql_code_matches(_JSON_SHAPE_FUNCTION, expression), None):
                        findings.append(match.start())
                    break
    return findings


@final
class NoApplicationSchemaCheck(Rule):
    id = "no-application-schema-check"
    code = "SARJ118"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Review JSON shape validation duplicated in database CHECK constraints.",
        rationale=(
            "A database CHECK that repeats an application-owned JSON schema creates two "
            "validators that can drift and turn an otherwise valid application deployment into failed writes."
        ),
        remediation=(
            "If the application owns the contract, validate the JSON payload with the typed "
            "application boundary before changing its CHECK. Preserve database-owned validation and checks needed by other writers; use an exact SARJ118 suppression explaining ownership. Keep relational constraints such as foreign keys, uniqueness, "
            "nullability, and cross-column invariants in the database."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only PostgreSQL CHECK expressions that call JSON_TYPEOF, JSONB_TYPEOF, JSON_ARRAY_LENGTH, or JSONB_ARRAY_LENGTH are reported.",
            "Closed status value sets and numeric/interval bounds are allowed as database integrity constraints.",
            "JSON operators alone are not matched. Function calls inside cross-column or mixed checks can match; application ownership is not proven and removal requires review of every writer.",
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
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "check" not in source.casefold() or is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)
        diagnostics: list[Diagnostic] = []
        for statement in split_statements(mask_sql_literals_and_comments(source, mask_dollar_literals=True)):
            text = "\n".join(fragment for _, fragment in statement)
            for offset in _application_schema_checks(text):
                line, col = locate(statement, offset)
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=self.code,
                        severity=DefaultLevel.WARNING,
                        message=(
                            "Review ownership of this "
                            "JSON-shape CHECK. Move application-owned validation to a typed boundary; retain database invariants and document their ownership."
                        ),
                    )
                )
        return redirect_to_model(diagnostics, model_owned=model_owned)
