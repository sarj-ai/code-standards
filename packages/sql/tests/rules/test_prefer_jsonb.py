from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = PreferJsonb.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return PreferJsonb().check(Path("supabase/migrations/001.sql"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = PreferJsonb().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_json_column_type():
    src = "CREATE TABLE IF NOT EXISTS call (metadata JSON NOT NULL);"
    diags = _check(src)
    assert len(diags) == 1
    assert "JSONB" in diags[0].message


def test_flags_non_b_json_cast_default():
    src = "ALTER TABLE call ADD COLUMN IF NOT EXISTS meta JSONB DEFAULT '{}'::json;"
    assert len(_check(src)) == 1


def test_is_case_insensitive():
    src = "CREATE TABLE document (metadata Json not null);"
    assert len(_check(src)) == 1


def test_allows_jsonb_column_and_cast():
    src = """
CREATE TABLE IF NOT EXISTS call (
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""
    assert _check(src) == []


def test_allows_json_prefixed_identifiers():
    src = "SELECT json_build_object('a', 1), row_to_json(t) FROM t"
    assert _check(src) == []


def test_skips_comment_lines():
    src = """
-- JSON columns are forbidden; use JSONB
/* DEFAULT '{}'::json is also forbidden */
"""
    assert _check(src) == []


def test_skips_json_word_inside_string_literal():
    src = """INSERT INTO doc (body) VALUES ('{"kind":"json"}');"""
    assert _check(src) == []


def test_skips_json_word_in_string_comment_clause():
    src = "COMMENT ON COLUMN t.meta IS 'stored as JSON text';"
    assert _check(src) == []


def test_sqlite_json_function_is_not_mistaken_for_a_postgres_type() -> None:
    source = "UPDATE schema SET json_schema = json(json_schema);"
    assert _check(source) == []


def test_sqlite_json_column_does_not_receive_jsonb_advice() -> None:
    source = "-- dialect: sqlite\nCREATE TABLE document (metadata JSON NOT NULL);"
    assert _check(source) == []


def test_ambiguous_json_column_without_postgres_evidence_stays_silent() -> None:
    source = "CREATE TABLE document (metadata JSON NOT NULL);"
    assert PreferJsonb().check(Path("db/init.sql"), source) == []


def test_flags_alter_column_json_type() -> None:
    source = "ALTER TABLE document ALTER COLUMN metadata TYPE JSON;"
    assert len(_check(source)) == 1


def test_flags_add_column_json_type() -> None:
    source = "ALTER TABLE document ADD COLUMN metadata JSON;"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "UPDATE external_config SET data = jsonb_set(data::jsonb, '{host}', '\"x\"')::json;",
        "INSERT INTO external_config (data) VALUES ('{}'::json);",
        "SELECT payload::json FROM external_config;",
    ],
)
def test_query_casts_may_target_external_or_legacy_json_columns(source: str) -> None:
    assert _check(source) == []


def test_reports_each_json_column_type() -> None:
    source = "CREATE TABLE document (metadata JSON, settings JSON);"

    assert [finding.col for finding in _check(source)] == [33, 48]
