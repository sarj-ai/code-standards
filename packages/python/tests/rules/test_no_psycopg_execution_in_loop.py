from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rules.no_psycopg_execution_in_loop import NoPsycopgExecutionInLoop
from sarj_python_lint.rules.prefer_psycopg_executemany import PreferPsycopgExecutemany


P = Path("app/store.py")


def test_documented_examples() -> None:
    verify_native_rule(NoPsycopgExecutionInLoop, analyze)


@pytest.mark.parametrize("receiver", ["connection", "alias"])
@pytest.mark.parametrize("statement", ["DELETE FROM item WHERE id = %s", "SELECT id FROM item WHERE id = %s"])
def test_connection_execution_and_local_preparation(receiver: str, statement: str) -> None:
    source = (
        "from psycopg import AsyncConnection as NativeConnection\n"
        "async def save(connection: NativeConnection, rows):\n"
        "    alias = connection\n"
        "    for row in rows:\n"
        "        identifier = row.id\n"
        f"        await {receiver}.execute({statement!r}, (identifier,))\n"
    )
    [finding] = NoPsycopgExecutionInLoop().check(P, source)
    assert finding.code == "SARJ560"
    assert finding.line == 6


@pytest.mark.parametrize("loop", ["for row in rows:", "async for row in rows:"])
def test_injected_pool_cursor_execution(loop: str) -> None:
    source = (
        "from psycopg_pool import AsyncConnectionPool\n"
        "class Store:\n"
        "    def __init__(self, pool: AsyncConnectionPool): self.pool = pool\n"
        "    async def save(self, rows):\n"
        "        async with self.pool.connection() as connection:\n"
        "            LOOP\n"
        "                async with connection.cursor() as cursor:\n"
        "                    await cursor.execute('DELETE FROM item WHERE id = %s', (row.id,))\n"
    ).replace("LOOP", loop)
    assert len(NoPsycopgExecutionInLoop().check(P, source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "return [await connection.execute(query, (row,)) for row in rows]",
        "return {row: await connection.execute(query, (row,)) for row in rows}",
        "return (connection.execute(query, (row,)) for row in rows)",
    ],
)
def test_comprehension_execution_is_not_a_bulk_query(body: str) -> None:
    source = (
        f"from psycopg import AsyncConnection\nasync def load(connection: AsyncConnection, query, rows):\n    {body}\n"
    )
    assert len(NoPsycopgExecutionInLoop().check(P, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "async def save(client, rows):\n    for row in rows:\n        await client.execute(query, row)\n",
        "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    values = [(row.id,) for row in rows]\n    await connection.execute(query, values)\n",
        "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    for connection in rows:\n        await connection.execute(query)\n",
        "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    for row in rows:\n        async def deferred():\n            await connection.execute(query)\n",
        "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    for row in rows:\n        pass\n    await connection.execute(query)\n",
        "from psycopg import AsyncCursor\nasync def save(cursor: AsyncCursor, batches):\n    for batch in batches:\n        await cursor.executemany('DELETE FROM item WHERE id = %s', batch)\n",
    ],
)
def test_in_memory_loops_unknown_receivers_and_deferred_work_remain_valid(source: str) -> None:
    assert NoPsycopgExecutionInLoop().check(P, source) == []


def test_specific_executemany_rule_owns_its_existing_diagnostic() -> None:
    source = "from psycopg import AsyncCursor\nasync def save(cursor: AsyncCursor, rows):\n    for row in rows:\n        await cursor.execute('DELETE FROM item WHERE id = %s', (row,))\n"
    findings = check_source([PreferPsycopgExecutemany(), NoPsycopgExecutionInLoop()], P, source)
    assert [finding.code for finding in findings] == ["SARJ518"]
    assert [finding.code for finding in check_source([NoPsycopgExecutionInLoop()], P, source)] == ["SARJ560"]


def test_suppression_generated_code_and_malformed_input() -> None:
    source = "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    for row in rows:\n        await connection.execute(query)  # sarj-noqa: SARJ560 -- intentionally serialized row effects\n"
    assert NoPsycopgExecutionInLoop().check(P, source) == []
    assert NoPsycopgExecutionInLoop().check(P, "# Code generated. DO NOT EDIT.\n" + source) == []
    assert NoPsycopgExecutionInLoop().check(P, "async def (") == []
