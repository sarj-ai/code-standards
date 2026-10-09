from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_raw_connection_in_tests import NoRawConnectionInTests


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "tests/test_orders.py"):
    return NoRawConnectionInTests().check(Path(path), dedent(source))


@pytest.mark.parametrize("example", NoRawConnectionInTests.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize("pool_type", ["ConnectionPool", "AsyncConnectionPool"])
def test_reports_connection_on_annotated_pool_parameter(pool_type: str) -> None:
    findings = _check(f"def inspect(pool: {pool_type}):\n    return pool.connection()\n")
    assert len(findings) == 1
    assert findings[0].code == "SARJ429"


def test_reports_annotated_local_and_constructed_pool() -> None:
    assert len(_check("pool: ConnectionPool\npool.connection()\n")) == 1
    assert len(_check("pool = psycopg_pool.AsyncConnectionPool(dsn)\npool.connection()\n")) == 1


def test_ignores_unproven_connections_and_production_code() -> None:
    assert _check("client.connection()\n") == []
    assert _check("def run(pool):\n    pool.connection()\n") == []
    assert _check("def run(pool: ConnectionPool):\n    pool.connection()\n", "app/store.py") == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/conftest.py",
        "tests/test_utils/database.py",
        "tests/testing/database.py",
        "tests/fixtures/database.py",
        "python/app/tests/db_truncate.py",
    ],
)
def test_allows_raw_connection_inside_shared_test_support(path: str) -> None:
    assert _check("def database_fixture(pool: ConnectionPool):\n    return pool.connection()\n", path) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/migrations/test_backfill_orders.py",
        "python/common/tests/migrations/test_backfill_orders.py",
    ],
)
def test_allows_migration_tests_to_manipulate_pre_store_state(path: str) -> None:
    assert _check("def seed_legacy_row(pool: ConnectionPool):\n    return pool.connection()\n", path) == []


def test_still_reports_collected_tests_outside_migration_trees() -> None:
    assert (
        len(
            _check(
                "def test_query(pool: ConnectionPool):\n    return pool.connection()\n", "tests/store/test_orders.py"
            )
        )
        == 1
    )


def test_allows_fixture_internal_connection_for_setup_and_cleanup() -> None:
    source = """
@pytest.fixture
async def seeded_database(pool: AsyncConnectionPool):
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO orders DEFAULT VALUES")
    yield "seeded"
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM orders")
"""
    assert len(_check(source)) == 2


def test_reports_fixture_that_exposes_raw_connection() -> None:
    source = """
@pytest.fixture()
async def raw_connection(pool: AsyncConnectionPool):
    async with pool.connection() as conn:
        yield conn
"""
    assert len(_check(source)) == 1


def test_pool_provenance_does_not_leak_between_functions() -> None:
    source = """
def database_fixture(pool: ConnectionPool):
    return pool

def unrelated_network_helper(pool):
    return pool.connection()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    ["tests/test_jobs.py", "tests/conftest.py", "tests/fixtures/probe.py", "app/testing/probe.py"],
)
def test_raw_sql_is_not_hidden_by_test_support_paths(path: str) -> None:
    source = """
from psycopg_pool import AsyncConnectionPool as Pool
class Probe:
    def __init__(self, pool: Pool):
        self._pool = pool
    async def seed(self):
        async with self._pool.connection() as connection:
            await connection.execute("INSERT INTO jobs (id) VALUES (%s)", (job_id,))
"""
    findings = _check(source, path)
    assert len(findings) == 1
    assert findings[0].code == "SARJ429"


@pytest.mark.parametrize(
    "statement",
    ["conn.execute(query)", "conn.executemany(query, rows)", "conn.execute(query=builder())"],
)
def test_proven_connection_catches_dynamic_queries(statement: str) -> None:
    source = f"from psycopg import Connection as DB\ndef test_query(conn: DB):\n    {statement}\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "client.query('SELECT id FROM jobs')",
        "client.execute('UPDATE jobs SET state = %s', (state,))",
        "client.fetch('SELECT id FROM jobs')",
        "client.exec_driver_sql('DELETE FROM jobs')",
        "client.command('TRUNCATE TABLE jobs')",
        "client.execute(query='SELECT 1')",
        "client.execute('SELECT ' + 'id FROM jobs')",
        "client.execute(f'SELECT id FROM jobs WHERE id = {job_id}')",
        "client.execute('/* setup */ SELECT id FROM jobs')",
    ],
)
def test_sql_shaped_execution_is_independent_of_driver(statement: str) -> None:
    assert len(_check(f"async def test_query(client):\n    {statement}\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "client.execute('send notification')\n",
        "client.query('How many orders?')\n",
        "client.execute('update preferences')\n",
        "example = \"conn.execute('SELECT id FROM jobs')\"\n",
        "assert compiler.render() == 'SELECT id FROM jobs'\n",
        "client.execute(query)\n",
        "# conn.execute('SELECT id FROM jobs')\n",
    ],
)
def test_near_misses_do_not_infer_database_execution(source: str) -> None:
    assert _check(source) == []


def test_sql_execution_supersedes_connection_acquisition() -> None:
    source = """
from psycopg_pool import AsyncConnectionPool
async def test_rows(pool: AsyncConnectionPool):
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_generated_and_production_sql_are_excluded() -> None:
    source = "conn.execute('SELECT id FROM jobs')\n"
    assert _check(source, "app/store.py") == []
    assert _check("# @generated\n" + source) == []


def test_malformed_source_and_exact_suppression() -> None:
    assert _check("def test_broken(:") == []
    assert _check("conn.execute('SELECT id FROM jobs')  # sarj-noqa: SARJ429 — migration behavior under test\n") == []
    assert len(_check("conn.execute('SELECT id FROM jobs')  # sarj-noqa: SARJ415 — different rule\n")) == 1
