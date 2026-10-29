from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_redundant_sql_alias import NoRedundantSqlAlias


P = Path("app/call_store.py")


def _source(query: str) -> str:
    return f"from psycopg.sql import SQL\nQUERY = SQL({query!r})\n"


def test_documented_examples() -> None:
    verify_native_rule(NoRedundantSqlAlias, analyze)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM call AS call",
        "SELECT id FROM call call",
        'SELECT id FROM "call" AS call',
        'SELECT id FROM call AS "call"',
        "SELECT id FROM public.call AS call",
        "SELECT id AS id FROM call",
        "SELECT call.id AS id FROM call",
        'SELECT "Id" AS "Id" FROM call',
        "SELECT id AS id, name AS name FROM call AS call",
        "SELECT {fields} FROM call AS call",
    ],
)
def test_exact_identifier_repetition(query: str) -> None:
    assert len(NoRedundantSqlAlias().check(P, _source(query))) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM call AS c",
        "SELECT id AS call_id FROM call",
        'SELECT id AS "Id" FROM call',
        'SELECT id FROM "Call" AS call',
        "SELECT id::text AS id FROM call",
        "SELECT LOWER(name) AS name FROM call",
        "SELECT * FROM call AS call(call_id)",
        "SELECT id FROM (SELECT id FROM call) AS call",
        "SELECT 'x AS x' FROM call",
        "SELECT id FROM call /* call AS call */",
        "SELECT id FROM call -- call AS call\n",
        "SELECT id FROM call WHERE id = $text$ FROM call AS call $text$",
        "SELECT Ä AS ä FROM call",
        "SELECT id FROM Ä AS ä",
        "SELECT (",
    ],
)
def test_distinct_roles_and_contracts_remain(query: str) -> None:
    assert NoRedundantSqlAlias().check(P, _source(query)) == []


def test_plain_execution_and_bound_local_query() -> None:
    source = 'import psycopg\ndef read(cursor: psycopg.Cursor):\n    query = "SELECT id AS id FROM call"\n    cursor.execute(query)\n'
    assert len(NoRedundantSqlAlias().check(P, source)) == 1


def test_unrelated_sql_like_string_is_ignored() -> None:
    assert NoRedundantSqlAlias().check(P, 'text = "SELECT id FROM call AS call"\n') == []


def test_shadowed_constructor_is_not_proven() -> None:
    assert (
        NoRedundantSqlAlias().check(
            P, 'from psycopg.sql import SQL\nSQL = print\nQUERY = SQL("SELECT id AS id FROM call")\n'
        )
        == []
    )


def test_mutated_constructor_is_not_proven() -> None:
    source = 'from psycopg.sql import SQL\nSQL.__new__ = custom\nQUERY = SQL("SELECT id AS id FROM call")\n'
    assert NoRedundantSqlAlias().check(P, source) == []


def test_exact_code_suppression() -> None:
    source = 'from psycopg.sql import SQL\nQUERY = SQL("SELECT id AS id FROM call")  # sarj-noqa: SARJ543 -- external generator preserves this alias\n'
    assert NoRedundantSqlAlias().check(P, source) == []


def test_generated_source_is_ignored() -> None:
    assert NoRedundantSqlAlias().check(Path("generated/call_store.py"), _source("SELECT id AS id FROM call")) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT {column} AS {output} FROM call",
        "SELECT {column} AS {column} FROM call",
        "SELECT id FROM {relation} AS {role}",
        "SELECT id FROM {relation} AS {relation}",
        'SELECT "prefix{column}" AS "prefix{output}" FROM call',
        'SELECT id FROM "prefix{relation}" AS "prefix{role}"',
    ],
)
def test_unresolved_identifiers_do_not_prove_redundancy(query: str) -> None:
    assert NoRedundantSqlAlias().check(P, _source(query)) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT {relation}.id AS id FROM {relation}",
        "SELECT id AS id FROM {relation}",
        "SELECT {column} FROM call AS call",
        "SELECT {column} AS {output}, id AS id FROM call",
        "SELECT {column} AS {output} FROM call AS call",
    ],
)
def test_unresolved_identifiers_preserve_independent_static_matches(query: str) -> None:
    assert len(NoRedundantSqlAlias().check(P, _source(query))) == 1


@pytest.mark.parametrize(
    "query",
    [
        'f"SELECT {column} AS {output} FROM call"',
        'f"SELECT id FROM {relation} AS {role}"',
    ],
)
def test_constructor_fstring_identifiers_are_unresolved(query: str) -> None:
    source = f"from psycopg.sql import SQL\nQUERY = SQL({query})\n"
    assert NoRedundantSqlAlias().check(P, source) == []


@pytest.mark.parametrize(
    "expression",
    [
        'f"SELECT {column} AS {output} FROM call"',
        '"SELECT {column} AS {output} FROM call".format(column=column, output=output)',
        'SQL("SELECT {column} AS {output} FROM call").format(column=column, output=output)',
        'f"SELECT id FROM {relation} AS {role}"',
        '"SELECT id FROM {relation} AS {role}".format(relation=relation, role=role)',
        'SQL("SELECT id FROM {relation} AS {role}").format(relation=relation, role=role)',
    ],
)
def test_execution_wrappers_preserve_unresolved_identity(expression: str) -> None:
    source = (
        "import psycopg\nfrom psycopg.sql import SQL\n"
        "def read(cursor: psycopg.Cursor, column, output, relation, role):\n"
        f"    cursor.execute({expression})\n"
    )
    assert NoRedundantSqlAlias().check(P, source) == []


@pytest.mark.parametrize(
    "expression",
    [
        'f"SELECT id AS id FROM {relation}"',
        '"SELECT id AS id FROM {relation}".format(relation=relation)',
        'SQL("SELECT id AS id FROM {relation}").format(relation=relation)',
        'f"SELECT {column} FROM call AS call"',
        '"SELECT {column} FROM call AS call".format(column=column)',
        'SQL("SELECT {column} FROM call AS call").format(column=column)',
    ],
)
def test_execution_wrappers_preserve_static_matches(expression: str) -> None:
    source = (
        "import psycopg\nfrom psycopg.sql import SQL\n"
        "def read(cursor: psycopg.Cursor, column, relation):\n"
        f"    cursor.execute({expression})\n"
    )
    assert len(NoRedundantSqlAlias().check(P, source)) == 1
