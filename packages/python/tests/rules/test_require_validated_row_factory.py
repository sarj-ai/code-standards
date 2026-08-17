from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_validated_row_factory import RequireValidatedRowFactory


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/store.py"):
    return RequireValidatedRowFactory().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        "async def load(conn):\n    async with conn.cursor() as cur:\n        row = await cur.fetchone()\n        return row[0]\n",
        "def load(conn):\n    with conn.cursor(row_factory=tuple_row) as cursor:\n        return cursor.fetchall()\n",
        "def load(conn):\n    with conn.cursor(row_factory=scalar_row) as cursor:\n        return cursor.fetchmany()\n",
    ],
)
def test_flags_fetched_cursor_without_class_row(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ414"


def test_allows_class_row_and_write_only_cursor() -> None:
    source = """
def load(conn):
    with conn.cursor(row_factory=class_row(PendingTimeRow)) as cur:
        return cur.fetchone()

def save(conn):
    with conn.cursor() as cur:
        cur.execute("UPDATE task SET ready = true")
        return cur.rowcount
"""
    assert _check(source) == []


def test_leaves_dict_row_exclusively_to_sarj013() -> None:
    source = """
def load(conn):
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return cur.fetchone()
"""
    assert _check(source) == []


def test_excludes_migrations_and_generated_code() -> None:
    source = "def load(conn):\n    with conn.cursor() as cur:\n        return cur.fetchone()\n"
    assert _check(source, "migrations/001.py") == []
    assert _check(source, "tests/test_store.py") == []
    assert _check(f"# @generated\n{source}") == []


@pytest.mark.parametrize("example", RequireValidatedRowFactory.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
