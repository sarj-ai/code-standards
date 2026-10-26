from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlglot import exp

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


_PATH = Path("supabase/queries/literals.sql")
_TEXT = "SELECT CAST(CAST('abc' AS pg_catalog.varchar(8)) AS pg_catalog.text) AS name;"
_JSON = (
    "CREATE TABLE IF NOT EXISTS document (metadata pg_catalog.jsonb DEFAULT ('{}'::pg_catalog.json)::pg_catalog.jsonb);"
)
_INSTANT = (
    "SELECT pg_catalog.timezone(INTERVAL '00:00', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp)) AS instant;"
)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("rule_id", "source", "expected"),
    [
        ("prefer-text-over-varchar", _TEXT, _TEXT.replace("pg_catalog.varchar(8)", "pg_catalog.text")),
        (
            "prefer-text-over-varchar",
            "SELECT ('abc'::pg_catalog.varchar(3))::pg_catalog.text AS name;",
            "SELECT ('abc'::pg_catalog.text)::pg_catalog.text AS name;",
        ),
        (
            "prefer-text-over-varchar",
            "SELECT 'é' AS symbol, CAST(CAST('abc' AS pg_catalog.varchar(8)) AS pg_catalog.text) AS name;",
            "SELECT 'é' AS symbol, CAST(CAST('abc' AS pg_catalog.text) AS pg_catalog.text) AS name;",
        ),
        ("prefer-jsonb", _JSON, _JSON.replace("::pg_catalog.json)", "::pg_catalog.jsonb)")),
        (
            "prefer-jsonb",
            _JSON.replace("metadata", '"é"'),
            _JSON.replace("metadata", '"é"').replace("::pg_catalog.json)", "::pg_catalog.jsonb)"),
        ),
        (
            "prefer-jsonb",
            _JSON.replace("'{}'", "'[]'"),
            _JSON.replace("'{}'", "'[]'").replace("::pg_catalog.json)", "::pg_catalog.jsonb)"),
        ),
        (
            "prefer-jsonb",
            "CREATE TABLE IF NOT EXISTS document (metadata pg_catalog.jsonb DEFAULT CAST(CAST('{}' AS pg_catalog.json) AS pg_catalog.jsonb));",
            "CREATE TABLE IF NOT EXISTS document (metadata pg_catalog.jsonb DEFAULT CAST(CAST('{}' AS pg_catalog.jsonb) AS pg_catalog.jsonb));",
        ),
        (
            "enforce-timestamptz",
            _INSTANT,
            "SELECT CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz) AS instant;",
        ),
        (
            "enforce-timestamptz",
            _INSTANT.replace("SELECT ", "SELECT 'é' AS symbol, "),
            "SELECT 'é' AS symbol, CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz) AS instant;",
        ),
        (
            "enforce-timestamptz",
            "SELECT CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp) AT TIME ZONE INTERVAL '00:00' AS instant;",
            "SELECT CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz) AS instant;",
        ),
        (
            "enforce-timestamptz",
            "CREATE TABLE IF NOT EXISTS events (at pg_catalog.timestamptz DEFAULT pg_catalog.timezone(INTERVAL '00:00', CAST('2024-02-29 23:59:59' AS pg_catalog.timestamp)));",
            "CREATE TABLE IF NOT EXISTS events (at pg_catalog.timestamptz DEFAULT CAST('2024-02-29 23:59:59+00' AS pg_catalog.timestamptz));",
        ),
    ],
)
def test_literal_fixes_preserve_existing_boundaries_and_converge(
    rule_id: RuleId, source: str, expected: str, eol: str
) -> None:
    original = source + eol
    expected += eol
    assert len(REGISTRY[rule_id]().check(_PATH, original)) == 1
    fixed = fix_source(_PATH, original, rule_ids=[rule_id])
    assert fixed == expected
    assert not REGISTRY[rule_id]().check(_PATH, fixed)
    assert parse_postgres(fixed)
    assert fix_source(_PATH, fixed, rule_ids=[rule_id]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        _TEXT.replace("varchar(8)", "varchar(2)"),
        _TEXT.replace("varchar(8)", "varchar(0)"),
        _TEXT.replace("varchar(8)", "varchar(10485761)"),
        _TEXT.replace("varchar(8)", "varchar(9999999999999999999999999999999999999999)"),
        _TEXT.replace("varchar(8)", "varchar(8)[]"),
        _TEXT.replace("'abc'", "value"),
        _TEXT.replace("'abc'", "'a''b'"),
        _TEXT.replace("'abc'", "E'a\\tb'"),
        _TEXT.replace("'abc'", "$$abc$$"),
        _TEXT.replace("'abc'", "'α'"),
        _TEXT.replace("pg_catalog.text", "app.text"),
        _TEXT.replace("pg_catalog.varchar", "app.varchar"),
        "SELECT CAST('abc' AS pg_catalog.varchar(8));",
        "CREATE TABLE users (name pg_catalog.varchar(8));",
    ],
)
def test_text_literals_refuse_unknown_or_changed_contracts(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=["prefer-text-over-varchar"]) == source


@pytest.mark.parametrize(
    "source",
    [
        _JSON.replace("'{}'", "'{\"a\":1}'"),
        _JSON.replace("'{}'", "value"),
        _JSON.replace("'{}'", "E'{}'"),
        _JSON.replace("pg_catalog.jsonb DEFAULT", "pg_catalog.json DEFAULT"),
        _JSON.replace("::pg_catalog.jsonb", "::pg_catalog.json"),
        _JSON.replace("::pg_catalog.jsonb", "::pg_catalog.jsonb[]"),
        _JSON.replace("::pg_catalog.json)", "::app.json)"),
        "CREATE TABLE document (metadata pg_catalog.json DEFAULT '{}'::pg_catalog.json);",
        "SELECT ('{}'::pg_catalog.json)::pg_catalog.jsonb;",
    ],
)
def test_json_literals_refuse_schema_or_document_changes(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=["prefer-jsonb"]) == source


@pytest.mark.parametrize(
    "source",
    [
        _INSTANT.replace("INTERVAL '00:00'", "'UTC'"),
        _INSTANT.replace("INTERVAL '00:00'", "INTERVAL '01:00'"),
        _INSTANT.replace("INTERVAL '00:00'", "INTERVAL '1 day'"),
        _INSTANT.replace("pg_catalog.timezone", "app.timezone"),
        _INSTANT.replace("pg_catalog.timestamp", "app.timestamp"),
        _INSTANT.replace(" AS instant", ""),
        _INSTANT.replace("2000-01-01", "2000-02-30"),
        _INSTANT.replace("00:00:00", "24:00:00"),
        _INSTANT.replace("00:00:00", "00:00:60"),
        _INSTANT.replace("pg_catalog.timestamp)", "pg_catalog.timestamp(0))"),
        _INSTANT.replace("CAST('2000-01-01", "CAST(/* explanation */ '2000-01-01"),
        "SELECT CAST(CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp) AS pg_catalog.timestamptz) AS instant;",
        "CREATE TABLE events (at pg_catalog.timestamp DEFAULT pg_catalog.timezone(INTERVAL '00:00', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp)));",
    ],
)
def test_timestamp_literals_refuse_session_authority_labels_errors_and_comments(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=["enforce-timestamptz"]) == source


@pytest.mark.parametrize(
    ("rule_id", "source", "code"),
    [
        ("prefer-text-over-varchar", _TEXT, "SARJ104"),
        ("prefer-jsonb", _JSON, "SARJ106"),
        ("enforce-timestamptz", _INSTANT, "SARJ101"),
    ],
)
def test_literal_fixes_respect_suppression_selection_generated_and_malformed_source(
    rule_id: RuleId, source: str, code: str
) -> None:
    suppressed = f"{source} -- sarj-noqa: {code}\n"
    assert fix_source(_PATH, suppressed, rule_ids=[rule_id]) == suppressed
    assert fix_source(_PATH, source, rule_ids=[]) == source
    generated = "-- generated; do not edit\n" + source
    assert fix_source(_PATH, generated, rule_ids=[rule_id]) == generated
    malformed = source.removesuffix(";") + " ("
    assert fix_source(_PATH, malformed, rule_ids=[rule_id]) == malformed


def test_literal_fixes_keep_schema_types_and_named_select_outputs() -> None:
    for source, rule_id in ((_JSON, "prefer-jsonb"), (_INSTANT, "enforce-timestamptz")):
        original = parse_postgres(source)[0]
        fixed = parse_postgres(fix_source(_PATH, source, rule_ids=[rule_id]))[0]
        assert original is not None
        assert fixed is not None
        assert [str(node.args.get("kind")) for node in original.find_all(exp.ColumnDef)] == [
            str(node.args.get("kind")) for node in fixed.find_all(exp.ColumnDef)
        ]
        assert [node.alias for node in original.find_all(exp.Alias)] == [
            node.alias for node in fixed.find_all(exp.Alias)
        ]


def test_literal_rules_combine_with_existing_ddl_and_comment_fixes() -> None:
    path = Path("supabase/migrations/001_literals.sql")
    source = (
        "-- ========\nCREATE TABLE document (\n"
        "name pg_catalog.text DEFAULT CAST(CAST('abc' AS pg_catalog.varchar(8)) AS pg_catalog.text),\n"
        "metadata pg_catalog.jsonb DEFAULT ('{}'::pg_catalog.json)::pg_catalog.jsonb,\n"
        "at pg_catalog.timestamptz DEFAULT pg_catalog.timezone(INTERVAL '00:00', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp)));\n"
    )
    fixed = fix_source(path, source)
    expected = source.replace("-- ========", "").replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS")
    expected = expected.replace("pg_catalog.varchar(8)", "pg_catalog.text")
    expected = expected.replace("::pg_catalog.json)", "::pg_catalog.jsonb)")
    expected = expected.replace(
        "pg_catalog.timezone(INTERVAL '00:00', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp))",
        "CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz)",
    )
    assert fixed == expected
    assert fix_source(path, fixed) == fixed


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        (
            "enforce-timestamptz",
            "CREATE OR REPLACE FUNCTION pg_catalog.timezone(zone interval, value timestamp) RETURNS timestamptz LANGUAGE sql IMMUTABLE AS 'SELECT ''2001-01-01 00:00:00+00''::timestamptz';\n"
            + _INSTANT,
        ),
        ("enforce-timestamptz", "SELECT patch_catalog();\n" + _INSTANT),
        ("enforce-timestamptz", "WITH changed AS (SELECT patch_catalog()) " + _INSTANT),
        ("enforce-timestamptz", _INSTANT.replace(" AS instant;", " AS instant FROM source;")),
        ("enforce-timestamptz", _INSTANT.replace("SELECT ", "SELECT patch_catalog(), ")),
        ("enforce-timestamptz", "ALTER FUNCTION pg_catalog.timezone(interval, timestamp) VOLATILE;\n" + _INSTANT),
        ("prefer-text-over-varchar", "SELECT 1;\n" + _TEXT),
        ("prefer-text-over-varchar", _TEXT.replace("SELECT ", "SELECT patch_catalog(), ")),
        ("prefer-text-over-varchar", _TEXT.replace("SELECT ", "SELECT (SELECT patch_catalog()), ")),
        ("prefer-text-over-varchar", _TEXT.replace("SELECT ", "SELECT 1 + 1 AS sum, ")),
        ("prefer-text-over-varchar", _TEXT.replace("SELECT ", "SELECT DISTINCT ")),
        ("prefer-text-over-varchar", _TEXT.replace("SELECT ", "SELECT other::app.domain, ")),
        ("prefer-text-over-varchar", _TEXT.replace("CAST('abc'", "TRY_CAST('abc'")),
        ("prefer-jsonb", _JSON.replace("metadata pg_catalog.jsonb", "other app.domain, metadata pg_catalog.jsonb")),
        (
            "prefer-jsonb",
            _JSON.replace(
                "metadata pg_catalog.jsonb", "other pg_catalog.text DEFAULT patch_catalog(), metadata pg_catalog.jsonb"
            ),
        ),
        (
            "prefer-jsonb",
            _JSON.replace("metadata pg_catalog.jsonb DEFAULT", "metadata pg_catalog.jsonb NOT NULL DEFAULT"),
        ),
        ("prefer-jsonb", _JSON.removesuffix(");") + ", CHECK (patch_catalog()));"),
        ("prefer-jsonb", _JSON.replace("metadata pg_catalog.jsonb", "other INTEGER, metadata pg_catalog.jsonb")),
    ],
)
def test_literal_fixes_refuse_source_visible_catalog_mutation_and_callouts(rule_id: RuleId, source: str) -> None:
    assert REGISTRY[rule_id]().check(_PATH, source)
    assert fix_source(_PATH, source, rule_ids=[rule_id]) == source
