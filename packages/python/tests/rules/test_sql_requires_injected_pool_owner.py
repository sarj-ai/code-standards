from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.sql_requires_injected_pool_owner import SqlRequiresInjectedPoolOwner


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/store.py"):
    return SqlRequiresInjectedPoolOwner().check(Path(path), source)


def test_flags_pool_connection_and_cursor_in_free_helper() -> None:
    source = """
async def mark(pool: AsyncConnectionPool):
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE call SET retry_attempt_number = 2")
"""
    findings = _check(source, "tests/fixtures/retry_rows.py")
    assert len(findings) == 1
    assert findings[0].code == "SARJ415"


def test_allows_execution_derived_from_injected_pool() -> None:
    source = """
class Store:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def mark(self):
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("UPDATE call SET retry_attempt_number = 2")
"""
    assert _check(source) == []


def test_ignores_unproven_executor_and_migrations() -> None:
    assert _check("def run(executor):\n    executor.execute(job)\n") == []
    source = "async def up(conn: AsyncConnection):\n    await conn.execute('ALTER TABLE call ADD x int')\n"
    assert _check(source, "migrations/001.py") == []


@pytest.mark.parametrize("example", SqlRequiresInjectedPoolOwner.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
