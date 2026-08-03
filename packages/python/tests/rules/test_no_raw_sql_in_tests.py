from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_raw_sql_in_tests import NoRawSqlInTests


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/stores/test_call_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return NoRawSqlInTests().check(Path(path), source)


@pytest.mark.parametrize(
    "call",
    [
        'conn.execute("INSERT INTO call (id) VALUES (%s)", (cid,))',
        'conn.execute("insert into call (id) values (%s)", (cid,))',
        'cursor.executemany("INSERT INTO t (a) VALUES (%s)", rows)',
        'db.executescript("INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);")',
        'await pool.execute("INSERT\\nINTO batch_call (id) VALUES ($1)", bid)',
        'session.execute(text("INSERT INTO call (id) VALUES (:id)"), {"id": cid})',
        'session.execute(sa.text("INSERT INTO call (id) VALUES (:id)"))',
        'session.execute(sqlalchemy.text("INSERT INTO call (id) VALUES (:id)"))',
    ],
)
def test_flags_raw_insert_calls(call: str):
    src = f"async def test_x(conn, cursor, db, pool, session):\n    {call}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ036"
    assert "store/service" in diags[0].message


def test_flags_fstring_insert():
    src = 'async def test_x(conn):\n    await conn.execute(f"INSERT INTO {table} (id) VALUES ({cid})")\n'
    assert len(_check(src)) == 1


def test_fstring_interpolation_cannot_complete_a_sql_keyword():
    src = 'def test_x(conn):\n    conn.execute(f"INS{operation}ERT INTO call VALUES (1)")\n'
    assert _check(src) == []


def test_flags_concatenated_insert():
    src = 'def test_x(cur):\n    cur.execute("INSERT INTO " + "call (id) VALUES (1)")\n'
    assert len(_check(src)) == 1


def test_flags_multiline_insert():
    src = '''
async def test_x(conn):
    await conn.execute(
        """
        INSERT INTO call (id, status)
        VALUES ($1, $2)
        """,
        cid,
        "done",
    )
'''
    assert len(_check(src)) == 1


def test_flags_at_module_level_helper_in_test_file():
    src = 'def seed(conn):\n    conn.execute("INSERT INTO t VALUES (1)")\n'
    assert len(_check(src)) == 1


def test_message_names_the_method():
    src = 'def test_x(cur):\n    cur.executemany("INSERT INTO t VALUES (%s)", rows)\n'
    diags = _check(src)
    assert ".executemany" in diags[0].message


@pytest.mark.parametrize(
    "call",
    [
        # State assertions read the database on purpose.
        'cursor.execute("SELECT * FROM call WHERE id = %s", (call_id,))',
        'session.execute("SELECT count(*) FROM call")',
        'await conn.fetch("SELECT id FROM call")',
        'await conn.fetchrow("select * from call limit 1")',
        'await conn.fetchval("SELECT count(*) FROM call")',
        # Teardown/cleanup in the test body.
        'conn.execute("DELETE FROM call")',
        'await pool.execute("DELETE FROM batch_call WHERE id = $1", bid)',
        # Time-travel setup no store method exposes on purpose.
        "conn.execute(\"UPDATE call SET created_at = NOW() - interval '2 days'\")",
        # Advisory-lock / schema probes.
        'conn.execute("SELECT pg_try_advisory_lock(42)")',
        # asyncpg-style fetch of non-SQL helpers.
        'client.fetch_completion("Select the best answer and update the record")',
        'client.fetch_json("https://api.example.com")',
    ],
)
def test_allows_non_insert_sql(call: str):
    src = f"async def test_x(conn, cursor, pool, session, client):\n    {call}\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        "cursor.execute(\"UPDATE t SET note = 'INSERT INTO nothing' WHERE id = 1\")",
        "conn.execute(\"SELECT 'INSERT INTO nothing'\")",
        'conn.execute("SELECT 1 -- INSERT INTO nothing")',
        'conn.execute("SELECT 1 /* INSERT INTO nothing */")',
        'conn.execute("INSERT")',
        'conn.execute("insert record into the queue table")',
    ],
)
def test_allows_insert_only_in_values_comments_or_prose(call: str):
    src = f"def test_x(conn, cursor):\n    {call}\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        "conn.execute(query)",
        "conn.execute(build_query())",
        'conn.execute(query, "INSERT INTO t VALUES (1)")',
        "conn.execute(text(sql))",
        "conn.execute(text())",
        'conn.execute(other.text("INSERT INTO t VALUES (1)"))',
        'conn.execute(text("INSERT INTO t VALUES (1)", extra))',
        "conn.execute()",
        'execute("INSERT INTO t VALUES (1)")',
        'thread_pool.submit(work, "INSERT INTO t VALUES (1)")',
        'conn.run("INSERT INTO t VALUES (1)")',
        'cursor.execute("TRUNCATE call")',
        "conn.execute(\"SET timezone = 'UTC'\")",
    ],
)
def test_allows_non_matching_calls(call: str):
    src = f"def test_x(conn, cursor, thread_pool):\n    {call}\n"
    assert _check(src) == []


def test_allows_service_method_calls():
    src = """
async def test_x(store):
    call = await store.insert(make_call())
    got = await store.get(call.id)
"""
    assert _check(src) == []


_SQL_CALL = 'async def f(conn):\n    await conn.execute("INSERT INTO call (id) VALUES (1)")\n'


@pytest.mark.parametrize(
    "path",
    [
        "tests/stores/test_call_store.py",
        "test_call_store.py",
        "call_store_test.py",
        "python/app/tests/helpers/seed.py",
        "python/app/test/helpers/seed.py",
    ],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_SQL_CALL, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "python/app/app/calls/call_store.py",
        "scripts/backfill.py",
        "conftest.py",
        "tests/conftest.py",
        "python/app/tests/stores/conftest.py",
        "tests/migrations/test_0042.py",
        "migrations/0042_add_column.py",
    ],
)
def test_skips_non_test_conftest_and_migrations(path: str):
    assert _check(_SQL_CALL, path) == []


def test_multiple_hits_sorted():
    src = """
async def test_x(conn):
    await conn.execute("INSERT INTO a (id) VALUES (1)")
    await conn.execute(text("INSERT INTO b (id) VALUES (2)"))
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_col():
    src = 'def test_x(conn):\n    conn.execute("INSERT INTO a VALUES (1)")\n'
    diags = _check(src)
    assert (diags[0].line, diags[0].col) == (2, 5)


def test_reasoned_sarj_noqa_suppresses_schema_probe():
    src = (
        "def test_constraint(conn):\n"
        '    conn.execute("INSERT INTO call VALUES (1)")  '
        "# sarj-noqa: SARJ036 — assert database constraint\n"
    )
    diag = _check(src)[0]
    assert is_suppressed(src.splitlines(), diag.line, diag.code)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []
