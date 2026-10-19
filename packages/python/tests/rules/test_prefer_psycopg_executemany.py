from pathlib import Path
from textwrap import dedent, indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_psycopg_executemany import PreferPsycopgExecutemany


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(
    body: str, *, annotation: str = "AsyncCursor", imports: str = "from psycopg import AsyncCursor"
) -> list[Diagnostic]:
    return PreferPsycopgExecutemany().check(
        Path("app/user_store.py"),
        imports + f"\nasync def save(cursor: {annotation}, rows):\n" + indent(dedent(body), "    "),
    )


def test_flags_invariant_parameterized_execute_loop() -> None:
    findings = _check(
        '    for row in rows:\n        await cursor.execute("INSERT INTO users (id) VALUES (%s)", (row.id,))\n'
    )
    assert len(findings) == 1
    assert findings[0].code == "SARJ518"
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
    assert _check(body) == []


def test_unproven_driver_is_excluded() -> None:
    assert (
        _check(
            '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
            imports="from app import AsyncCursor",
        )
        == []
    )


def test_rebound_cursor_is_excluded() -> None:
    assert (
        _check(
            '    cursor = other\n    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n'
        )
        == []
    )


def test_sync_cursor_and_import_alias() -> None:
    source = 'from psycopg import Cursor as DatabaseCursor\ndef save(cursor: DatabaseCursor, rows):\n    for row in rows:\n        cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n'
    assert len(PreferPsycopgExecutemany().check(Path("app/user_store.py"), source)) == 1


def test_execute_text_in_comments_is_not_sql() -> None:
    assert (
        _check('    for row in rows:\n        await cursor.execute("-- INSERT INTO users VALUES (%s)", (row.id,))\n')
        == []
    )


def test_native_examples() -> None:
    verify_native_rule(PreferPsycopgExecutemany, analyze)


def test_connection_execute_has_no_executemany_equivalent() -> None:
    assert (
        _check(
            '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))\n',
            annotation="AsyncConnection",
            imports="from psycopg import AsyncConnection",
        )
        == []
    )


def test_sql_composition_wrapper_preserves_a_static_statement() -> None:
    assert (
        len(
            _check(
                '    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
                imports="from psycopg import AsyncCursor\nfrom psycopg.sql import SQL",
            )
        )
        == 1
    )


def test_unrelated_sql_wrapper_is_not_recognized() -> None:
    assert (
        _check(
            '    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
            imports="from psycopg import AsyncCursor\nfrom app import SQL",
        )
        == []
    )


def test_named_bound_parameters_are_supported() -> None:
    assert (
        len(
            _check(
                '    for row in rows:\n        await cursor.execute("DELETE FROM users WHERE id=%(id)s", {"id": row.id})\n'
            )
        )
        == 1
    )


def test_malformed_source_and_generated_source_are_excluded() -> None:
    rule = PreferPsycopgExecutemany()
    assert rule.check(Path("app/user_store.py"), "def save(:") == []
    assert (
        rule.check(
            Path("app/user_store.py"),
            "# @generated\n" + PreferPsycopgExecutemany.public_examples()[0].focus_file.source,
        )
        == []
    )


def test_locally_shadowed_sql_wrapper_is_not_a_literal_query() -> None:
    assert (
        _check(
            '    SQL = custom_wrapper\n    for row in rows:\n        await cursor.execute(SQL("DELETE FROM users WHERE id=%s"), (row.id,))\n',
            imports="from psycopg import AsyncCursor\nfrom psycopg.sql import SQL",
        )
        == []
    )


def test_mutated_driver_namespace_is_not_import_proof() -> None:
    assert (
        _check(
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
        _check(
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
    assert _check(body) == []


def test_cursor_close_and_other_direct_writes_preserve_batch_candidate() -> None:
    assert (
        len(
            _check(
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
            _check(
                "def count(cursor):\n    return cursor.rowcount\n"
                'for row in rows:\n    await cursor.execute("DELETE FROM users WHERE id=%s", (row.id,))'
            )
        )
        == 1
    )
