from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._store_sql import store_queries
from sarj_python_lint.rules.prefer_application_model_joins import PreferApplicationModelJoins


P = Path("app/item_store.py")


def _source(query: str) -> str:
    return f"""from psycopg import AsyncCursor
async def load(cursor: AsyncCursor):
    await cursor.execute({query!r}, (1,))
"""


def _check(query: str):
    return PreferApplicationModelJoins().check(P, _source(query))


def test_documented_examples() -> None:
    verify_native_rule(PreferApplicationModelJoins, analyze)


@pytest.mark.parametrize("join", ["JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "CROSS JOIN", "NATURAL JOIN"])
def test_cross_relation_joins(join: str) -> None:
    condition = "" if join in {"CROSS JOIN", "NATURAL JOIN"} else " ON b.id=a.owner_id"
    query = f"SELECT a.id,b.name FROM item a {join} person b{condition} WHERE a.id=%s"  # ruff: ignore[hardcoded-sql-expression] -- parser input, never executed.
    [finding] = _check(query)
    assert finding.code == "SARJ545"
    assert finding.severity is Severity.WARNING
    assert "snapshot" in finding.message
    assert "locks" in finding.message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM item a JOIN item b ON a.parent_id=b.id",
        'SELECT a.id FROM "item" a JOIN item b ON a.parent_id=b.id',
        "SELECT a.id FROM public.item a JOIN item b ON a.parent_id=b.id",
        "WITH other AS (SELECT * FROM person) SELECT a.id FROM item a JOIN other b ON b.id=a.id",
        "SELECT a.id FROM item a JOIN (SELECT id FROM person) b ON b.id=a.owner_id",
        "SELECT a.id FROM item a JOIN person_func() b ON b.id=a.owner_id",
        "SELECT 'JOIN person ON TRUE' FROM item",
        "SELECT id FROM item /* JOIN person ON TRUE */",
        "SELECT * FROM item JOIN",
    ],
)
def test_unknown_or_same_relation_ownership_is_preserved(query: str) -> None:
    assert _check(query) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM item a, person b WHERE a.owner_id=b.id",
        "SELECT a.id FROM public.item a JOIN other.item b ON b.id=a.id",
        'SELECT a.id FROM item a JOIN "Item" b ON b.id=a.id',
        "WITH other AS (SELECT a.id FROM item a JOIN person b ON b.id=a.id) SELECT id FROM other",
        "SELECT id FROM item WHERE EXISTS (SELECT a.id FROM item a JOIN person b ON a.id=b.id)",
    ],
)
def test_comma_schema_case_and_nested_direct_boundaries(query: str) -> None:
    assert len(_check(query)) == 1


def test_composed_projection_and_module_constant_keep_one_diagnostic() -> None:
    source = """from psycopg import AsyncCursor
from psycopg.sql import SQL
QUERY = SQL('SELECT {fields} FROM item a JOIN person b ON a.owner_id=b.id FOR UPDATE OF a')
async def load(cursor: AsyncCursor):
    await cursor.execute(QUERY.format(fields=SQL('a.id, b.name')))
    await cursor.execute(QUERY.format(fields=SQL('a.id, b.name')))
"""
    assert len(PreferApplicationModelJoins().check(P, source)) == 1


def test_dynamic_relation_is_not_a_model_boundary() -> None:
    source = """from psycopg import AsyncCursor
from psycopg.sql import SQL
async def load(cursor: AsyncCursor, relation):
    await cursor.execute(SQL('SELECT * FROM item JOIN {relation} ON TRUE').format(relation=relation))
"""
    assert PreferApplicationModelJoins().check(P, source) == []


def test_keyword_query_and_alias_cursor() -> None:
    source = """from psycopg import AsyncCursor as NativeCursor
async def load(cursor: NativeCursor):
    alias = cursor
    await alias.execute(query='SELECT a.id FROM item a JOIN person b ON b.id=a.owner_id')
"""
    assert len(PreferApplicationModelJoins().check(P, source)) == 1


@pytest.mark.parametrize("prefix", ["# Code generated. DO NOT EDIT.\n", ""])
def test_generated_and_test_sources_are_excluded(prefix: str) -> None:
    source = prefix + _source("SELECT a.id FROM item a JOIN person b ON TRUE")
    path = P if prefix else Path("tests/test_item_store.py")
    assert PreferApplicationModelJoins().check(path, source) == []


def test_unrelated_execute_method_and_prose_are_excluded() -> None:
    source = """class Other:
    def execute(self, query): pass
client = Other()
client.execute('SELECT a.id FROM item a JOIN person b ON TRUE')
"""
    assert PreferApplicationModelJoins().check(P, source) == []


def test_malformed_repeated_relation_alias_does_not_prove_two_model_owners() -> None:
    assert _check("SELECT a.id FROM item a JOIN person a ON TRUE") == []


def test_unquoted_non_ascii_relation_folding_needs_database_encoding() -> None:
    assert _check('SELECT a.id FROM Ä a JOIN "Ä" b ON TRUE') == []
    assert len(_check('SELECT a.id FROM "Ä" a JOIN "ä" b ON TRUE')) == 1


@pytest.mark.parametrize(
    "query",
    [
        "WITH ITEM AS (SELECT id FROM person) SELECT a.id FROM item a JOIN person b ON TRUE",
        "WITH other AS (SELECT id FROM person) SELECT a.id FROM item a JOIN OTHER b ON TRUE",
        'WITH "item" AS (SELECT id FROM person) SELECT a.id FROM ITEM a JOIN person b ON TRUE',
        "WITH X AS (SELECT id FROM item), Y AS (SELECT id FROM person) SELECT a.id FROM x a JOIN y b ON TRUE",
        "SELECT a.id FROM item A JOIN person a ON TRUE",
        'SELECT a.id FROM item "a" JOIN person A ON TRUE',
    ],
)
def test_postgres_identifier_folding_keeps_ctes_and_duplicate_aliases_unknown(query: str) -> None:
    assert _check(query) == []


@pytest.mark.parametrize(
    "query",
    [
        'WITH "ITEM" AS (SELECT id FROM person) SELECT a.id FROM item a JOIN person b ON TRUE',
        "WITH ITEM AS (SELECT id FROM person) SELECT a.id FROM public.item a JOIN public.person b ON TRUE",
        'SELECT a.id FROM item "A" JOIN person a ON TRUE',
        "SELECT a.id FROM ITEM a JOIN PERSON b ON TRUE",
    ],
)
def test_folding_preserves_quoted_and_schema_distinct_physical_relations(query: str) -> None:
    assert len(_check(query)) == 1


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("x" * 63 + "a", "x" * 63 + "b", 0),
        ("x" * 62 + "a", "x" * 62 + "b", 1),
        ("é" * 31 + "aa", "é" * 31 + "ab", 0),
        ("é" * 31 + "a", "é" * 31 + "b", 1),
        ("bad\ud800", "person", 0),
    ],
)
def test_overlength_or_invalid_identifier_identity_abstains(left: str, right: str, expected: int) -> None:
    query = f'SELECT a.id FROM "{left}" a JOIN "{right}" b ON TRUE'  # ruff: ignore[hardcoded-sql-expression] -- parser input, never executed.
    assert len(_check(query)) == expected


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM item " + "x" * 63 + "a JOIN person " + "x" * 63 + "b ON TRUE",
        "WITH " + "x" * 63 + "a AS (SELECT id FROM person) SELECT a.id FROM " + "x" * 63 + " a JOIN person b ON TRUE",
    ],
)
def test_overlength_aliases_and_cte_names_do_not_establish_physical_owners(query: str) -> None:
    assert _check(query) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM item " + "x" * 62 + "a JOIN person " + "x" * 62 + "b ON TRUE",
        "WITH " + "x" * 62 + "a AS (SELECT id FROM person) SELECT a.id FROM item a JOIN person b ON TRUE",
    ],
)
def test_supported_length_alias_and_cte_boundaries_remain_reviewable(query: str) -> None:
    assert len(_check(query)) == 1


def test_scope_normalization_preserves_shared_cached_query() -> None:
    query = "WITH ITEM AS (SELECT id FROM person) SELECT a.id FROM item a JOIN person b ON TRUE"
    context = PythonFileContext(P, _source(query))
    queries = tuple(store_queries(context))
    before = [item.statement.sql() for item in queries]
    assert PreferApplicationModelJoins().check_context(context) == []
    assert [item.statement.sql() for item in queries] == before
