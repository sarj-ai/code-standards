from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return EnforceTimestamptz().check(Path("supabase/migrations/001.sql"), source)


def test_authored_examples_verify_fixes_and_convergence() -> None:
    def fix(_root: Path, path: Path, source: str) -> str:
        return fix_source(path, source, rule_ids=(EnforceTimestamptz.id,))

    documentation = EnforceTimestamptz.documentation
    assert documentation is not None
    assert verify_native_rule(EnforceTimestamptz, analyze, fix=fix) == len(documentation.examples)


def test_flags_naive_timestamp():
    src = """
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL
);
"""
    assert len(_check(src)) == 1


def test_flags_explicit_timestamp_without_time_zone():
    source = "CREATE TABLE event (created_at TIMESTAMP WITHOUT TIME ZONE);"
    assert len(_check(source)) == 1


def test_allows_timestamp_with_time_zone():
    src = """
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE events (created_at TIMESTAMP\n WITH TIME ZONE);",
        "CREATE TABLE events (created_at TIMESTAMP\n (3) WITH\n TIME ZONE);",
        "CREATE TABLE events (created_at TIMESTAMP /* precision */\n WITH TIME ZONE);",
        "SELECT date_trunc('day', created_at) FROM events GROUP BY (\n timestamp\n );",
    ],
)
def test_multiline_zoned_type_and_column_reference_are_preserved(source: str) -> None:
    assert _check(source) == []


def test_multiline_naive_type_reports_its_keyword_location() -> None:
    source = "CREATE TABLE events (\n    created_at TIMESTAMP\n WITHOUT TIME ZONE);"
    assert [(item.line, item.col) for item in _check(source)] == [(2, 16)]


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
    diags = _check("CREATE TABLE t (created_at TIMESTAMP, id INT);")
    assert len(diags) == 1


def test_flags_timestamp_column_definition_ending_the_column_list():
    assert len(_check("CREATE TABLE t (created_at TIMESTAMP)")) == 1


def test_flags_timestamp_as_the_first_column_definition():
    assert len(_check("CREATE TABLE t (created_at TIMESTAMP NOT NULL, id INT)")) == 1


def test_flags_alter_column_type_change_to_naive_timestamp():
    assert len(_check("ALTER TABLE t ALTER COLUMN created_at TYPE TIMESTAMP;")) == 1


def test_reports_each_naive_timestamp_column() -> None:
    source = "CREATE TABLE event (created_at TIMESTAMP, updated_at TIMESTAMP);"

    assert [finding.col for finding in _check(source)] == [32, 54]


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_non_postgres_timestamp_types_do_not_receive_postgres_advice(dialect: str) -> None:
    source = f"-- dialect: {dialect}\nCREATE TABLE event (created_at TIMESTAMP);"
    assert _check(source) == []


def test_ambiguous_timestamp_without_postgres_evidence_stays_silent() -> None:
    source = "CREATE TABLE event (created_at TIMESTAMP);"
    assert EnforceTimestamptz().check(Path("db/init.sql"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "SELECT timestamp FROM events;",
        "SELECT events.timestamp FROM events ORDER BY timestamp;",
        "CREATE TABLE events(timestamp text);",
        "SELECT created_at AS timestamp FROM events;",
        "SELECT count(timestamp) FROM events;",
    ],
)
def test_timestamp_identifier_is_not_a_type_declaration(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE timestamp(created_at TIMESTAMP);",
        "SELECT timestamp::TIMESTAMP FROM events;",
        "SELECT CAST(timestamp AS TIMESTAMP) FROM events;",
        "SELECT TIMESTAMP '2020-01-01';",
    ],
)
def test_timestamp_identifier_does_not_hide_a_real_naive_type(source: str) -> None:
    assert len(_check(source)) == 1


def test_unsupported_syntax_retains_detection_without_logging_source(caplog: pytest.LogCaptureFixture) -> None:
    findings = _check("CREATE AGGREGATE earliest (timestamptz) (SFUNC = earlier, STYPE = TIMESTAMP);")
    assert len(findings) == 1
    assert not caplog.records


@pytest.mark.parametrize(
    "datatype",
    ['"timestamp"', "pg_catalog.timestamp", '"pg_catalog"."timestamp"', 'pg_catalog."timestamp"'],
)
def test_quoted_and_catalog_qualified_builtin_types_still_require_a_zone(datatype: str) -> None:
    source = f"CREATE TABLE events (created_at {datatype});"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("datatype", ["custom.timestamp", 'custom."timestamp"', '"TIMESTAMP"'])
def test_custom_schema_and_quoted_case_sensitive_types_are_not_inferred(datatype: str) -> None:
    source = f"CREATE TABLE events (created_at {datatype});"
    assert _check(source) == []


def test_quoted_column_name_does_not_hide_a_naive_builtin_type() -> None:
    assert len(_check('CREATE TABLE events ("timestamp" TIMESTAMP);')) == 1
