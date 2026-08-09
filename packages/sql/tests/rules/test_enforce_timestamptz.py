from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return EnforceTimestamptz().check(Path("supabase/migrations/001.sql"), source)


_PUBLIC_EXAMPLES = EnforceTimestamptz.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(EnforceTimestamptz().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_naive_timestamp():
    src = """
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL
);
"""
    assert len(_check(src)) == 1


def test_allows_timestamp_with_time_zone():
    src = """
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
"""
    assert _check(src) == []


def test_allows_timestamptz_keyword():
    src = """
CREATE TABLE orders (
    created_at TIMESTAMPTZ NOT NULL
);
"""
    assert _check(src) == []


def test_allows_timestamp_with_precision_and_time_zone():
    src = "created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL"
    assert _check(src) == []


def test_flags_timestamp_with_precision_but_no_time_zone():
    src = "created_at TIMESTAMP(6) NOT NULL"
    assert len(_check(src)) == 1


def test_skips_comment_lines():
    src = """
-- TIMESTAMP without WITH TIME ZONE is forbidden in our docs comments
CREATE TABLE x (created_at TIMESTAMPTZ);
"""
    assert _check(src) == []


def test_skips_trailing_inline_comment():
    src = "created_at TIMESTAMPTZ NOT NULL -- TIMESTAMP was the old type"
    assert _check(src) == []


def test_skips_string_literal_body():
    src = "INSERT INTO log (kind) VALUES ('TIMESTAMP');"
    assert _check(src) == []


def test_skips_block_comment_body():
    src = """
/*
  legacy column was TIMESTAMP without zone
*/
CREATE TABLE x (created_at TIMESTAMPTZ);
"""
    assert _check(src) == []


def test_allows_timestamp_as_a_bare_column_reference_in_a_grouping_key():
    assert _check("PARTITION BY toYYYYMM(timestamp)") == []


def test_allows_timestamp_in_a_column_list():
    assert _check("ORDER BY (org_id, timestamp, api_key_id)") == []


def test_allows_timestamp_in_a_cte_column_list():
    assert _check("WITH states (TYPE, name, timestamp, state_details) AS (SELECT 1)") == []


def test_flags_timestamp_column_definition_ending_in_a_comma():
    """The boundary: the char before the keyword is part of the column name."""
    diags = _check("CREATE TABLE t (created_at TIMESTAMP, id INT);")
    assert len(diags) == 1


def test_flags_timestamp_column_definition_ending_the_column_list():
    """The boundary: `)` on the right alone must not trigger the guard."""
    assert len(_check("CREATE TABLE t (created_at TIMESTAMP)")) == 1


def test_flags_timestamp_as_the_first_column_definition():
    """The boundary: `(` on the left alone must not trigger the guard."""
    assert len(_check("CREATE TABLE t (created_at TIMESTAMP NOT NULL, id INT)")) == 1


def test_flags_alter_column_type_change_to_naive_timestamp():
    assert len(_check("ALTER TABLE t ALTER COLUMN created_at TYPE TIMESTAMP;")) == 1


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_non_postgres_timestamp_types_do_not_receive_postgres_advice(dialect: str) -> None:
    source = f"-- dialect: {dialect}\nCREATE TABLE event (created_at TIMESTAMP);"
    assert _check(source) == []


def test_ambiguous_timestamp_without_postgres_evidence_stays_silent() -> None:
    source = "CREATE TABLE event (created_at TIMESTAMP);"
    assert EnforceTimestamptz().check(Path("db/init.sql"), source) == []
