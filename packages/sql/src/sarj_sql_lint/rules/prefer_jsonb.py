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
    is_postgres_source,
    locate,
    mask_sql_literals_and_comments,
    redirect_to_model,
    split_statements,
    sql_code_matches,
)


if TYPE_CHECKING:
    from pathlib import Path


_IDENT = r'(?:[A-Za-z_][\w$]*|"(?:""|[^"])+")'
_TYPE_FOLLOW = r"(?:\s*\[\s*\])*(?=\s*(?:,|\)|;|$|NOT\b|NULL\b|DEFAULT\b|CHECK\b|COLLATE\b|CONSTRAINT\b|GENERATED\b|REFERENCES\b|PRIMARY\b|UNIQUE\b|USING\b))"
_JSON_TYPE = r'(?P<json>(?:(?:pg_catalog|(?-i:"pg_catalog"))\s*\.\s*)?(?:JSON\b|(?-i:"json")))'
_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\b", re.IGNORECASE)
_ALTER_TABLE_RE = re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE)
_TABLE_JSON_RE = re.compile(rf"(?:\(|,)\s*{_IDENT}\s+{_JSON_TYPE}{_TYPE_FOLLOW}", re.IGNORECASE)
_ALTER_JSON_RE = re.compile(
    rf"\b(?:ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}|ALTER\s+(?:COLUMN\s+)?{_IDENT}\s+TYPE)\s+"
    rf"{_JSON_TYPE}{_TYPE_FOLLOW}",
    re.IGNORECASE,
)
_JSON_CAST_RE = re.compile(rf"::\s*{_JSON_TYPE}", re.IGNORECASE)


@final
class PreferJsonb(Rule):
    id = "prefer-jsonb"
    code = "SARJ106"
    documentation = RuleDocumentation(
        summary="JSON column type or table-DDL cast — use JSONB.",
        rationale=(
            "JSONB supports indexing and containment operators and avoids reparsing the stored document on every read."
        ),
        remediation="Declare JSONB columns and use jsonb casts for JSON document values.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "PostgreSQL dump files are excluded.",
            "JSON tokens inside comments, string literals, and longer identifiers are ignored.",
            "Column declarations include optional COLUMN keywords, JSON arrays, and exact quoted or pg_catalog-qualified built-ins. Case-sensitive quoted custom types and other schemas remain excluded.",
            "Query and data-migration casts are excluded because an external or legacy JSON column may require them.",
        ),
        examples=(
            RuleExample(
                example_id="alter-json-type-with-using",
                title="An ALTER USING conversion still declares a plain JSON type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_boundary.sql",
                        "ALTER TABLE document ALTER COLUMN metadata TYPE json USING metadata::json;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_boundary.sql"),
                expected_count=2,
                public=True,
                scenario="semantic-boundary",
            ),
            RuleExample(
                example_id="alter-jsonb-type-with-using",
                title="The target type and conversion both use JSONB",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_boundary.sql",
                        "ALTER TABLE document ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_boundary.sql"),
                expected_count=0,
                public=True,
                scenario="semantic-boundary",
            ),
            RuleExample(
                example_id="json-column",
                title="Plain JSON column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_documents.sql",
                        "CREATE TABLE document (metadata JSON NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_documents.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="jsonb-column",
                title="Indexable JSONB column",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_documents.sql",
                        "CREATE TABLE document (metadata JSONB NOT NULL DEFAULT '{}'::jsonb);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_documents.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)

        diags: list[Diagnostic] = []
        for statement in split_statements(mask_sql_literals_and_comments(source, mask_dollar_literals=True)):
            text = "\n".join(fragment for _, fragment in statement)
            for position in _json_type_positions(text):
                line, col = locate(statement, position)
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=self.code,
                        message=(
                            "Use JSONB — plain JSON has no indexing or containment operators and re-parses on every read."
                        ),
                    )
                )
        return redirect_to_model(diags, model_owned=model_owned)


def _json_type_positions(text: str) -> list[int]:
    create_table = next(sql_code_matches(_CREATE_TABLE_RE, text), None) is not None
    alter_table = next(sql_code_matches(_ALTER_TABLE_RE, text), None) is not None
    patterns = [_ALTER_JSON_RE] if alter_table else []
    if create_table:
        patterns.append(_TABLE_JSON_RE)
    if create_table or alter_table:
        patterns.append(_JSON_CAST_RE)
    return sorted(
        {match.start("json") for pattern in patterns for match in sql_code_matches(pattern, text, group="json")}
    )
