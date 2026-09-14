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
def test_flags_closed_text_value_check(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ118"


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
