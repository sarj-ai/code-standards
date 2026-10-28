from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._store_sql import store_queries
from sarj_python_lint.rules.store_insert_requires_explicit_conflict_policy import (
    StoreInsertRequiresExplicitConflictPolicy,
)


P = Path("app/item_store.py")


def _source(query: str, *, name: str = "insert") -> str:
    return f"""from psycopg import AsyncCursor
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor
    async def {name}(self):
        await self.cursor.execute({query!r}, (1,))
"""


def test_documented_examples() -> None:
    verify_native_rule(StoreInsertRequiresExplicitConflictPolicy, analyze)


@pytest.mark.parametrize("name", ["insert", "create", "upsert", "write", "append"])
def test_ordinary_store_insert_methods_declare_policy(name: str) -> None:
    findings = StoreInsertRequiresExplicitConflictPolicy().check(
        P, _source("INSERT INTO item(id) VALUES(%s)", name=name)
    )
    assert len(findings) == 1
    assert findings[0].code == "SARJ547"
    assert findings[0].severity.value == "warning"


@pytest.mark.parametrize(
    "clause",
    [
        "ON CONFLICT DO NOTHING",
        "ON CONFLICT(id) DO UPDATE SET id=EXCLUDED.id",
        "ON CONFLICT ON CONSTRAINT item_pkey DO NOTHING",
    ],
)
def test_explicit_duplicate_contract(clause: str) -> None:
    query = f"INSERT INTO item(id) VALUES(%s) {clause}"
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, _source(query)) == []


def test_fixture_query_forwarder_is_not_excluded() -> None:
    source = """from psycopg_pool import AsyncConnectionPool
class RowsFixture:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool=pool
    async def insert(self):
        return await self._fetch_one('INSERT INTO item(id) VALUES(%s) RETURNING id', (1,))
    async def _fetch_one(self, query, params):
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(query, params)
            return await cursor.fetchone()
"""
    findings = StoreInsertRequiresExplicitConflictPolicy().check(Path("tests/fixtures/rows.py"), source)
    assert len(findings) == 1
    assert findings[0].line == 6


def test_replay_rule_has_precedence_for_its_existing_scope() -> None:
    source = _source("INSERT INTO item(id) VALUES(%s)", name="ensure")
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []
    assert len(StoreInsertRequiresExplicitConflictPolicy().check(Path("tests/fixtures/rows.py"), source)) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 'INSERT INTO item(id) VALUES(%s)'",
        "UPDATE item SET id=%s",
        "INSERT INTO",
        "-- INSERT INTO item(id) VALUES(%s)\nSELECT 1",
    ],
)
def test_non_insert_malformed_and_quoted_text_do_not_match(query: str) -> None:
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, _source(query)) == []


def test_one_finding_for_multiple_inserts_in_one_source_expression() -> None:
    source = _source("INSERT INTO item(id) VALUES(%s); INSERT INTO item(id) VALUES(%s)")
    assert len(StoreInsertRequiresExplicitConflictPolicy().check(P, source)) == 1


def test_unknown_native_receiver_and_unexecuted_constant_are_not_database_facts() -> None:
    source = """from psycopg import AsyncCursor
QUERY='INSERT INTO item(id) VALUES(%s)'
class Other:
    async def write(self, cursor):
        await cursor.execute(QUERY, (1,))
"""
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []


def test_dynamic_sql_cannot_manufacture_an_insert_target() -> None:
    source = """from psycopg import AsyncCursor
async def insert(cursor: AsyncCursor, query):
    await cursor.execute(query)
"""
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []


def test_exact_suppression_in_public_pipeline(tmp_path: Path) -> None:
    target = tmp_path / "item_store.py"
    source = _source("INSERT INTO item(id) VALUES(%s)")
    target.write_text(source)
    assert len(analyze([StoreInsertRequiresExplicitConflictPolicy.id], [target])) == 1
    target.write_text(source.rstrip() + "  # sarj-noqa: SARJ547 -- fixture deliberately tests duplicate rejection\n")
    assert analyze([StoreInsertRequiresExplicitConflictPolicy.id], [target]) == []


def test_sql_constructor_mutation_invalidates_native_composition_proof() -> None:
    source = """from psycopg import AsyncCursor
from psycopg.sql import SQL
SQL.__new__ = custom
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor=cursor
    async def insert(self):
        await self.cursor.execute(SQL('INSERT INTO item(id) VALUES(%s)'))
"""
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []


def test_dynamic_target_keeps_unresolved_relation_policy() -> None:
    source = """from psycopg import AsyncCursor
from psycopg.sql import SQL
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor=cursor
    async def insert(self, target):
        await self.cursor.execute(SQL('INSERT INTO {target}(id) VALUES(%s)').format(target=target))
"""
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []


def test_shared_query_cache_is_local_to_the_file_context() -> None:
    context = PythonFileContext(P, _source("INSERT INTO item(id) VALUES(%s)"))
    first = tuple(store_queries(context))
    second = tuple(store_queries(context))
    assert len(first) == 1
    assert first[0] is second[0]
    other = PythonFileContext(P, _source("INSERT INTO item(id) VALUES(%s) ON CONFLICT DO NOTHING"))
    assert next(iter(store_queries(other))) is not first[0]


def test_instance_method_replacement_invalidates_query_forwarder_proof() -> None:
    source = """from psycopg import AsyncCursor
class ItemStore:
    def __init__(self, cursor: AsyncCursor, callback):
        self.cursor=cursor
        self._fetch_one=callback
    async def insert(self):
        return await self._fetch_one('INSERT INTO item(id) VALUES(%s)', (1,))
    async def _fetch_one(self, query, params):
        await self.cursor.execute(query, params)
"""
    assert StoreInsertRequiresExplicitConflictPolicy().check(P, source) == []
