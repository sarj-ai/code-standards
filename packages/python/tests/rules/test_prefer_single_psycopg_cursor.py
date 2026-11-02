from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_single_psycopg_cursor import PreferSinglePsycopgCursor


P = Path("app/store.py")


def test_documented_examples() -> None:
    verify_native_rule(PreferSinglePsycopgCursor, analyze)


def test_repeated_cursor_scopes_in_injected_store_warn_once() -> None:
    source = "from psycopg_pool import AsyncConnectionPool\nclass Store:\n    def __init__(self, pool: AsyncConnectionPool): self.pool = pool\n    async def load(self):\n        async with self.pool.connection() as conn:\n            async with conn.cursor() as cursor:\n                await cursor.execute('SELECT id FROM item')\n            async with conn.cursor() as cursor:\n                await cursor.execute('SELECT id FROM other')\n            async with conn.cursor() as cursor:\n                await cursor.execute('SELECT id FROM third')\n"
    [finding] = PreferSinglePsycopgCursor().check(P, source)
    assert finding.code == "SARJ561"
    assert finding.line == 8


@pytest.mark.parametrize(
    "source",
    [
        "def load(client):\n    client.cursor()\n    client.cursor()\n",
        "from psycopg import Connection\ndef load(conn: Connection):\n    conn.cursor()\ndef other(conn: Connection):\n    conn.cursor()\n",
        "from psycopg import Connection\ndef load(conn: Connection):\n    conn.cursor()\n    def other():\n        conn.cursor()\n",
        "from psycopg import Connection\ndef load(conn: Connection):\n    if ready:\n        conn.cursor()\n    else:\n        conn.cursor()\n",
        "from psycopg import Connection\ndef load(conn: Connection):\n    conn.cursor()\n    conn = other\n    conn.cursor()\n",
    ],
)
def test_unknown_separate_or_mutually_exclusive_cursor_owners(source: str) -> None:
    assert PreferSinglePsycopgCursor().check(P, source) == []


def test_suppression_and_generated_sources() -> None:
    source = "from psycopg import Connection\ndef load(conn: Connection):\n    conn.cursor()\n    conn.cursor()  # sarj-noqa: SARJ561 -- preserve independent pipeline result sets\n"
    assert PreferSinglePsycopgCursor().check(P, source) == []
    assert PreferSinglePsycopgCursor().check(P, "# Code generated. DO NOT EDIT.\n" + source) == []
    assert PreferSinglePsycopgCursor().check(P, "def (") == []
