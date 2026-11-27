from pathlib import Path
from textwrap import dedent, indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rules.no_psycopg_execution_in_loop import NoPsycopgExecutionInLoop


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


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
    [finding] = check_source([NoPsycopgExecutionInLoop()], P, source)
    assert finding.code == "SARJ560"
    assert "executemany" in finding.message


def test_suppression_generated_code_and_malformed_input() -> None:
    source = "from psycopg import AsyncConnection\nasync def save(connection: AsyncConnection, rows):\n    for row in rows:\n        await connection.execute(query)  # sarj-noqa: SARJ560 -- intentionally serialized row effects\n"
    assert NoPsycopgExecutionInLoop().check(P, source) == []
    assert NoPsycopgExecutionInLoop().check(P, "# Code generated. DO NOT EDIT.\n" + source) == []
    assert NoPsycopgExecutionInLoop().check(P, "async def (") == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("[await connection.execute(query) for _ in ()]", 0),
        ("[await connection.execute(query) for _ in (0,)]", 0),
        ("{row: await connection.execute(query) for row in ()}", 0),
        ("[row for row in (0,) if await connection.execute(query)]", 0),
        ("[value for _ in (0,) for value in await connection.execute(query)]", 0),
        ("[await connection.execute(query) for _ in () for row in rows]", 0),
        ("[await connection.execute(query) for _ in (0, 1)]", 1),
        ("[value for _ in (0, 1) for value in await connection.execute(query)]", 1),
        ("[await connection.execute(query) for row in rows for _ in (0,)]", 1),
        ("[row for row in rows if await connection.execute(query)]", 1),
        ("[value for row in rows for value in await connection.execute(query)]", 1),
        ("[[await connection.execute(query) for _ in (0,)] for row in rows]", 1),
    ],
)
def test_comprehension_repetition_follows_evaluation_cardinality(body: str, expected: int) -> None:
    source = f"from psycopg import AsyncConnection\nasync def load(connection: AsyncConnection, query, rows):\n    return {body}\n"
    assert len(NoPsycopgExecutionInLoop().check(P, source)) == expected


def _executemany_findings(
    body: str, *, annotation: str = "AsyncCursor", imports: str = "from psycopg import AsyncCursor"
) -> list[Diagnostic]:
    findings = NoPsycopgExecutionInLoop().check(
        Path("app/user_store.py"),
        imports + f"\nasync def save(cursor: {annotation}, rows):\n" + indent(dedent(body), "    "),
    )
    return [finding for finding in findings if "executemany" in finding.message]


def test_flags_invariant_parameterized_execute_loop() -> None:
    findings = _executemany_findings(
        '    for row in rows:\n        await cursor.execute("INSERT INTO users (id) VALUES (%s)", (row.id,))\n'
    )
    assert len(findings) == 1
    assert findings[0].code == "SARJ560"
    assert "executemany" in findings[0].message


@pytest.mark.parametrize(
    "body",
    [
        '    for row in rows:\n        await cursor.execute("UPDATE users SET name=%s WHERE id=%s RETURNING id", (row.name, row.id))\n',
        '    for row in rows:\n        await cursor.execute("SELECT id FROM users WHERE id=%s", (row.id,))\n',
        '    for row in rows:\n        await cursor.execute(f"UPDATE {row.table} SET id=%s", (row.id,))\n',
        "    for row in rows:\n        await cursor.execute(row.sql, (row.id,))\n",
        '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (fixed,))\n',
        '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n        await cursor.fetchone()\n',
        '    for row in rows:\n        async with conn.transaction():\n            await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
        '    for row in rows:\n        try:\n            await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n        except Conflict:\n            continue\n',
        '    async for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
        '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,), prepare=False)\n',
        '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n        break\n',
    ],
)
def test_preserves_result_consumption_row_transactions_and_dynamic_queries(body: str) -> None:
    assert _executemany_findings(body) == []


def test_unproven_driver_is_excluded() -> None:
    assert (
        _executemany_findings(
            '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
            imports="from app import AsyncCursor",
        )
        == []
    )


def test_rebound_cursor_is_excluded() -> None:
    assert (
        _executemany_findings(
            '    cursor = other\n    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n'
        )
        == []
    )


def test_sync_cursor_and_import_alias() -> None:
    source = 'from psycopg import Cursor as DatabaseCursor\ndef save(cursor: DatabaseCursor, rows):\n    for row in rows:\n        cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n'
    assert len(NoPsycopgExecutionInLoop().check(Path("app/user_store.py"), source)) == 1


def test_execute_text_in_comments_is_not_sql() -> None:
    assert (
        _executemany_findings(
            '    for row in rows:\n        await cursor.execute("-- INSERT INTO users VALUES (%s)", (row.id,))\n'
        )
        == []
    )


def test_connection_execute_has_no_executemany_equivalent() -> None:
    assert (
        _executemany_findings(
            '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
            annotation="AsyncConnection",
            imports="from psycopg import AsyncConnection",
        )
        == []
    )


def test_sql_composition_wrapper_preserves_a_static_statement() -> None:
    assert (
        len(
            _executemany_findings(
                '    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
                imports="from psycopg import AsyncCursor\nfrom psycopg.sql import SQL",
            )
        )
        == 1
    )


def test_unrelated_sql_wrapper_is_not_recognized() -> None:
    assert (
        _executemany_findings(
            '    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
            imports="from psycopg import AsyncCursor\nfrom app import SQL",
        )
        == []
    )


def test_named_bound_parameters_are_supported() -> None:
    assert (
        len(
            _executemany_findings(
                '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%(id)s", {"id": row.id})\n'
            )
        )
        == 1
    )


def test_malformed_source_and_generated_source_are_excluded() -> None:
    rule = NoPsycopgExecutionInLoop()
    assert rule.check(Path("app/user_store.py"), "def save(:") == []
    assert (
        rule.check(
            Path("app/user_store.py"),
            "# @generated\n" + NoPsycopgExecutionInLoop.public_examples()[0].focus_file.source,
        )
        == []
    )


def test_locally_shadowed_sql_wrapper_is_not_a_literal_query() -> None:
    assert (
        _executemany_findings(
            '    SQL = custom_wrapper\n    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
            imports="from psycopg import AsyncCursor\nfrom psycopg.sql import SQL",
        )
        == []
    )


def test_mutated_driver_namespace_is_not_import_proof() -> None:
    assert (
        _executemany_findings(
            '    psycopg.AsyncCursor = CustomCursor\n    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
            annotation="psycopg.AsyncCursor",
            imports="import psycopg",
        )
        == []
    )


@pytest.mark.parametrize(
    "namespace",
    [
        "globals()['AsyncCursor'] = CustomCursor",
        "locals()['AsyncCursor'] = CustomCursor",
        "exec('AsyncCursor = CustomCursor')",
        "from app.custom_cursors import *",
    ],
    ids=["globals", "locals", "exec", "wildcard"],
)
def test_dynamic_driver_namespace_is_not_import_proof(namespace: str) -> None:
    assert (
        _executemany_findings(
            'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))',
            imports=f"from psycopg import AsyncCursor\n{namespace}",
        )
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        'for row in rows:\n    await cursor.execute("UPDATE users SET prior=%s WHERE id=%s", (cursor.rowcount, row.id))',
        'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\nreturn cursor.rowcount',
        'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\nreturn cursor.statusmessage',
        'for row in cursor:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))',
        'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\ninspect_cursor(cursor)',
        'alias = cursor\nfor row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\nreturn alias.rowcount',
        'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", lookup(cursor, row.id))',
    ],
    ids=["interleaved-state", "rowcount", "status", "iteration", "opaque-escape", "alias-escape", "nested-read"],
)
def test_preserves_observable_cursor_state_and_cursor_escapes(body: str) -> None:
    assert _executemany_findings(body) == []


def test_cursor_close_and_other_direct_writes_preserve_batch_candidate() -> None:
    assert (
        len(
            _executemany_findings(
                'await cursor.execute("DELETE FROM stale_users")\n'
                'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n'
                "await cursor.close()"
            )
        )
        == 1
    )


def test_shadowed_nested_cursor_state_does_not_escape_outer_cursor() -> None:
    assert (
        len(
            _executemany_findings(
                "def count(cursor):\n    return cursor.rowcount\n"
                'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))'
            )
        )
        == 1
    )
