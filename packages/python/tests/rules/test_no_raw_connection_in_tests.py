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


def test_pool_provenance_does_not_leak_between_functions() -> None:
    source = """
def database_fixture(pool: ConnectionPool):
    return pool

def unrelated_network_helper(pool):
    return pool.connection()
"""
    assert _check(source) == []
