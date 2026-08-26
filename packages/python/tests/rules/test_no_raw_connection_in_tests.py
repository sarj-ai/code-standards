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


@pytest.mark.parametrize("path", ["tests/conftest.py", "tests/test_utils/database.py", "tests/testing/database.py"])
def test_allows_raw_connection_inside_shared_test_support(path: str) -> None:
    assert _check("def database_fixture(pool: ConnectionPool):\n    return pool.connection()\n", path) == []


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
    assert _check(source) == []


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
