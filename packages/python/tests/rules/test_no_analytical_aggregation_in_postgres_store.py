from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.rule_base import Diagnostic, RuleExample, Severity
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._nominal_project import NominalProjectFacts
from sarj_python_lint.rules.complex_postgres_query_requires_architecture_review import (
    ComplexPostgresQueryRequiresArchitectureReview,
)
from sarj_python_lint.rules.no_analytical_aggregation_in_postgres_store import (
    NoAnalyticalAggregationInPostgresStore,
    analytical_signal,
)


def _check(source: str, filename: str = "event_store.py") -> list[Diagnostic]:
    return NoAnalyticalAggregationInPostgresStore().check(Path(filename), source)


_PUBLIC_EXAMPLES = NoAnalyticalAggregationInPostgresStore.public_examples()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "SELECT org_id, status, COUNT(*), AVG(amount) FROM item GROUP BY org_id, status",
            "grouped reporting shape",
        ),
        ("SELECT org_id, status, COUNT(*), AVG(amount) FROM item WHERE id=%s GROUP BY org_id, status", None),
        ("SELECT org_id, COUNT(*) FROM item GROUP BY org_id", None),
        ("SELECT org_id, status, COUNT(*), AVG(amount) FROM item GROUP BY org_id, status FOR UPDATE", None),
        ("SELECT COUNT(*) FROM item WHERE label='unterminated GROUP BY id", None),
    ],
)
def test_legacy_architecture_overlap_helper_preserves_signals(query: str, expected: str | None) -> None:
    assert analytical_signal(query) == expected


def test_legacy_architecture_overlap_helper_abstains_on_parser_recursion() -> None:
    query = "SELECT COUNT(*) FROM (" * 200 + "SELECT id FROM item" + ") grouped GROUP BY id" * 200
    assert analytical_signal(query) is None


def test_legacy_architecture_overlap_helper_preserves_supported_signal_without_private_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    query = (
        "SELECT org_id, status, COUNT(*), AVG(amount) FROM item GROUP BY org_id, status; "
        "VACUUM private_synthetic_marker"
    )
    assert analytical_signal(query) == "grouped reporting shape"
    assert caplog.records == []


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "function",
    [
        "STDDEV_POP(latency_ms)",
        "VAR_SAMP(latency_ms)",
        "CORR(duration_ms, cost)",
        "COVAR_POP(duration_ms, cost)",
        "REGR_SLOPE(cost, duration_ms)",
        "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)",
    ],
)
def test_flags_strong_statistical_postgres_aggregates(function: str) -> None:
    source = f'import psycopg\nQUERY = "SELECT {function} FROM event"\n'  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


def test_flags_postgres_time_bucketed_rollup() -> None:
    source = """import asyncpg
QUERY = \"SELECT DATE_TRUNC('hour', occurred_at), COUNT(*), AVG(latency_ms) FROM event GROUP BY 1\"
"""
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "GROUP BY" in diagnostics[0].message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT organization_id, status, COUNT(*), AVG(duration) FROM call GROUP BY organization_id, status",
        "SELECT organization_id, COUNT(*), MIN(started_at), MAX(ended_at) FROM call GROUP BY organization_id",
    ],
)
def test_flags_broad_grouped_reporting_shapes(query: str) -> None:
    diagnostics = _check(f'import psycopg\nq = "{query}"\n')
    assert len(diagnostics) == 1
    assert "GROUP BY" in diagnostics[0].message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT status, COUNT(*), AVG(duration) FROM call WHERE id = %s GROUP BY status",
        "SELECT organization_id, status, COUNT(*), AVG(duration) FROM call WHERE id = %s GROUP BY organization_id, status",
        "SELECT organization_id, status, COUNT(*), AVG(duration) FROM call GROUP BY organization_id, status FOR UPDATE",
    ],
)
def test_bounds_and_locks_do_not_bypass_datastore_policy(query: str) -> None:
    assert len(_check(f'import psycopg\nq = "{query}"\n')) == 1


@pytest.mark.parametrize(
    "source",
    [
        'import psycopg\nq = "SELECT SUM(amount) FROM ledger WHERE account_id = %s FOR UPDATE"\n',
        'import psycopg\nq = "SELECT MIN(run_at) FROM job WHERE queue = %s"\n',
        'import psycopg\nq = "SELECT MAX(version) FROM migration FOR UPDATE"\n',
        'import psycopg\nq = "SELECT DISTINCT user_id FROM member WHERE org_id = %s"\n',
        'import psycopg\nq = "SELECT JSONB_AGG(child) FROM child WHERE parent_id = %s"\n',
        'import psycopg\nq = "SELECT status, COUNT(*) FROM task GROUP BY status"\n',
        'import psycopg\nq = "UPDATE cache SET count = (SELECT COUNT(*) FROM item)"\n',
    ],
)
def test_previously_exempt_aggregate_shapes_are_blocking(source: str) -> None:
    [finding] = _check(source)
    assert finding.severity is Severity.ERROR


@pytest.mark.parametrize(
    "source",
    [
        "q = \"SELECT DATE_TRUNC('day', ts), COUNT(*) FROM event GROUP BY 1\"\n",
        '# import psycopg\nq = "SELECT DISTINCT id FROM event"\n',
        'DRIVER = "psycopg"\nq = "SELECT DISTINCT id FROM event"\n',
        'import fake_psycopg\nq = "SELECT DISTINCT id FROM event"\n',
        'from .psycopg import Connection\nq = "SELECT DISTINCT id FROM event"\n',
    ],
)
def test_requires_native_backend_ownership(source: str) -> None:
    assert _check(source) == []


def test_sql_in_docstrings_is_not_executable() -> None:
    source = '''import psycopg

def report() -> None:
    """Never run SELECT STDDEV(latency) FROM event in PostgreSQL."""
'''
    assert _check(source) == []


def test_generated_module_is_excluded() -> None:
    source = """# Code generated by sqlc. DO NOT EDIT.
import psycopg
q = "SELECT STDDEV(latency) FROM event"
"""
    assert _check(source) == []


def test_mixed_backend_module_classifies_each_query() -> None:
    source = """import psycopg
import clickhouse_connect

def report(pg: psycopg.Connection) -> None:
    pg.execute("SELECT COUNT(*) FROM event")
    clickhouse_connect.get_client().query("SELECT COUNT(*) FROM event")
"""
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5


def test_bigquery_query_in_mixed_module_is_excluded() -> None:
    source = """import psycopg
from google.cloud import bigquery
q = "SELECT PERCENTILE_CONT(duration, 0.9) FROM `project.dataset.event`"
"""
    assert _check(source) == []


def test_concatenated_cte_is_detected_once() -> None:
    source = """import psycopg
q = "WITH samples AS (SELECT latency FROM event) " + "SELECT STDDEV(latency) FROM samples"
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("filename", ["test_event_store.py", "tests/stores/event.py"])
def test_test_modules_are_excluded(filename: str) -> None:
    source = 'import psycopg\nq = "SELECT STDDEV(latency) FROM event"\n'
    assert _check(source, filename) == []


def test_parse_failure_returns_no_diagnostics() -> None:
    source = 'import psycopg\nq = "SELECT STDDEV(latency) FROM event"\ndef (:\n'
    assert _check(source) == []


def test_diagnostic_metadata() -> None:
    diagnostics = _check('import psycopg\nq = "SELECT STDDEV(latency) FROM event"\n')
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.code == "SARJ020"
    assert diagnostic.path == Path("event_store.py")
    assert (diagnostic.line, diagnostic.col) == (2, 5)
    assert diagnostic.severity is Severity.ERROR
    assert "ClickHouse" in diagnostic.message


@pytest.mark.parametrize("filename", ["service.py", "routes/report.py", "jobs/reconcile.py", "client.py"])
def test_policy_is_independent_of_module_naming(filename: str) -> None:
    assert (
        len(_check('from psycopg_pool import AsyncConnectionPool\nq = "SELECT DISTINCT id FROM event"\n', filename))
        == 1
    )


_POLICY_QUERIES = (
    "SELECT DISTINCT id FROM event",
    "SELECT DISTINCT ON (team_id) id FROM event ORDER BY team_id",
    "SELECT team_id FROM event GROUP BY team_id",
    "SELECT team_id FROM event GROUP/* comment */BY team_id",
    "SELECT team_id FROM event GROUP /* comment */ BY team_id",
    "SELECT team_id FROM event GROUP-- comment\r\nBY team_id",
    "SELECT team_id FROM event GROUP/* first\r\nsecond */BY team_id",
    "SELECT team_id, COUNT(*) FROM event GROUP BY team_id LIMIT 1",
    "SELECT COUNT(*) FROM event",
    "SELECT COUNT(DISTINCT team_id) FROM event",
    "SELECT SUM(cost) FROM event",
    "SELECT AVG(cost) FROM event",
    "SELECT MIN(created_at) FROM event",
    "SELECT MAX(created_at) FROM event",
    "SELECT ARRAY_AGG(id) FROM event",
    "SELECT STRING_AGG(name, ',') FROM event",
    "SELECT JSONB_AGG(event) FROM event",
    "SELECT JSON_AGG(NULL), JSON_AGG(NULL) FROM event",
    "SELECT JSON_AGG(TRUE), JSON_AGG(FALSE) FROM event",
    "SELECT JSON_AGG(NULL), JSON_AGG(TRUE), JSON_AGG(FALSE)",
    "SELECT JSON_AGG(NULL), JSON_AGG(NULL); SELECT JSON_AGG(TRUE), JSON_AGG(FALSE)",
    "SELECT BOOL_AND(active) FROM event",
    "SELECT COUNT(*) OVER (PARTITION BY team_id) FROM event",
    "WITH report AS (SELECT DISTINCT id FROM event) SELECT id FROM report",
    "SELECT id FROM event WHERE id IN (SELECT MIN(id) FROM event)",
    "INSERT INTO report SELECT team_id, COUNT(*) FROM event GROUP BY team_id",
    "UPDATE report SET total = (SELECT COUNT(*) FROM event)",
    "DELETE FROM report WHERE total < (SELECT COUNT(*) FROM event)",
    "SELECT COUNT(*) FROM event WHERE id = %(event_id)s LIMIT 1",
    "SELECT COUNT(*) FROM event WHERE id = $1",
    "SELECT COUNT(1)",
    "SELECT 1 GROUP BY 1",
)


@pytest.mark.parametrize("query", _POLICY_QUERIES)
def test_parsed_policy_shapes_are_blocking(query: str) -> None:
    [finding] = _check(f"import psycopg\nq = {query!r}\n")
    assert finding.severity is Severity.ERROR


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM event WHERE id = %s LIMIT 1",
        "SELECT EXISTS(SELECT 1 FROM event WHERE id = $1)",
        "SELECT id FROM event WHERE cost IS DISTINCT FROM 0",
        "SELECT id FROM event WHERE cost IS NOT DISTINCT FROM 0",
        "SELECT 'SELECT DISTINCT id FROM event' AS example FROM event",
        'SELECT "DISTINCT", "GROUP BY", "COUNT" FROM event',
        "SELECT id /* COUNT(*) GROUP BY id */ FROM event -- DISTINCT",
        "SELECT $$SELECT COUNT(*) FROM event$$ AS example",
        "SELECT id FROM event WHERE id = %(count)s",
        "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM event",
        "SELECT COALESCE(cost, 0) FROM event",
        "SELECT id FROM event UNION ALL SELECT id FROM archive",
        "SELECT DISTINCT FROM",
    ],
)
def test_near_miss_sql_is_not_an_aggregate_policy_violation(query: str) -> None:
    assert _check(f"import psycopg\nq = {query!r}\n") == []


@pytest.mark.parametrize(
    "driver",
    [
        "psycopg",
        "psycopg2",
        "psycopg_pool",
        "asyncpg",
        "sqlite3",
        "aiosqlite",
        "mysql.connector",
        "pymysql",
        "aiomysql",
        "asyncmy",
        "sqlalchemy.dialects.postgresql",
        "sqlalchemy.dialects.mysql",
        "sqlalchemy.dialects.sqlite",
    ],
)
def test_known_transactional_drivers_own_module_queries(driver: str) -> None:
    source = f"import {driver} as driver\nq = 'SELECT DISTINCT id FROM event'\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(source)
    assert finding.severity is Severity.ERROR


@pytest.mark.parametrize(
    "driver",
    [
        "clickhouse_connect",
        "clickhouse_driver",
        "asynch",
        "google.cloud.bigquery",
        "duckdb",
        "snowflake.connector",
        "trino",
        "pyathena",
        "databricks.sql",
    ],
)
def test_analytical_drivers_allow_the_same_queries(driver: str) -> None:
    source = f"import {driver}\nq = 'SELECT DISTINCT id, COUNT(*) FROM event GROUP BY id'\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


@pytest.mark.parametrize(
    "expression",
    [
        'f"SELECT DISTINCT id FROM {table}"',
        '"SELECT DISTINCT id FROM " + table',
        '"SELECT COUNT(*) " + "FROM event"',
        '"SELECT DISTINCT id FROM {}".format(table)',
        'SQL("SELECT DISTINCT id FROM {}").format(Identifier(table))',
    ],
)
def test_static_tokens_survive_recoverable_query_compositions(expression: str) -> None:
    source = f"from psycopg.sql import SQL, Identifier\nq = {expression}\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "receiver",
    [
        "psycopg.connect()",
        "psycopg.Connection.connect()",
        "psycopg.AsyncConnection.connect()",
        "psycopg.connect().cursor()",
    ],
)
def test_native_transactional_sinks_in_mixed_modules(receiver: str) -> None:
    source = f"import psycopg\nimport duckdb\n{receiver}.execute('SELECT DISTINCT id FROM event')\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import psycopg\nimport duckdb\nq = 'SELECT COUNT(*) FROM event'\n",
        "import psycopg\nimport duckdb\nunknown.execute('SELECT COUNT(*) FROM event')\n",
        "import psycopg\nimport duckdb\nduckdb.connect().execute('SELECT COUNT(*) FROM event')\n",
        "import psycopg\nimport duckdb\ndef report(pg):\n    pg.execute('SELECT COUNT(*) FROM event')\n",
        "import psycopg\nimport duckdb\ndef report(pg: psycopg.Connection):\n    pg = duckdb.connect()\n    pg.execute('SELECT COUNT(*) FROM event')\n",
    ],
)
def test_ambiguous_and_analytical_sinks_in_mixed_modules_abstain(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("tail", "exit_code"),
    [
        ("", 1),
        ("  # sarj-noqa: SARJ020 -- reviewed atomic invariant", 0),
    ],
)
def test_native_cli_enforces_policy_and_exact_exceptions(tmp_path: Path, tail: str, exit_code: int) -> None:
    path = tmp_path / "service.py"
    source = f"import psycopg\nq = 'SELECT COUNT(*) FROM event'{tail}\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    path.write_text(source)
    assert main(["check", "--rule", NoAnalyticalAggregationInPostgresStore.id, str(path)]) == exit_code


@pytest.mark.parametrize(
    ("driver", "query", "count"),
    [
        ("psycopg", "SELECT distinctrow FROM event", 0),
        ("psycopg", 'SELECT "distinctrow" FROM event', 0),
        ("mysql.connector", "SELECT DISTINCTROW id FROM event", 1),
        ("psycopg", 'SELECT "GROUP" /* gap */ "BY" FROM event', 0),
        ("mysql.connector", "SELECT `GROUP` /* gap */ `BY` FROM event", 0),
        ("sqlite3", "SELECT [GROUP] /* gap */ [BY] FROM event", 0),
        ("sqlite3", "SELECT [a--b], COUNT(*) FROM event", 1),
        ("sqlite3", "SELECT [a--b] FROM event GROUP/* gap */BY [a--b]", 1),
        ("sqlite3", "SELECT [a--b] FROM event GROUP-- gap\r\nBY [a--b]", 1),
        ("mysql.connector", "SELECT id FROM event GROUP/* gap */BY id", 1),
        ("mysql.connector", "SELECT id FROM event GROUP-- gap\r\nBY id", 1),
        ("psycopg", "SELECT 'GROUP/*keep*/BY' FROM event", 0),
        ("psycopg", 'SELECT pg_catalog."sum" /* gap */ (NULL) FROM event', 1),
        ("psycopg", 'SELECT public."sum" /* gap */ (NULL) FROM event', 0),
        ("psycopg", "SELECT XMLAGG(NULL) FROM event", 1),
        ("psycopg", "SELECT RANGE_INTERSECT_AGG(NULL) FROM event", 1),
        ("sqlite3", "SELECT JSONB_GROUP_ARRAY(NULL) FROM event", 1),
        ("sqlite3", "SELECT MIN(a,b) FROM event", 0),
        ("sqlite3", "SELECT MAX(a,b) FROM event", 0),
        ("sqlite3", "SELECT MIN(a) FROM event", 1),
        ("sqlite3", "SELECT TOTAL(cost) FROM event", 1),
        ("sqlite3", "SELECT JSON_GROUP_ARRAY(id) FROM event", 1),
        ("sqlite3", "SELECT JSON_GROUP_OBJECT(id,cost) FROM event", 1),
        ("mysql.connector", "SELECT ANY_VALUE(id) FROM event", 0),
        ("mysql.connector", "SELECT STD(cost) FROM event", 1),
        ("mysql.connector", "SELECT JSON_ARRAYAGG(id) FROM event", 1),
        ("mysql.connector", "SELECT JSON_OBJECTAGG(id,cost) FROM event", 1),
        ("psycopg", "SELECT ANY_VALUE(id) FROM event", 1),
        ("psycopg", "SELECT JSONB_OBJECT_AGG_UNIQUE_STRICT(id,cost) FROM event", 1),
    ],
)
def test_dialect_specific_aggregate_and_scalar_semantics(driver: str, query: str, count: int) -> None:
    assert len(_check(f"import {driver}\nq = {query!r}\n")) == count


@pytest.mark.parametrize(
    "setup",
    [
        "def report(db: psycopg.Connection):",
        "def report(db: 'psycopg.Connection'):",
        "def report():\n    db = psycopg.connect()",
        "def report():\n    db = psycopg.connect().cursor()",
        "def report():\n    with psycopg.connect() as db:",
    ],
)
def test_mixed_backend_native_bindings_and_annotations(setup: str) -> None:
    indent = "        " if "with " in setup else "    "
    query = "SELECT DISTINCT id FROM event"
    source = f"import psycopg\nimport duckdb\n{setup}\n{indent}db.execute(query={query!r})\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("mutation", ["db.execute = other", "unknown(db)"])
def test_mixed_backend_mutated_or_escaped_receivers_abstain(mutation: str) -> None:
    query = "SELECT COUNT(*) FROM event"
    source = f"import psycopg\nimport duckdb\ndef report(db: psycopg.Connection):\n    {mutation}\n    db.execute({query!r})\n"
    assert _check(source) == []


@pytest.mark.parametrize("suppress", [False, True])
def test_aggregate_error_precedes_complexity_only_when_present(*, suppress: bool) -> None:
    query = "SELECT * FROM owner JOIN (SELECT team_id, COUNT(*) FROM event JOIN tag ON tag.event_id = event.id GROUP BY team_id) report ON TRUE"
    tail = "  # sarj-noqa: SARJ020 -- reviewed atomic invariant" if suppress else ""
    source = f"import psycopg\ncursor.execute({query!r}){tail}\n"
    findings = check_source(
        [NoAnalyticalAggregationInPostgresStore(), ComplexPostgresQueryRequiresArchitectureReview()],
        Path("service.py"),
        source,
    )
    expected = [("SARJ437", Severity.WARNING)] if suppress else [("SARJ020", Severity.ERROR)]
    assert [(finding.code, finding.severity) for finding in findings] == expected


@pytest.mark.parametrize("reexports", [0, 1, 2])
@pytest.mark.parametrize("driver", ["clickhouse_connect", "duckdb"])
def test_first_party_analytical_protocols_do_not_become_postgres_queries(
    tmp_path: Path, reexports: int, driver: str
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.1.0"\n')
    package = tmp_path / "example"
    package.mkdir()
    (package / "__init__.py").write_text("")
    provider = f"import {driver}\nfrom typing import Protocol\nclass QueryBoundary(Protocol):\n    def query(self, sql: str) -> str: ...\n"
    (package / "provider.py").write_text(provider)
    imported = "provider"
    for index in range(reexports):
        name = f"alias_{index}"
        (package / f"{name}.py").write_text(f"from example.{imported} import QueryBoundary as QueryBoundary\n")
        imported = name
    query = "SELECT team_id,COUNT(*) FROM event GROUP BY team_id"
    path = package / "service.py"
    source = f"import psycopg\nfrom example.{imported} import QueryBoundary\ndef report(client: QueryBoundary):\n    client.query({query!r})\npsycopg.connect().execute({query!r})\n"
    path.write_text(source)
    findings = analyze([NoAnalyticalAggregationInPostgresStore.id], [path])
    assert [(finding.line, finding.severity) for finding in findings] == [(5, Severity.ERROR)]


def test_clickhouse_names_without_analytical_source_do_not_exempt_postgres(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.1.0"\n')
    package = tmp_path / "example"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "provider.py").write_text(
        "import psycopg\nclass ClickHouseQueryClient:\n    def query(self, sql: str) -> str: ...\n"
    )
    path = package / "service.py"
    path.write_text(
        "import psycopg\nfrom example.provider import ClickHouseQueryClient\ndef report(client: ClickHouseQueryClient):\n    client.query('SELECT COUNT(*) FROM event')\n"
    )
    assert len(analyze([NoAnalyticalAggregationInPostgresStore.id], [path])) == 1


def _namespace_wrapper_project(
    tmp_path: Path,
    annotation: str,
    *,
    declared_dependency: bool,
    generated_provider: bool = False,
    generated_reexport: bool = False,
) -> Path:
    (tmp_path / ".git").mkdir()
    workspace = tmp_path / "python"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["common", "webserver"]\n')
    common = workspace / "common"
    webserver = workspace / "webserver"
    provider = common / "acme" / "platform" / "common"
    consumer = webserver / "acme" / "platform" / "web"
    provider.mkdir(parents=True)
    consumer.mkdir(parents=True)
    (common / "pyproject.toml").write_text('[project]\nname = "sample-core"\nversion = "0.1.0"\n')
    dependencies = '["sample-core"]' if declared_dependency else "[]"
    (webserver / "pyproject.toml").write_text(
        f'[project]\nname = "sample-web"\nversion = "0.1.0"\ndependencies = {dependencies}\n'
    )
    # The import namespace spans distributions without package initializers.
    (provider / "provider.py").write_text(
        ("# @generated\n" if generated_provider else "") + "from clickhouse_connect.driver import create_async_client\n"
        "from typing import Protocol\n"
        "class QueryBoundary(Protocol):\n"
        "    def query(self, sql: str) -> str: ...\n"
    )
    (consumer / "client.py").write_text(
        ("# @generated\n" if generated_reexport else "")
        + "from acme.platform.common.provider import QueryBoundary as QueryBoundary\n"
    )
    query = "SELECT team_id,COUNT(*) FROM event GROUP BY team_id"
    path = consumer / "service.py"
    path.write_text(
        "from typing import TYPE_CHECKING\n"
        "import psycopg\n"
        "if TYPE_CHECKING:\n"
        "    from acme.platform.web.client import QueryBoundary\n"
        "\n"
        f"def report(client: {annotation}):\n"
        f"    query = {query!r}\n"
        "    return client.query(query)\n"
        "\n"
        f"psycopg.connect().execute({query!r})\n"
    )
    return path


@pytest.mark.parametrize("annotation", ["QueryBoundary", "'QueryBoundary'"])
@pytest.mark.parametrize("declared_dependency", [True, False])
def test_namespace_analytical_wrappers_follow_owned_distributions(
    tmp_path: Path, annotation: str, *, declared_dependency: bool
) -> None:
    path = _namespace_wrapper_project(tmp_path, annotation, declared_dependency=declared_dependency)
    findings = analyze([NoAnalyticalAggregationInPostgresStore.id], [path])
    expected_lines = [10] if declared_dependency else [7, 10]
    assert [(finding.line, finding.severity) for finding in findings] == [
        (line, Severity.ERROR) for line in expected_lines
    ]


@pytest.mark.parametrize("annotation", ["QueryBoundary", "'QueryBoundary'"])
@pytest.mark.parametrize("declared_dependency", [True, False])
@pytest.mark.parametrize("generated", ["provider", "reexport", "both"])
def test_generated_namespace_analytical_wrappers_retain_backend_ownership(
    tmp_path: Path, annotation: str, generated: str, *, declared_dependency: bool
) -> None:
    path = _namespace_wrapper_project(
        tmp_path,
        annotation,
        declared_dependency=declared_dependency,
        generated_provider=generated in {"provider", "both"},
        generated_reexport=generated in {"reexport", "both"},
    )
    expected_lines = [10] if declared_dependency else [7, 10]
    assert [
        (finding.line, finding.severity) for finding in analyze([NoAnalyticalAggregationInPostgresStore.id], [path])
    ] == [(line, Severity.ERROR) for line in expected_lines]


@pytest.mark.parametrize("first_mode", [False, True])
def test_generated_source_cache_keeps_nominal_inventories_excluded(tmp_path: Path, *, first_mode: bool) -> None:
    path = _namespace_wrapper_project(
        tmp_path, "QueryBoundary", declared_dependency=True, generated_provider=True, generated_reexport=True
    )
    ownership = NominalProjectFacts()
    first_party = FirstPartyFacts()
    provider = path.parents[4] / "common/acme/platform/common/provider.py"
    modules = {"acme.platform.common.provider", "acme.platform.web.client"}
    for include_generated in (first_mode, not first_mode, first_mode):
        sources = ownership.sources(path, first_party, include_generated=include_generated)
        assert modules <= sources.keys() if include_generated else modules.isdisjoint(sources)
        own_sources = ownership.sources(provider, first_party, include_generated=include_generated)
        assert ("acme.platform.common.provider" in own_sources) is include_generated
    assert modules.isdisjoint(ownership.sources(path, first_party))


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
    assert len(_check(f"import psycopg\nq = {query!r}\n")) == count


@pytest.mark.parametrize(
    ("driver", "prefix", "count"),
    [
        ("psycopg", "EXPLAIN ANALYZE", 1),
        ("psycopg", "EXPLAIN ANALYZE VERBOSE", 1),
        ("psycopg", "EXPLAIN (ANALYZE)", 1),
        ("psycopg", "EXPLAIN (ANALYZE TRUE, BUFFERS)", 1),
        ("psycopg", "EXPLAIN (FORMAT JSON, ANALYZE ON)", 1),
        ("psycopg", "EXPLAIN (ANALYZE 1)", 1),
        ("psycopg", "EXPLAIN /* boundary */ ANALYZE", 1),
        ("psycopg", "EXPLAIN", 0),
        ("psycopg", "EXPLAIN VERBOSE", 0),
        ("psycopg", "EXPLAIN (ANALYZE FALSE)", 0),
        ("psycopg", "EXPLAIN (ANALYZE OFF)", 0),
        ("psycopg", "EXPLAIN (ANALYZE 0)", 0),
        ("psycopg", "EXPLAIN (FORMAT JSON)", 0),
        ("psycopg", "EXPLAIN (ANALYZE TRUE, ANALYZE TRUE)", 0),
        ("mysql.connector", "EXPLAIN ANALYZE", 1),
        ("mysql.connector", "EXPLAIN ANALYZE FORMAT=TREE", 1),
        ("mysql.connector", "EXPLAIN", 0),
        ("mysql.connector", "EXPLAIN FORMAT=JSON", 0),
        ("sqlite3", "EXPLAIN", 0),
        ("sqlite3", "EXPLAIN QUERY PLAN", 0),
    ],
)
def test_only_executing_explain_queries_are_aggregation_work(driver: str, prefix: str, count: int) -> None:
    query = f"{prefix} SELECT COUNT(*) FROM event"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(f"import {driver}\nq = {query!r}\n")) == count


@pytest.mark.parametrize("operation", ["UNION", "INTERSECT", "EXCEPT"])
@pytest.mark.parametrize("modifier", ["", "DISTINCT", "ALL"])
def test_set_deduplication_cannot_bypass_distinct_policy(operation: str, modifier: str) -> None:
    query = f"SELECT id FROM event {operation} {modifier} SELECT id FROM archive"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(f"import psycopg\nq = {query!r}\n")) == int(modifier != "ALL")


@pytest.mark.parametrize("annotation", ["Connection", "'Connection'"])
def test_type_only_native_connection_annotations_retain_backend_proof(annotation: str) -> None:
    query = "SELECT COUNT(*) FROM event"
    source = f"from typing import TYPE_CHECKING\nimport duckdb\nif TYPE_CHECKING:\n    from psycopg import Connection\ndef report(db: {annotation}):\n    db.execute({query!r})\n"
    assert len(_check(source)) == 1


def test_local_annotation_shadow_cannot_claim_postgres_ownership() -> None:
    source = "import duckdb\nfrom psycopg import Connection\ndef outer():\n    Connection = duckdb.DuckDBPyConnection\n    def report(db: Connection):\n        db.execute('SELECT COUNT(*) FROM event')\n"
    assert _check(source) == []


@pytest.mark.parametrize("table", ["TEMP TABLE report", 'TEMPORARY TABLE IF NOT EXISTS "report.schema"."ON COMMIT"'])
@pytest.mark.parametrize("on_commit", ["DROP", "DELETE ROWS", "PRESERVE ROWS"])
@pytest.mark.parametrize(
    "query", ["SELECT DISTINCT id FROM event", "SELECT COUNT(*) FROM event", "SELECT id FROM event GROUP BY id"]
)
def test_temporary_ctas_executes_its_policy_query(table: str, on_commit: str, query: str) -> None:
    sql = f"CREATE {table} ON COMMIT {on_commit} AS WITH rows AS ({query}) SELECT * FROM rows;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(f"import psycopg\nq = {sql!r}\n")
    assert finding.code == "SARJ020"
    assert finding.severity is Severity.ERROR


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
    sql = f"CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS ({query}) SELECT * FROM rows;"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(f"import psycopg\nq = {sql!r}\n") == []


def test_temporary_ctas_preserves_python_literal_locations_and_single_diagnostic() -> None:
    sql = '-- header\r\nCREATE TEMP TABLE "ON COMMIT DROP AS" ON /* one\r\ntwo */ COMMIT /* three */ DROP AS\r\nWITH rows AS (\r\n  SELECT DISTINCT id, COUNT(*) FROM event GROUP BY id\r\n) SELECT * FROM rows;'
    [finding] = _check(f"import psycopg\n\ncursor.execute({sql!r})\n")
    assert (finding.line, finding.col) == (3, 16)


@pytest.mark.parametrize("tail", ["", "  # sarj-noqa: SARJ020 -- reviewed transactional invariant"])
def test_temporary_ctas_native_exception_uses_the_original_python_line(tmp_path: Path, tail: str) -> None:
    path = tmp_path / "service.py"
    sql = "CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;"
    path.write_text(f"import psycopg\ncursor.execute({sql!r}){tail}\n")
    assert main(["check", "--rule", NoAnalyticalAggregationInPostgresStore.id, str(path)]) == int(not tail)


@pytest.mark.parametrize(
    ("sql", "count"),
    [
        (
            "COPY event FROM STDIN;\nCREATE TEMP TABLE payload ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;\n\\.\n",
            0,
        ),
        (
            "COPY event FROM STDIN;\nCREATE TEMP TABLE payload ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;\n\\.\nCREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;",
            1,
        ),
    ],
)
def test_copy_stdin_ctas_text_is_not_executable(sql: str, count: int) -> None:
    assert len(_check(f"import psycopg\nq = {sql!r}\n")) == count


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT FROM;",
        "CREATE VIEW report ON COMMIT DROP AS SELECT DISTINCT id FROM event;",
        "SELECT 'CREATE TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows';",
        "COPY event FROM STDIN;\nCREATE TEMP TABLE payload ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;\n",
    ],
)
def test_ctas_fallback_does_not_promote_malformed_or_opaque_commands(sql: str) -> None:
    assert _check(f"import psycopg\nq = {sql!r}\n") == []


@pytest.mark.parametrize(
    "sql",
    [
        "COPY event FROM STDIN;\nraw'quote EXPLAIN\n\\.\nSELECT DISTINCT id FROM event;",
        'COPY event FROM STDIN;\nraw"quote EXPLAIN\n\\.\nSELECT DISTINCT id FROM event;',
        "COPY event FROM STDIN;\nraw'quote EXPLAIN\n\\.\nCREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;",
        'COPY event FROM STDIN;\nraw"quote EXPLAIN\n\\.\nEXPLAIN ANALYZE CREATE TEMP TABLE report ON COMMIT DROP AS SELECT DISTINCT id FROM event;',
    ],
)
def test_copy_payload_quotes_cannot_hide_a_later_policy_query(sql: str) -> None:
    [finding] = _check(f"import psycopg\nq = {sql!r}\n")
    assert finding.code == "SARJ020"
    assert finding.severity is Severity.ERROR


def test_quoted_stdin_filename_cannot_hide_a_later_policy_query() -> None:
    sql = "COPY event FROM 'STDIN'; SELECT DISTINCT id FROM event;"
    assert len(_check(f"import psycopg\nq = {sql!r}\n")) == 1


@pytest.mark.parametrize(
    ("sql", "count"),
    [
        pytest.param(
            "CREATE LOCAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;",
            1,
            id="local-temp-distinct",
        ),
        pytest.param(
            "CREATE GLOBAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;",
            1,
            id="global-temp-distinct",
        ),
        pytest.param(
            "CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;",
            1,
            id="drop-before-tablespace-distinct",
        ),
        pytest.param(
            'CREATE LOCAL TEMPORARY TABLE IF NOT EXISTS "ON COMMIT"."DROP" TABLESPACE "pg_default" AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;',
            1,
            id="quoted-local-temporary-identifiers",
        ),
        pytest.param(
            'CREATE GLOBAL TEMPORARY TABLE "TABLESPACE" ON COMMIT PRESERVE ROWS TABLESPACE "ON COMMIT DROP" AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;',
            1,
            id="quoted-global-temporary-identifiers",
        ),
        pytest.param(
            "CREATE LOCAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT id FROM event WHERE id = $1) SELECT id FROM rows;",
            0,
            id="local-temp-operational-lookup",
        ),
        pytest.param(
            "CREATE GLOBAL TEMP TABLE report ON COMMIT DROP AS WITH rows AS (SELECT EXISTS(SELECT 1 FROM event WHERE id = $1) AS present) SELECT present FROM rows;",
            0,
            id="global-temp-operational-existence",
        ),
        pytest.param(
            "CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE pg_default AS WITH rows AS (SELECT id FROM event WHERE id = $1) SELECT id FROM rows;",
            0,
            id="tablespace-operational-lookup",
        ),
        pytest.param(
            "CREATE GLOBAL TEMP TABLE report ON COMMIT DROP TABLESPACE pg_default AS SELECT 'SELECT DISTINCT id FROM event; LOCAL GLOBAL ON COMMIT DROP' AS example;",
            0,
            id="quoted-policy-words-remain-data",
        ),
        pytest.param(
            "COPY event FROM STDIN;\nraw'quote EXPLAIN LOCAL GLOBAL TABLESPACE\n\\.\nEXPLAIN ANALYZE CREATE LOCAL TEMP TABLE report ON COMMIT DROP TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT id FROM rows;",
            1,
            id="copy-data-and-repeated-explain-normalization",
        ),
        pytest.param(
            "CREATE TABLE report TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            1,
            id="regular-table-tablespace-distinct",
        ),
        pytest.param(
            "CREATE UNLOGGED TABLE report TABLESPACE pg_default AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            1,
            id="unlogged-table-tablespace-distinct",
        ),
        pytest.param(
            "CREATE TEMP TABLE report WITHOUT OIDS ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            1,
            id="temporary-table-without-oids-distinct",
        ),
        pytest.param(
            "CREATE TEMP TABLE report USING heap ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            1,
            id="supported-using-heap-remains-checked",
        ),
        pytest.param(
            "CREATE TEMP TABLE report WITH (fillfactor=70) ON COMMIT DROP AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            1,
            id="supported-storage-options-remain-checked",
        ),
        pytest.param(
            "CREATE TEMP TABLE report ON COMMIT DROP TABLESPACE 'pg_default' AS WITH rows AS (SELECT DISTINCT id FROM event) SELECT * FROM rows;",
            0,
            id="single-quoted-tablespace-is-invalid",
        ),
    ],
)
def test_qualified_temporary_ctas_preserves_policy_with_real_postgres_store(sql: str, count: int) -> None:
    source = (
        "from psycopg_pool import AsyncConnectionPool\n\n\n"
        "class PsqlProbeStore:\n"
        "    def __init__(self, pool: AsyncConnectionPool) -> None:\n"
        "        self.pool = pool\n\n"
        "    async def load(self) -> None:\n"
        "        async with self.pool.connection() as conn:\n"
        f"            await conn.execute({sql!r})\n"
    )
    findings = _check(source)
    assert len(findings) == count
    if findings:
        assert findings[0].code == "SARJ020"
        assert findings[0].severity is Severity.ERROR
        assert (findings[0].line, findings[0].col) == (10, 32)
