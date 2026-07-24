from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_raw_sql_in_tests import NoRawSqlInTests


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/stores/test_call_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return NoRawSqlInTests().check(Path(path), source)


# --------------------------------------------------------------------------- #
# Positive: raw SQL literals through execute/fetch in tests.                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        'cursor.execute("SELECT * FROM call WHERE id = %s", (call_id,))',
        'conn.execute("insert into call (id) values (%s)", (cid,))',
        'db.execute("UPDATE call SET status = \'done\'")',
        'conn.execute("DELETE FROM call")',
        'cursor.executemany("INSERT INTO t (a) VALUES (%s)", rows)',
        'await conn.fetch("SELECT id FROM call")',
        'await conn.fetchrow("select * from call limit 1")',
        'await conn.fetchval("SELECT count(*) FROM call")',
        'await pool.execute("DELETE FROM batch_call")',
        'session.execute("SELECT 1 FROM call")',
    ],
)
def test_flags_raw_sql_calls(call: str):
    src = f"async def test_x(conn, cursor, db, pool, session):\n    {call}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ036"
    assert "store/service" in diags[0].message


def test_flags_fstring_sql():
    src = 'async def test_x(conn):\n    await conn.execute(f"DELETE FROM call WHERE id = {cid}")\n'
    assert len(_check(src)) == 1


def test_flags_concatenated_sql():
    src = 'def test_x(cur):\n    cur.execute("SELECT id " + "FROM call")\n'
    assert len(_check(src)) == 1


def test_flags_multiline_sql():
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


# --------------------------------------------------------------------------- #
# Negative: keyword only inside quoted values / comments / identifiers.        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "cursor.execute(\"SET search_path TO 'select'\")",
        'conn.execute("SET x = \'please delete me\'")',
        'store.fetch_by_name("select_option")',
        'obj.fetch_config("update_strategy")',
        'conn.execute("NOTIFY channel, \'update ready\'")',
    ],
)
def test_allows_keyword_only_in_values_or_identifiers(call: str):
    src = f"def test_x(conn, cursor, store, obj):\n    {call}\n"
    assert _check(src) == []


def test_allows_keyword_only_in_sql_comment():
    src = 'def test_x(conn):\n    conn.execute("SET x = 1 -- select nothing")\n'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: non-literal / non-SQL arguments and other call shapes.             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "conn.execute(query)",
        "conn.execute(build_query())",
        "conn.execute(text(sql))",
        "conn.execute()",
        'execute("SELECT 1")',
        'thread_pool.submit(work, "SELECT 1")',
        'conn.run("SELECT 1")',
        'cursor.execute("TRUNCATE call")',
        'conn.execute("SET timezone = \'UTC\'")',
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


# --------------------------------------------------------------------------- #
# Path gating: tests only; conftest + migrations allowlisted.                  #
# --------------------------------------------------------------------------- #


_SQL_CALL = 'async def f(conn):\n    await conn.execute("DELETE FROM call")\n'


@pytest.mark.parametrize(
    "path",
    [
        "tests/stores/test_call_store.py",
        "test_call_store.py",
        "call_store_test.py",
        "python/bulbul/tests/helpers/seed.py",
    ],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_SQL_CALL, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "python/bulbul/bulbul/calls/call_store.py",
        "scripts/backfill.py",
        "conftest.py",
        "tests/conftest.py",
        "python/bulbul/tests/stores/conftest.py",
        "tests/migrations/test_0042.py",
        "migrations/0042_add_column.py",
    ],
)
def test_skips_non_test_conftest_and_migrations(path: str):
    assert _check(_SQL_CALL, path) == []


# --------------------------------------------------------------------------- #
# Counts, ordering, edge cases.                                                #
# --------------------------------------------------------------------------- #


def test_multiple_hits_sorted():
    src = """
async def test_x(conn):
    await conn.execute("DELETE FROM a")
    await conn.fetch("SELECT * FROM b")
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_col():
    src = 'def test_x(conn):\n    conn.execute("DELETE FROM a")\n'
    diags = _check(src)
    assert (diags[0].line, diags[0].col) == (2, 5)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []
