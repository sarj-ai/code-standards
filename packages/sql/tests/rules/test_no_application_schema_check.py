from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.no_application_schema_check import NoApplicationSchemaCheck


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoApplicationSchemaCheck.public_examples()


def _check(source: str, path: Path = Path("supabase/migrations/001.sql")) -> list[Diagnostic]:
    return NoApplicationSchemaCheck().check(path, source)


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(focus.path))) == example.expected_count


@pytest.mark.parametrize("function", ["JSON_TYPEOF", "JSONB_TYPEOF", "JSON_ARRAY_LENGTH", "JSONB_ARRAY_LENGTH"])
def test_flags_json_shape_function_in_check(function: str) -> None:
    source = f"CREATE TABLE item (payload JSONB CHECK ({function}(payload) IS NOT NULL));"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ118"


def test_reports_each_json_shape_check_once() -> None:
    source = """
CREATE TABLE item (
    payload JSONB CHECK (
        JSONB_TYPEOF(payload) = 'array'
        AND JSONB_ARRAY_LENGTH(payload) > 0
    ),
    metadata JSONB CHECK (JSONB_TYPEOF(metadata) = 'object')
);
"""
    assert [finding.line for finding in _check(source)] == [3, 7]


def test_does_not_associate_function_outside_check_with_earlier_check() -> None:
    source = """
CREATE TABLE item (
    quantity INTEGER CHECK (quantity > 0),
    payload JSONB,
    payload_type TEXT GENERATED ALWAYS AS (JSONB_TYPEOF(payload)) STORED
);
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE call (status TEXT CHECK (status IN ('queued', 'completed')));",
        "ALTER TABLE call ADD CONSTRAINT status_allowed CHECK (status in ('queued', 'completed', 'failed'));",
    ],
)
def test_allows_closed_text_value_check(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE item (price INTEGER CHECK (price > 0));",
        "CREATE TABLE item (payload JSONB NOT NULL);",
        "ALTER TABLE item ADD CONSTRAINT payload_matches_kind CHECK (payload ->> 'kind' = kind);",
        "CREATE TABLE item (quantity INTEGER CHECK (quantity IN (1, 2, 3)));",
        "CREATE TABLE item (kind TEXT CHECK (kind IN ('only')));",
    ],
)
def test_allows_database_owned_or_non_shape_invariants(source: str) -> None:
    assert _check(source) == []


def test_ignores_comments_and_strings() -> None:
    source = """
-- CHECK (JSONB_TYPEOF(payload) = 'object')
INSERT INTO docs (body) VALUES ('CHECK (JSONB_ARRAY_LENGTH(payload) > 0)');
"""
    assert _check(source) == []


def test_excludes_postgres_dump() -> None:
    source = "-- PostgreSQL database dump\nCREATE TABLE item (payload JSONB CHECK (JSONB_TYPEOF(payload) = 'object'));"
    assert _check(source, Path("schema.sql")) == []


def test_quoted_column_in_closed_string_set_is_detected() -> None:
    assert _check("CREATE TABLE item (\"status\" TEXT CHECK (\"status\" IN ('ready', 'done')));") == []


@pytest.mark.parametrize(
    "source",
    [
        'CREATE TABLE item ("CHECK (JSONB_TYPEOF(payload))" TEXT);',
        "CREATE TABLE item (payload JSONB CHECK (\"JSONB_TYPEOF(payload)\" = 'ok'));",
        'CREATE TABLE item ("status" TEXT CHECK ("status" IN (1, 2)));',
        'CREATE TABLE item ("a)b" TEXT CHECK (length("a)b") > 0));',
    ],
)
def test_quoted_check_and_function_decoys_are_inert(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("column", ['"status"', '"status)name"', '"state""name"'])
def test_allows_closed_values_for_a_quoted_column(column: str) -> None:
    source = f"CREATE TABLE call ({column} TEXT CHECK ({column} IN ('queued', 'completed')));"
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "SELECT \"CHECK (status IN ('queued', 'completed'))\" FROM call;",
        'CREATE TABLE item ("JSONB_TYPEOF(payload)" TEXT CHECK (quantity > 0));',
        'CREATE TABLE call (status TEXT CHECK (status IN ("queued", "completed")));',
        'CREATE TABLE item (payload JSONB CHECK ("JSONB_TYPEOF"(payload) IS NOT NULL));',
    ],
)
def test_quoted_identifiers_do_not_manufacture_schema_checks(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("separator", ["\n", "/* constraint boundary */"])
def test_check_keyword_guard_allows_comment_and_newline_trivia(separator: str) -> None:
    source = f"CREATE TABLE call (payload JSONB cHeCk{separator}(jsonb_typeof(payload) = 'object'));"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("function", ["json_typeof", "jsonb_typeof", "json_array_length", "jsonb_array_length"])
def test_quoted_lowercase_json_function_has_the_same_schema_contract(function: str) -> None:
    source = f'CREATE TABLE item (payload JSONB CHECK ("{function}"(payload) IS NOT NULL));'
    assert len(_check(source)) == 1


def test_dollar_identifier_suffix_does_not_become_a_native_json_function() -> None:
    assert _check("CREATE TABLE event (payload jsonb CHECK (custom$jsonb_typeof(payload) = 'array'));") == []


@pytest.mark.parametrize("prefix", ["α", "café", "a\u0301", "😀", "custom$"])
def test_custom_unicode_function_is_not_a_native_json_shape_check(prefix: str) -> None:
    source = f"CREATE TABLE entries (payload JSONB CHECK ({prefix}jsonb_typeof(payload) = 'array'));"
    assert NoApplicationSchemaCheck().check(Path("migrations/001_entries.sql"), source) == []


@pytest.mark.parametrize("name", ["j\u017fonb_typeof", "jsonb_typeof\u00a0"])
def test_unicode_function_names_do_not_prove_native_json_checks(name: str) -> None:
    source = f"CREATE TABLE entries (payload jsonb CHECK ({name}(payload) = 'array'));"
    assert _check(source) == []


@pytest.mark.parametrize("name", ["😀check", "custom$check", "chec\u212a", "check\u00a0"])
def test_custom_check_function_does_not_become_a_constraint(name: str) -> None:
    source = f"SELECT {name}(jsonb_typeof('{{}}'::jsonb));"
    assert _check(source) == []
