from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule
import sqlglot

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import DefaultLevel, Diagnostic
from sarj_sql_lint.rules._postgres_ctas import normalize_postgres_ctas
from sarj_sql_lint.rules.no_analytical_queries_in_transactional_db import NoAnalyticalQueriesInTransactionalDb


if TYPE_CHECKING:
    from sqlglot.tokenizer_core import Token


def test_documented_examples() -> None:
    verify_native_rule(NoAnalyticalQueriesInTransactionalDb, analyze)


def _check(source: str, filename: str = "queries/events.sql") -> list[Diagnostic]:
    return NoAnalyticalQueriesInTransactionalDb().check(Path(filename), source)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT DISTINCT id FROM event;",
        "SELECT DISTINCT ON (team_id) id FROM event ORDER BY team_id;",
        "SELECT team_id FROM event GROUP BY team_id;",
        "SELECT team_id FROM event GROUP/* comment */BY team_id",
        "SELECT team_id FROM event GROUP /* comment */ BY team_id",
        "SELECT team_id FROM event GROUP-- comment\r\nBY team_id",
        "SELECT team_id FROM event GROUP/* first\r\nsecond */BY team_id",
        "SELECT team_id, COUNT(*) FROM event GROUP BY team_id LIMIT 1;",
        "SELECT COUNT(*) FROM event;",
        "SELECT COUNT(DISTINCT team_id) FROM event;",
        "SELECT SUM(cost) FROM event;",
        "SELECT AVG(cost) FROM event;",
        "SELECT MIN(created_at) FROM event;",
        "SELECT MAX(created_at) FROM event;",
        "SELECT ARRAY_AGG(id) FROM event;",
        "SELECT STRING_AGG(name, ',') FROM event;",
        "SELECT JSONB_AGG(event) FROM event;",
        "SELECT JSON_AGG(NULL), JSON_AGG(NULL) FROM event;",
        "SELECT JSON_AGG(TRUE), JSON_AGG(FALSE) FROM event;",
        "SELECT JSON_AGG(NULL), JSON_AGG(TRUE), JSON_AGG(FALSE);",
        "SELECT BOOL_AND(active) FROM event;",
        "SELECT STDDEV_POP(cost) FROM event;",
        "SELECT VAR_SAMP(cost) FROM event;",
        "SELECT CORR(cost, latency) FROM event;",
        "SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency) FROM event;",
        "SELECT COUNT(*) OVER (PARTITION BY team_id) FROM event;",
        "WITH report AS (SELECT DISTINCT id FROM event) SELECT id FROM report;",
        "SELECT id FROM event WHERE id IN (SELECT MIN(id) FROM event);",
        "INSERT INTO report SELECT team_id, COUNT(*) FROM event GROUP BY team_id;",
        "UPDATE report SET total = (SELECT COUNT(*) FROM event);",
        "DELETE FROM report WHERE total < (SELECT COUNT(*) FROM event);",
        "CREATE VIEW report AS SELECT DISTINCT id FROM event;",
        "SELECT COUNT(*) FROM event WHERE id = %(event_id)s LIMIT 1;",
        "SELECT COUNT(*) FROM event WHERE id = $1;",
        "SELECT COUNT(1);",
        "SELECT 1 GROUP BY 1;",
    ],
)
def test_policy_query_shapes_are_blocking(query: str) -> None:
    [finding] = _check(query)
    assert finding.code == "SARJ122"
    assert finding.severity is DefaultLevel.ERROR
    assert "ClickHouse" in finding.message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM event WHERE id = $1 LIMIT 1;",
        "SELECT EXISTS(SELECT 1 FROM event WHERE id = $1);",
        "SELECT id FROM event WHERE cost IS DISTINCT FROM 0;",
        "SELECT id FROM event WHERE cost IS NOT DISTINCT FROM 0;",
        "SELECT 'SELECT DISTINCT id FROM event' AS example FROM event;",
        'SELECT "DISTINCT", "GROUP BY", "COUNT" FROM event;',
        "SELECT id /* COUNT(*) GROUP BY id */ FROM event -- DISTINCT;",
        "SELECT $$SELECT COUNT(*) FROM event; SELECT DISTINCT id FROM event$$ AS example;",
        "SELECT $body$SELECT COUNT(*) FROM event$body$ AS example;",
        "SELECT id FROM event WHERE id = %(count)s;",
        "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM event;",
        "SELECT COALESCE(cost, 0) FROM event;",
        "SELECT id FROM event UNION ALL SELECT id FROM archive;",
        "CREATE TABLE event (id UUID PRIMARY KEY, total INTEGER);",
        "SELECT DISTINCT FROM;",
    ],
)
def test_near_misses_are_not_policy_violations(query: str) -> None:
    assert _check(query) == []


@pytest.mark.parametrize("dialect", ["postgres", "postgresql", "mysql", "mariadb", "sqlite"])
def test_explicit_transactional_dialects(dialect: str) -> None:
    [finding] = _check(f"-- sql-dialect: {dialect}\nSELECT DISTINCT id FROM event;")
    assert finding.line == 2


@pytest.mark.parametrize(
    "dialect", ["clickhouse", "bigquery", "duckdb", "snowflake", "redshift", "trino", "athena", "spark", "databricks"]
)
def test_analytical_dialects_allow_same_queries(dialect: str) -> None:
    assert _check(f"-- dialect: {dialect}\nSELECT DISTINCT id, COUNT(*) FROM event GROUP BY id;") == []
    assert _check("SELECT DISTINCT id, COUNT(*) FROM event GROUP BY id;", f"{dialect}/queries/events.sql") == []


def test_explicit_transactional_dialect_overrides_analytical_directory() -> None:
    assert len(_check("-- dialect: postgres\nSELECT COUNT(*) FROM event;", "clickhouse/queries/events.sql")) == 1


def test_analytical_directive_inside_data_does_not_change_backend() -> None:
    assert len(_check("SELECT '-- dialect: clickhouse';\nSELECT DISTINCT id FROM event;")) == 1
    assert len(_check("SELECT $$\n-- dialect: clickhouse\n$$;\nSELECT DISTINCT id FROM event;")) == 1


@pytest.mark.parametrize(
    "path", ["tests/events.sql", "fixtures/events.sql", "generated/events.sql", "queries/events.generated.sql"]
)
def test_nonproduction_source_is_excluded(path: str) -> None:
    assert _check("SELECT COUNT(*) FROM event;", path) == []


@pytest.mark.parametrize(
    "header", ["-- @generated\n", "-- Code generated by tool. DO NOT EDIT.\n", "-- PostgreSQL database dump\n"]
)
def test_generated_or_dump_headers_are_excluded(header: str) -> None:
    source = header + "SELECT COUNT(*) FROM event;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


@pytest.mark.parametrize("path", ["migrations/001.sql", "schema.sql", "scripts/report.sql", "analytics/report.sql"])
def test_authored_sql_is_not_exempt_by_filename(path: str) -> None:
    assert len(_check("SELECT DISTINCT id FROM event;", path)) == 1


def test_one_finding_per_statement_with_physical_locations() -> None:
    source = "-- header\r\nSELECT DISTINCT id, COUNT(*) FROM event GROUP BY id;\r\nSELECT id FROM event;\r\nSELECT %(param)s, SUM(cost) FROM event;\r\n"
    findings = _check(source)
    assert [(finding.line, finding.col) for finding in findings] == [(2, 8), (4, 19)]


def test_group_comments_preserve_locations_and_later_native_function_identity() -> None:
    source = '-- header\r\nSELECT id FROM event GROUP/* gap\r\n*/BY id;\r\nSELECT "SUM"(id) FROM event;\r\nSELECT pg_catalog."sum"(id) FROM event;'
    findings = _check(source)
    assert [(finding.line, finding.col) for finding in findings] == [(2, 22), (5, 19)]


def test_malformed_statement_does_not_hide_later_query() -> None:
    assert len(_check("SELECT DISTINCT FROM;\nSELECT COUNT(*) FROM event;")) == 1


@pytest.mark.parametrize(("tail", "exit_code"), [("", 1), (" -- sarj-noqa: SARJ122 -- reviewed atomic invariant", 0)])
def test_native_cli_policy_and_exact_exceptions(tmp_path: Path, tail: str, exit_code: int) -> None:
    path = tmp_path / "events.sql"
    source = f"SELECT COUNT(*) FROM event;{tail}\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    path.write_text(source)
    assert main(["check", "--rule", NoAnalyticalQueriesInTransactionalDb.id, str(path)]) == exit_code


@pytest.mark.parametrize(
    ("dialect", "query", "count"),
    [
        ("postgres", "SELECT distinctrow FROM event", 0),
        ("postgres", 'SELECT DISTINCT "id" FROM event', 1),
        ("postgres", "SELECT DISTINCT 'value' FROM event", 1),
        ("postgres", "SELECT DISTINCT $$value$$ FROM event", 1),
        ("postgres", "SELECT DISTINCT NULL FROM event", 1),
        ("postgres", 'SELECT "a--b" FROM event WHERE id IS DISTINCT FROM 0', 0),
        ("postgres", 'SELECT "a--b" FROM event WHERE id IS NOT DISTINCT FROM 0', 0),
        ("mysql", "SELECT DISTINCT 'value' FROM event", 1),
        ("mysql", r"SELECT 'a\' GROUP BY id' FROM event", 0),
        ("mysql", "SELECT `a--b` FROM event WHERE id IS DISTINCT FROM 0", 0),
        ("mysql", "SELECT `a--b` FROM event WHERE id IS NOT DISTINCT FROM 0", 0),
        ("sqlite", "SELECT DISTINCT 'value' FROM event", 1),
        ("sqlite", "SELECT DISTINCT[a--b] FROM event", 1),
        ("postgres", 'SELECT "distinctrow" FROM event', 0),
        ("mysql", "SELECT DISTINCTROW id FROM event", 1),
        ("mariadb", "SELECT DISTINCTROW id FROM event", 1),
        ("postgres", 'SELECT "GROUP" /* gap */ "BY" FROM event', 0),
        ("mysql", "SELECT `GROUP` /* gap */ `BY` FROM event", 0),
        ("sqlite", "SELECT [GROUP] /* gap */ [BY] FROM event", 0),
        ("sqlite", "SELECT [a--b], COUNT(*) FROM event", 1),
        ("sqlite", "SELECT [a--b] FROM event GROUP BY [a--b]", 1),
        ("sqlite", "SELECT `a--b` FROM event GROUP BY `a--b`", 1),
        ("sqlite", "SELECT [a--b] FROM event GROUP/* gap */BY [a--b]", 1),
        ("sqlite", "SELECT [a--b] FROM event GROUP-- gap\r\nBY [a--b]", 1),
        ("sqlite", "SELECT [a/*b] FROM event GROUP/* gap */BY [a/*b]", 1),
        ("sqlite", "SELECT DISTINCT [a--b] FROM event", 1),
        ("sqlite", "SELECT [a--b] FROM event UNION SELECT [a--b] FROM archive", 1),
        ("sqlite", "WITH [a--b] AS (SELECT id FROM event) SELECT id FROM [a--b] GROUP BY id", 1),
        ("sqlite", "SELECT [a--b] FROM event; SELECT [a--b] FROM event GROUP/* gap */BY [a--b]", 1),
        ("sqlite", "SELECT [a--b GROUP BY DISTINCT UNION] FROM event", 0),
        ("sqlite", "SELECT [a/*b GROUP BY DISTINCT UNION] FROM event", 0),
        ("sqlite", "SELECT [a--b] FROM event WHERE id IS DISTINCT FROM 0", 0),
        ("sqlite", "SELECT [a--b] FROM event WHERE id IS NOT DISTINCT FROM 0", 0),
        ("mysql", "SELECT `a--b` FROM event GROUP/* gap */BY `a--b`", 1),
        ("mysql", "WITH `a--b` AS (SELECT id FROM event) SELECT id FROM `a--b` GROUP BY id", 1),
        ("mysql", "SELECT `a/*b` FROM event GROUP-- gap\r\nBY `a/*b`", 1),
        ("mariadb", "SELECT `a--b` FROM event GROUP BY `a--b`", 1),
        ("mysql", "SELECT `a--b GROUP BY DISTINCT UNION` FROM event", 0),
        ("mysql", "SELECT id FROM event GROUP/* gap */BY id", 1),
        ("mysql", "SELECT id FROM event GROUP-- gap\r\nBY id", 1),
        ("postgres", "SELECT 'GROUP/*keep*/BY' FROM event", 0),
        ("postgres", 'SELECT pg_catalog."sum" /* gap */ (NULL) FROM event', 1),
        ("postgres", 'SELECT public."sum" /* gap */ (NULL) FROM event', 0),
        ("postgres", "SELECT XMLAGG(NULL) FROM event", 1),
        ("postgres", "SELECT RANGE_INTERSECT_AGG(NULL) FROM event", 1),
        ("sqlite", "SELECT JSONB_GROUP_ARRAY(NULL) FROM event", 1),
        ("sqlite", "SELECT MIN(a,b) FROM event", 0),
        ("sqlite", "SELECT MAX(a,b) FROM event", 0),
        ("sqlite", "SELECT MIN(a) FROM event", 1),
        ("sqlite", "SELECT TOTAL(cost) FROM event", 1),
        ("sqlite", "SELECT JSON_GROUP_ARRAY(id) FROM event", 1),
        ("sqlite", "SELECT JSON_GROUP_OBJECT(id,cost) FROM event", 1),
        ("mysql", "SELECT ANY_VALUE(id) FROM event", 0),
        ("mysql", "SELECT STD(cost) FROM event", 1),
        ("mysql", "SELECT JSON_ARRAYAGG(id) FROM event", 1),
        ("mysql", "SELECT JSON_OBJECTAGG(id,cost) FROM event", 1),
        ("postgres", "SELECT ANY_VALUE(id) FROM event", 1),
        ("postgres", "SELECT JSONB_OBJECT_AGG_UNIQUE_STRICT(id,cost) FROM event", 1),
    ],
)
def test_dialect_specific_aggregate_and_scalar_semantics(dialect: str, query: str, count: int) -> None:
    assert len(_check(f"-- dialect: {dialect}\n{query};")) == count


@pytest.mark.parametrize(
    ("dialect", "identifier"),
    [
        ("postgres", '"a--b GROUP BY DISTINCT UNION"'),
        ("mysql", "`a--b GROUP BY DISTINCT UNION`"),
        ("sqlite", "[a--b GROUP BY DISTINCT UNION]"),
    ],
)
@pytest.mark.parametrize("gap", ["/* gap */", "-- gap\r\n", "/* first\r\nsecond */"])
def test_group_locations_follow_dialect_quoted_identifiers_and_comments(
    dialect: str, identifier: str, gap: str
) -> None:
    source = f"-- dialect: {dialect}\r\nSELECT {identifier} FROM event;\r\nSELECT {identifier} FROM event\r\nGROUP{gap}BY {identifier};\r\nSELECT {identifier} FROM archive;"
    [finding] = _check(source)
    assert (finding.line, finding.col) == (4, 1)
    assert finding.message.startswith("GROUP BY belongs")


@pytest.mark.parametrize(
    "comment",
    ["# GROUP BY", r"# 'a\' GROUP BY id'", "# DISTINCT UNION GROUP BY"],
)
def test_mysql_comment_keywords_cannot_own_a_group_exception(comment: str, tmp_path: Path) -> None:
    path = tmp_path / "events.sql"
    source = f"-- dialect: mysql\nSELECT id FROM event {comment} -- sarj-noqa: SARJ122 -- comment is not the grouping clause\nGROUP BY id;\n"
    path.write_text(source)
    [finding] = analyze([NoAnalyticalQueriesInTransactionalDb.id], [path])
    assert (finding.line, finding.col) == (3, 1)
    assert finding.message.startswith("GROUP BY belongs")


@pytest.mark.parametrize("operation", ["UNION", "INTERSECT", "EXCEPT"])
@pytest.mark.parametrize("all_gap", [" ", "/* gap */", "-- gap\r\n"])
def test_set_operation_locations_skip_allowed_all_operations(operation: str, all_gap: str) -> None:
    source = f"-- dialect: postgres\r\nSELECT id FROM event UNION{all_gap}ALL SELECT id FROM archive;\r\nSELECT id FROM event\r\nUNION{all_gap}ALL SELECT id FROM archive\r\n  {operation} SELECT id FROM report;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(source)
    expected_line = source[: source.index(f"  {operation}")].count("\n") + 1
    assert (finding.line, finding.col) == (expected_line, 3)
    assert finding.message.startswith("deduplicating set operation belongs")


def test_exception_on_allowed_union_all_does_not_suppress_later_deduplication(tmp_path: Path) -> None:
    path = tmp_path / "events.sql"
    path.write_text(
        "SELECT id FROM event\n"
        "UNION ALL SELECT id FROM archive -- sarj-noqa: SARJ122 -- reviewed historical note\n"
        "UNION SELECT id FROM report;\n"
    )
    [finding] = analyze([NoAnalyticalQueriesInTransactionalDb.id], [path])
    assert (finding.line, finding.col) == (3, 1)


@pytest.mark.parametrize(
    ("query", "count"),
    [
        ("SELECT pg_catalog.sum(cost) FROM event", 1),
        ('SELECT "pg_catalog"."sum"(cost) FROM event', 1),
        ("SELECT pg_catalog.count(*) FROM event", 1),
        ('SELECT "SUM"(cost) FROM event', 0),
        ('SELECT "sum"(cost) FROM event', 1),
        ('SELECT "JSONB_AGG"(cost) FROM event', 0),
        ('SELECT "jsonb_agg"(cost) FROM event', 1),
        ("SELECT public.jsonb_agg(cost) FROM event", 0),
        ("SELECT app.sum(cost) FROM event", 0),
        ('SELECT "PG_CATALOG".sum(cost) FROM event', 0),
        ('SELECT %(value)s, "SUM"(cost) FROM event', 0),
        ('SELECT %(value)s, "sum"(cost) FROM event', 1),
        ('SELECT "JSON_AGG"(NULL), "JSON_AGG"(NULL) FROM event', 0),
        ('SELECT "json_agg"(NULL), "json_agg"(NULL) FROM event', 1),
        ('SELECT "JSON_AGG"(NULL), custom.json_agg(NULL) FROM event', 0),
        ('SELECT "JSON_AGG"(NULL), JSON_AGG(NULL) FROM event', 1),
        ('SELECT JSON_AGG(NULL), "JSON_AGG"(NULL) FROM event', 1),
        ('SELECT "JSON_AGG"(TRUE), "JSON_AGG"(FALSE) FROM event', 0),
        ('SELECT "JSON_AGG"("JSON_AGG"(NULL)), custom.json_agg(NULL) FROM event', 0),
        ('SELECT "JSON_AGG"("JSON_AGG"(NULL)), JSON_AGG(FALSE) FROM event', 1),
        ('WITH prior AS (SELECT "JSON_AGG"(NULL) FROM event) SELECT JSON_AGG(NULL) FROM prior', 1),
        ('WITH prior AS (SELECT JSON_AGG(NULL) FROM event) SELECT "JSON_AGG"(NULL) FROM prior', 1),
        ('WITH prior AS (SELECT custom.json_agg(NULL) FROM event) SELECT "JSON_AGG"(NULL) FROM prior', 0),
        ('SELECT "JSON_AGG"(NULL) FROM event; SELECT JSON_AGG(NULL) FROM archive', 1),
        ('SELECT "JSON_AGG"(NULL) FROM event; SELECT custom.json_agg(NULL) FROM archive', 0),
        ('SELECT JSON_AGG(NULL); SELECT "JSON_AGG"(NULL)', 1),
        ('SELECT "JSON_AGG"(NULL); SELECT JSON_AGG(NULL)', 1),
        ('SELECT "JSON_AGG"(NULL); SELECT custom.json_agg(NULL)', 0),
        ('SELECT custom.json_agg(NULL); SELECT "JSON_AGG"(NULL)', 0),
        ("SELECT ';' AS marker; SELECT \"JSON_AGG\"(NULL), custom.json_agg(NULL)", 0),
        ("SELECT $$;$$ AS marker; SELECT JSON_AGG(NULL), JSON_AGG(NULL)", 1),
    ],
)
def test_builtin_function_identity_uses_original_sql(query: str, count: int) -> None:
    assert len(_check(query)) == count


def test_metadata_free_function_location_uses_matching_native_call() -> None:
    query = 'SELECT "JSON_AGG"(NULL), JSON_AGG(NULL) FROM event'
    [finding] = _check(query)
    assert (finding.line, finding.col) == (1, query.index("JSON_AGG(NULL)") + 1)


@pytest.mark.parametrize(
    ("dialect", "prefix", "count"),
    [
        ("postgres", "EXPLAIN ANALYZE", 1),
        ("postgres", "EXPLAIN ANALYZE VERBOSE", 1),
        ("postgres", "EXPLAIN (ANALYZE)", 1),
        ("postgres", "EXPLAIN (ANALYZE TRUE, BUFFERS)", 1),
        ("postgres", "EXPLAIN (FORMAT JSON, ANALYZE ON)", 1),
        ("postgres", "EXPLAIN (ANALYZE 1)", 1),
        ("postgres", "EXPLAIN /* boundary */ ANALYZE", 1),
        ("postgres", "EXPLAIN", 0),
        ("postgres", "EXPLAIN VERBOSE", 0),
        ("postgres", "EXPLAIN (ANALYZE FALSE)", 0),
        ("postgres", "EXPLAIN (ANALYZE OFF)", 0),
        ("postgres", "EXPLAIN (ANALYZE 0)", 0),
        ("postgres", "EXPLAIN (FORMAT JSON)", 0),
        ("postgres", "EXPLAIN (ANALYZE TRUE, ANALYZE TRUE)", 0),
        ("mysql", "EXPLAIN ANALYZE", 1),
        ("mysql", "EXPLAIN ANALYZE FORMAT=TREE", 1),
        ("mysql", "EXPLAIN", 0),
        ("mysql", "EXPLAIN FORMAT=JSON", 0),
        ("sqlite", "EXPLAIN", 0),
        ("sqlite", "EXPLAIN QUERY PLAN", 0),
    ],
)
def test_only_executing_explain_queries_are_aggregation_work(dialect: str, prefix: str, count: int) -> None:
    query = f"{prefix} SELECT COUNT(*) FROM event"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(f"-- dialect: {dialect}\n{query};")) == count


def test_explain_normalization_preserves_comments_semicolons_and_crlf_locations() -> None:
    source = "-- header\r\nEXPLAIN (ANALYZE TRUE, BUFFERS)\r\nSELECT COUNT(*) FROM event WHERE label = 'a;b';\r\nSELECT id FROM event;\r\n"
    [finding] = _check(source)
    assert (finding.line, finding.col) == (3, 8)


@pytest.mark.parametrize("operation", ["UNION", "INTERSECT", "EXCEPT"])
@pytest.mark.parametrize("modifier", ["", "DISTINCT", "ALL"])
def test_set_deduplication_cannot_bypass_distinct_policy(operation: str, modifier: str) -> None:
    query = f"SELECT id FROM event {operation} {modifier} SELECT id FROM archive"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(query)) == int(modifier != "ALL")


def test_metadata_free_aggregate_keeps_its_original_function_location() -> None:
    [finding] = _check("-- header\nSELECT JSON_AGG(id) FROM event;\n")
    assert (finding.line, finding.col) == (2, 8)


@pytest.mark.parametrize("table", ["TEMP TABLE report", 'TEMPORARY TABLE IF NOT EXISTS "report.schema"."ON COMMIT"'])
@pytest.mark.parametrize("on_commit", ["DROP", "DELETE ROWS", "PRESERVE ROWS"])
@pytest.mark.parametrize(
    "query", ["SELECT DISTINCT id FROM event", "SELECT COUNT(*) FROM event", "SELECT id FROM event GROUP BY id"]
)
def test_temporary_ctas_executes_its_policy_query(table: str, on_commit: str, query: str) -> None:
    source = f"CREATE {table} ON COMMIT {on_commit} AS WITH rows AS ({query}) SELECT * FROM rows;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(source)
    assert finding.code == "SARJ122"
    assert finding.severity is DefaultLevel.ERROR


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM event WHERE id = $1",
        "SELECT EXISTS(SELECT 1 FROM event WHERE id = $1)",
        "SELECT 'SELECT DISTINCT id FROM event; ON COMMIT DROP AS' AS example",
        'SELECT "DISTINCT", "COUNT" FROM event',
        "SELECT $$SELECT DISTINCT id FROM event;$$ AS example",
        "SELECT id /* COUNT(*) DISTINCT */ FROM event",
    ],
)
def test_temporary_ctas_does_not_promote_query_data_or_operational_reads(query: str) -> None:
    source = f"CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS ({query}) SELECT * FROM rows;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


def test_temporary_ctas_comments_crlf_and_physical_locations() -> None:
    source = '-- header\r\nCREATE TEMP TABLE "ON COMMIT DROP AS" ON /* one\r\ntwo */ COMMIT /* three */ DROP AS\r\nWITH rows AS (\r\n  SELECT DISTINCT id FROM event\r\n) SELECT * FROM rows;\r\nSELECT SUM(cost) FROM event;'
    assert [(finding.line, finding.col) for finding in _check(source)] == [(5, 10), (7, 8)]


@pytest.mark.parametrize("tail", ["", " -- sarj-noqa: SARJ122 -- reviewed transactional invariant"])
def test_temporary_ctas_native_exception_uses_the_original_query_line(tmp_path: Path, tail: str) -> None:
    path = tmp_path / "events.sql"
    path.write_text(
        f"CREATE TEMP TABLE report ON COMMIT DROP AS\nWITH rows AS (\nSELECT DISTINCT id FROM event{tail}\n) SELECT * FROM rows;\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    )
    assert main(["check", "--rule", NoAnalyticalQueriesInTransactionalDb.id, str(path)]) == int(not tail)


def test_copy_stdin_ctas_text_is_not_executable_and_later_query_keeps_its_location() -> None:
    source = "COPY event FROM STDIN;\nCREATE TEMP TABLE payload ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;\n\\.\nCREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;"
    [finding] = _check(source)
    assert (finding.line, finding.col) == (4, source.splitlines()[3].index("DISTINCT") + 1)


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT FROM;",
        "CREATE VIEW report ON COMMIT DROP AS SELECT DISTINCT id FROM event;",
        "SELECT 'CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows';",
        "COPY event FROM STDIN;\nCREATE TEMP TABLE payload ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;\n",
    ],
)
def test_ctas_fallback_does_not_promote_malformed_or_opaque_commands(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("payload", ["raw'quote", 'raw"quote'])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT DISTINCT id FROM event;",
        "CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
    ],
)
def test_copy_text_quotes_do_not_hide_later_executable_policy_queries(payload: str, query: str) -> None:
    source = f"SELECT ';' AS boundary;\r\nCOPY event FROM STDIN;\r\n{payload}\r\n\\.\r\n{query}"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(source)
    assert (finding.line, finding.col) == (5, query.index("DISTINCT") + 1)


def test_copy_filename_named_stdin_is_not_a_text_input_stream() -> None:
    source = "COPY event FROM 'STDIN';\nSELECT DISTINCT id FROM event;"
    [finding] = _check(source)
    assert (finding.line, finding.col) == (2, 8)


@pytest.mark.parametrize(("mode", "count"), [("ANALYZE", 1), ("", 0)])
def test_explain_temporary_ctas_only_checks_executed_queries(mode: str, count: int) -> None:
    source = f"EXPLAIN {mode}\nCREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    findings = _check(source)
    assert len(findings) == count
    if findings:
        assert (findings[0].line, findings[0].col) == (2, source.splitlines()[1].index("DISTINCT") + 1)


@pytest.mark.parametrize(("mode", "count"), [("ANALYZE", 1), ("", 0)])
def test_copy_mask_is_idempotent_before_explain_temporary_ctas(mode: str, count: int) -> None:
    query = (
        "CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;"
    )
    source = f"COPY event FROM STDIN;\r\nEXPLAIN raw'quote\r\n\\.\r\nEXPLAIN {mode}\r\n{query}"
    prepared = normalize_postgres_ctas(source)
    assert normalize_postgres_ctas(prepared) == prepared
    findings = _check(source)
    assert len(findings) == count
    if findings:
        assert (findings[0].line, findings[0].col) == (5, query.index("DISTINCT") + 1)


@pytest.mark.parametrize(
    ("source", "count"),
    [
        (
            (
                "CREATE LOCAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * "
                "FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE GLOBAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * "
                "FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM "
                "event) SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                'CREATE LOCAL TEMPORARY TABLE IF NOT EXISTS "schema.name"."report" AS WITH rows AS (SELECT DISTINCT id '
                "FROM event) SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                'CREATE GLOBAL TEMP TABLE report ON COMMIT PRESERVE ROWS TABLESPACE "pg default" AS WITH rows AS (SELECT '
                "DISTINCT id FROM event) SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE LOCAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT id FROM event WHERE id = $1) SELECT "
                "* FROM rows;"
            ),
            0,
        ),
        (
            (
                "CREATE GLOBAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT id FROM event WHERE id = $1) "
                "SELECT * FROM rows;"
            ),
            0,
        ),
        (
            (
                'CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE "pg default" AS WITH rows AS (SELECT id FROM event '
                "WHERE id = $1) SELECT * FROM rows;"
            ),
            0,
        ),
        (
            (
                'CREATE LOCAL TEMP TABLE "DISTINCT" ON COMMIT DROP TABLESPACE "COUNT; AS" AS SELECT \'SELECT DISTINCT '
                "id;' AS example;"
            ),
            0,
        ),
        (
            (
                "COPY event FROM STDIN;\r\n"
                "EXPLAIN raw'quote\r\n"
                "\\.\r\n"
                "EXPLAIN ANALYZE\r\n"
                'CREATE LOCAL TEMP TABLE report ON /* property */ COMMIT DROP TABLESPACE "pg default" AS WITH rows AS '
                "(SELECT DISTINCT id FROM event) SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TABLE report TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM "
                "rows;"
            ),
            1,
        ),
        (
            (
                "CREATE UNLOGGED TABLE report TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT "
                "* FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TEMP TABLE report WITHOUT OIDS ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) "
                "SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TEMP TABLE report USING heap ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT "
                "* FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TEMP TABLE report WITH (fillfactor=70) ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM "
                "event) SELECT * FROM rows;"
            ),
            1,
        ),
        (
            (
                "CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE 'pg_default' AS WITH rows AS (SELECT DISTINCT id FROM "
                "event) SELECT * FROM rows;"
            ),
            0,
        ),
    ],
)
def test_postgres_temporary_table_header_properties(source: str, count: int) -> None:
    prepared = normalize_postgres_ctas(source)
    assert len(prepared) == len(source)
    assert normalize_postgres_ctas(prepared) == prepared
    findings = _check(source)
    assert len(findings) == count
    if findings:
        offset = source.rindex("DISTINCT")
        expected_line = source[:offset].count("\n") + 1
        expected_column = offset - source.rfind("\n", 0, offset)
        assert (findings[0].line, findings[0].col) == (expected_line, expected_column)


@pytest.mark.parametrize("parameter", ["%s", "%(ids)s", "%b", "%t", "%(ids)b", "%(ids)t"])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT DISTINCT ON (language) language, id::text FROM agent_profile WHERE language=ANY({parameter}::text[]) ORDER BY language, created_at",
        "SELECT COUNT(*) FROM event WHERE id=ANY({parameter}::uuid[])",
        "SELECT status FROM event WHERE id=ALL({parameter}::uuid[]) GROUP BY status",
        "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event WHERE id=ANY({parameter}::uuid[])",
    ],
)
def test_postgres_parameter_casts_do_not_hide_analytics(parameter: str, query: str) -> None:
    sql = query.format(parameter=parameter)
    findings = _check(sql)
    assert len(findings) == 1
    assert findings[0].code == "SARJ122"


@pytest.mark.parametrize("parameter", ["%s", "%(ids)s", "%b", "%t", "%(ids)b", "%(ids)t"])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM event WHERE id=ANY({parameter}::uuid[])",
        "SELECT EXISTS(SELECT 1 FROM event WHERE id=ANY({parameter}::uuid[]))",
        "SELECT 'DISTINCT COUNT(*) %(quoted)t' AS example FROM event WHERE id=ANY({parameter}::uuid[]) /* GROUP BY %b */",
    ],
)
def test_postgres_parameter_casts_keep_operational_reads(parameter: str, query: str) -> None:
    sql = query.format(parameter=parameter)
    assert _check(sql) == []


@pytest.mark.parametrize(
    ("sql", "count"),
    [
        ("SELECT DISTINCT id FROM event WHERE (sequence %% 2)=%s", 1),
        ("SELECT COUNT(*) FROM event WHERE label='%%s' AND (sequence %% 2)=%(parity)b", 1),
        ("SELECT id FROM event WHERE (sequence %% 2)=%t", 0),
        ("SELECT 'DISTINCT COUNT(*) %%s' AS example FROM event WHERE (sequence %% 2)=%s /* GROUP BY %% */", 0),
        ("SELECT COUNT(*) FROM event WHERE id=ANY(%d::uuid[])", 0),
    ],
)
def test_postgres_parameter_formats_preserve_percent_data_and_reject_invalid_formats(sql: str, count: int) -> None:
    assert len(_check(sql)) == count


@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
@pytest.mark.parametrize("parameter", ["%b", "%t"])
def test_postgres_parameter_formats_do_not_broaden_other_dialects(dialect: str, parameter: str) -> None:
    source = f"-- dialect: {dialect}\nSELECT COUNT(*) FROM event WHERE id={parameter};"
    assert _check(source) == []


def test_parameter_padding_preserves_later_statement_physical_locations() -> None:
    source = (
        "SELECT id FROM event WHERE id=ANY(%(long_named_ids)b::uuid[]);\r\n"
        "SELECT COUNT(*) FROM event WHERE (sequence %% 2)=%t;"
    )
    findings = _check(source)
    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (2, 8)


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        pytest.param("SELECT 'COPY", "';", id="quoted-scalar"),
        pytest.param('SELECT "COPY', '";', id="quoted-identifier"),
        pytest.param("SELECT $body$COPY", "$body$;", id="dollar-scalar"),
        pytest.param("/* COPY", " */", id="block-comment"),
    ],
)
def test_ctas_normalization_avoids_retokenizing_quoted_semicolons(
    monkeypatch: pytest.MonkeyPatch, opening: str, closing: str
) -> None:
    query = "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;"
    prefix = opening + ";" * 128 + closing + "\r\n"
    source = prefix + query
    tokenize = sqlglot.tokenize
    work: list[int] = []

    def observe(sql: str, *, read: str) -> list[Token]:
        work.append(len(sql))
        return tokenize(sql, read=read)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe real tokenizer work while forwarding every PostgreSQL input.
        sqlglot, "tokenize", observe
    )

    normalized = normalize_postgres_ctas(source)

    assert normalized == prefix + query.replace("ON COMMIT DROP", " " * len("ON COMMIT DROP"))
    assert sum(work) <= len(source) * 2


def test_ctas_copy_candidate_probes_stay_within_linear_work_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    query = "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;"
    prefix = "SELECT '" + " COPY" * 128 + "';\r\n"
    source = prefix + query
    tokenize = sqlglot.tokenize
    work: list[int] = []

    def observe(sql: str, *, read: str) -> list[Token]:
        work.append(len(sql))
        return tokenize(sql, read=read)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe real tokenizer work while forwarding every PostgreSQL input.
        sqlglot, "tokenize", observe
    )

    normalized = normalize_postgres_ctas(source)

    assert normalized == prefix + query.replace("ON COMMIT DROP", " " * len("ON COMMIT DROP"))
    assert sum(work) <= len(source) * 4


@pytest.mark.parametrize("ending", [pytest.param("\n", id="LF"), pytest.param("\r\n", id="CRLF")])
def test_ctas_raw_copy_payload_is_masked_before_tokenization(monkeypatch: pytest.MonkeyPatch, ending: str) -> None:
    query = "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;"
    payload_marker = "RAW_COPY_PAYLOAD_MUST_NOT_REACH_LEXER"
    payload = ending.join([payload_marker + " 1 2 3"] * 128)
    prefix = "COPY event FROM STDIN;" + ending + payload + ending + "\\." + ending
    source = prefix + query
    tokenize = sqlglot.tokenize

    def observe(sql: str, *, read: str) -> list[Token]:
        assert payload_marker not in sql
        return tokenize(sql, read=read)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- reject raw payload inputs and forward every actual PostgreSQL tokenization.
        sqlglot, "tokenize", observe
    )

    normalized = normalize_postgres_ctas(source)

    masked_prefix = "".join(char if char in {"\r", "\n"} else " " for char in prefix)
    assert normalized == masked_prefix + query.replace("ON COMMIT DROP", " " * len("ON COMMIT DROP"))
