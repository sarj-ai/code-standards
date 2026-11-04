from __future__ import annotations

from pathlib import Path

import pytest

from sarj_python_lint.sql_literals import extract_sql_literals


def _source(expression: str) -> str:
    return f"from psycopg import Connection\ndef query(conn: Connection):\n    return conn.execute({expression})\n"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("'SELECT a FROM calls'", "SELECT a FROM calls"),
        ('"""SELECT a\nFROM calls"""', "SELECT a\nFROM calls"),
        ("r\"SELECT 'value'\"", "SELECT 'value'"),
        ('u"SELECT a"', "SELECT a"),
    ],
    ids=["single-literal", "multiline-literal", "raw-literal", "unicode-prefix"],
)
def test_extracts_only_complete_psycopg_literals(expression: str, expected: str) -> None:
    extracted = extract_sql_literals(Path("store.py"), _source(expression))

    assert [item.text for item in extracted.literals] == [expected]
    assert not extracted.gaps


@pytest.mark.parametrize(
    "expression",
    [
        'f"SELECT {column} FROM calls"',
        '"SELECT a\\nFROM calls"',
        '"SELECT " "a"',
        '"SELECT " + column',
        '"SELECT {}".format(column)',
        'b"SELECT a"',
        "query_builder()",
    ],
    ids=[
        "interpolation",
        "decoded-escape",
        "implicit-concatenation",
        "dynamic-addition",
        "format-call",
        "bytes",
        "unknown-call",
    ],
)
def test_dynamic_or_unmappable_queries_are_explicitly_uncovered(expression: str) -> None:
    extracted = extract_sql_literals(Path("store.py"), _source(expression))

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_reuses_lexical_binding_proof_for_a_local_literal() -> None:
    source = (
        "from psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    statement = 'SELECT a FROM calls'\n"
        "    return conn.execute(statement)\n"
    )
    extracted = extract_sql_literals(Path("store.py"), source)

    assert [item.text for item in extracted.literals] == ["SELECT a FROM calls"]
    assert extracted.literals[0].line == 3


def test_reassigned_query_does_not_borrow_an_old_literal() -> None:
    source = (
        "from psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    statement = 'SELECT a FROM calls'\n"
        "    statement = query_builder()\n"
        "    return conn.execute(statement)\n"
    )
    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_unrelated_execute_method_is_not_a_sql_boundary() -> None:
    source = (
        "from vendor import Connection\ndef run(conn: Connection):\n    conn.execute('SELECT a UNION SELECT a, b')\n"
    )

    extracted = extract_sql_literals(Path("worker.py"), source)

    assert not extracted.literals
    assert not extracted.gaps


def test_query_supplied_through_keyword_expansion_is_explicitly_uncovered() -> None:
    source = (
        "from psycopg import Connection\ndef query(conn: Connection, parameters):\n    conn.execute(**parameters)\n"
    )

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1
    assert extracted.gaps[0].line == 3


def test_multiline_crlf_literal_keeps_source_coordinates() -> None:
    source = _source('"""SELECT a\nUNION SELECT a, b"""').replace("\n", "\r\n")

    literal = extract_sql_literals(Path("store.py"), source).literals[0]
    point = literal.source_point(line=2, column=1)

    assert (point.line, point.column) == (4, 1)


def test_unicode_before_literal_uses_codepoint_columns() -> None:
    source = (
        "from psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    label = 'é😀'; return conn.execute('SELECT a')\n"
    )

    literal = extract_sql_literals(Path("store.py"), source).literals[0]

    assert literal.column == source.splitlines()[2].index("SELECT") + 1


def test_repeated_use_of_one_literal_has_one_source_owner() -> None:
    source = (
        "from psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    statement = 'SELECT a'\n"
        "    conn.execute(statement)\n"
        "    conn.execute(statement)\n"
    )

    extracted = extract_sql_literals(Path("store.py"), source)

    assert len(extracted.literals) == 1


def test_invalid_python_does_not_report_empty_success() -> None:
    with pytest.raises(ValueError, match="invalid Python"):
        extract_sql_literals(Path("store.py"), "def broken(")
