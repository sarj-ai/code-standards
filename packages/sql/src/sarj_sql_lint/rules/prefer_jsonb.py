"""SARJ106: prefer JSONB for PostgreSQL table storage."""

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
    mask_sql,
    redirect_to_model,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


_IDENT = r'(?:[A-Za-z_][\w$]*|"(?:""|[^"])+")'
_TYPE_FOLLOW = r"(?=\s*(?:,|\)|;|$|NOT\b|NULL\b|DEFAULT\b|CHECK\b|COLLATE\b|CONSTRAINT\b|GENERATED\b|REFERENCES\b|PRIMARY\b|UNIQUE\b))"
_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\b", re.IGNORECASE)
_ALTER_TABLE_RE = re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE)
_TABLE_JSON_RE = re.compile(rf"(?:\(|,)\s*{_IDENT}\s+(?P<json>JSON)\b{_TYPE_FOLLOW}", re.IGNORECASE)
_ALTER_JSON_RE = re.compile(
    rf"\b(?:ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+{_IDENT}|ALTER\s+COLUMN\s+{_IDENT}\s+TYPE)\s+"
    rf"(?P<json>JSON)\b{_TYPE_FOLLOW}",
    re.IGNORECASE,
)
_JSON_CAST_RE = re.compile(r"::\s*(?P<json>JSON)\b", re.IGNORECASE)


@final
class PreferJsonb(Rule):
    """JSON column type or table-DDL cast — use JSONB."""

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
            "Query and data-migration casts are excluded because an external or legacy JSON column may require them.",
        ),
        examples=(
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
        for statement in split_statements(mask_sql(source)):
            text = "\n".join(fragment for _, fragment in statement)
            create_table = _CREATE_TABLE_RE.search(text) is not None
            alter_table = _ALTER_TABLE_RE.search(text) is not None
            patterns = [_ALTER_JSON_RE]
            if create_table:
                patterns.append(_TABLE_JSON_RE)
            if create_table or alter_table:
                patterns.append(_JSON_CAST_RE)
            seen: set[int] = set()
            for pattern in patterns:
                for match in pattern.finditer(text):
                    position = match.start("json")
                    if position in seen:
                        continue
                    seen.add(position)
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
