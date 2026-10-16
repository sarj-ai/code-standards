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
    mask_sql,
    redirect_to_model,
    source_location,
)


if TYPE_CHECKING:
    from pathlib import Path


_CREATE_FUNCTION = re.compile(r"(?<![\w$])(?P<ddl>CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION)\b", re.IGNORECASE)


@final
class NoDatabaseFunctions(Rule):
    id = "no-database-functions"
    code = "SARJ120"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Prefer explicit application behavior to stored SQL functions.",
        rationale="Under a single-writer application architecture, stored functions can obscure application behavior. Database-owned invariants and expression indexes may still require approved stored functions.",
        remediation="Prefer declarative constraints or explicit transactional application behavior where equivalent. Preserve transaction atomicity and database-enforced integrity; use an exact SARJ120 suppression for an approved database-owned invariant or compatibility exception.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports PostgreSQL CREATE FUNCTION and CREATE OR REPLACE FUNCTION, including temporary-schema functions. Calls to built-in or existing functions and DROP FUNCTION remain valid.",
            "This is an organization-specific architecture policy. Comments, quoted values (including scalar and nested dollar-quoted strings), dumps, and non-PostgreSQL dialects are excluded. Executable DO and routine bodies remain visible.",
            "Generated migrations report against their owning model when one can be identified. Triggers are covered separately by SARJ114.",
            "Dynamically generated DDL inside procedural bodies is not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="stored-fault-function",
                title="Procedural database fault fixture",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001.sql",
                        "CREATE FUNCTION fail_counter() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'failure'; END $$;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declarative-fault",
                title="Declarative constraint in a disposable test database",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001.sql",
                        "ALTER TABLE batch ADD CONSTRAINT fail_counter CHECK (false) NOT VALID;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="anonymous-block-function",
                title="An executable anonymous block still creates a stored function",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_function.sql",
                        "DO $outer$ BEGIN CREATE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$; END $outer$;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_function.sql"),
                expected_count=1,
                public=True,
                scenario="executable-sql",
            ),
            RuleExample(
                example_id="scalar-function-text",
                title="Function DDL stored as scalar data does not execute",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_function.sql",
                        "SELECT $outer$CREATE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$;$outer$;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_function.sql"),
                expected_count=0,
                public=True,
                scenario="executable-sql",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        diagnostics: list[Diagnostic] = []
        for match in _CREATE_FUNCTION.finditer(mask_sql(source, mask_dollar_literals=True)):
            location = source_location(source, match.start("ddl"))
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message="Project architecture prefers declarative constraints or explicit transactional application behavior. Preserve atomicity and database-enforced integrity; use an exact SARJ120 suppression for an approved database-owned invariant or compatibility exception.",
                )
            )
        return redirect_to_model(diagnostics, model_owned=is_generated_migration(path, source))
