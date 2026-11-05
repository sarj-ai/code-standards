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


def _composed_source(expression: str) -> str:
    return "from psycopg.sql import SQL, Identifier\n" + _source(expression)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("SQL('SELECT a FROM calls')", "SELECT a FROM calls"),
        ("SQL('SELECT ') + SQL('a FROM calls')", "SELECT a FROM calls"),
        ("SQL('SELECT {}').format(SQL('a'))", "SELECT a"),
        ("SQL('SELECT {1}, {0}').format(SQL('a'), SQL('b'))", "SELECT b, a"),
        ("SQL('SELECT {field}').format(field=Identifier('a'))", 'SELECT "a"'),
        ("SQL('SELECT {}').format(Identifier('calls', 'id'))", 'SELECT "calls"."id"'),
        ("SQL('SELECT {}').format(Identifier('a\"b'))", 'SELECT "a""b"'),
        ("SQL('SELECT {{literal}}, {}').format(SQL('a'))", "SELECT {literal}, a"),
        (
            "SQL('SELECT {fields} FROM calls').format(fields=SQL(', ').join([Identifier('a'), Identifier('b')]))",
            'SELECT "a", "b" FROM calls',
        ),
        ("SQL('SELECT ') + SQL(', ').join((SQL('a'), SQL('b')))", "SELECT a, b"),
        ("SQL('SELECT {} UNION SELECT {}').format(SQL('a'), SQL('a, b'))", "SELECT a UNION SELECT a, b"),
    ],
)
def test_extracts_proven_psycopg_compositions(expression: str, expected: str) -> None:
    extracted = extract_sql_literals(Path("store.py"), _composed_source(expression))

    assert [literal.text for literal in extracted.literals] == [expected]
    assert not extracted.gaps


@pytest.mark.parametrize(
    "expression",
    [
        "SQL(query_builder())",
        "SQL('SELECT {field}').format(field=column)",
        "SQL('SELECT {}').format('a')",
        "SQL('SELECT {}').format(SQL('a')).format()",
        "SQL('SELECT {missing}').format(field=SQL('a'))",
        "SQL('SELECT {} {0}').format(SQL('a'))",
        "SQL('SELECT {field.name}').format(field=Identifier('a'))",
        "SQL('SELECT {0[0]}').format(SQL('a'))",
        "SQL('SELECT {!r}').format(SQL('a'))",
        "SQL('SELECT {:>10}').format(SQL('a'))",
        "SQL('SELECT {').format()",
        "SQL('SELECT ') + query_builder()",
        "SQL('SELECT ') + 'a'",
        "SQL(', ').join(fields)",
        "SQL(', ').join([SQL(field) for field in fields])",
        "SQL(', ').join(['a'])",
        "SQL(', ').join([SQL('a'), unknown])",
        "SQL('SELECT {field}').format(**fields)",
    ],
)
def test_unresolved_or_unsupported_compositions_remain_coverage_gaps(expression: str) -> None:
    extracted = extract_sql_literals(Path("store.py"), _composed_source(expression))

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_formatted_fragments_keep_their_own_source_locations() -> None:
    source = (
        "from psycopg import Connection\n"
        "from psycopg.sql import SQL\n"
        "def query(conn: Connection):\n"
        "    fields = SQL('a, b')\n"
        "    return conn.execute(SQL('SELECT {fields} UNION SELECT a').format(fields=fields))\n"
    )

    literal = extract_sql_literals(Path("store.py"), source).literals[0]
    fields = literal.source_point(line=1, column=8)
    union = literal.source_point(line=1, column=literal.text.index("UNION") + 1)

    assert literal.text == "SELECT a, b UNION SELECT a"
    assert (fields.line, fields.column) == (4, source.splitlines()[3].index("a, b") + 1)
    assert (union.line, union.column) == (5, source.splitlines()[4].index("UNION") + 1)


def test_import_aliases_retain_native_constructor_identity() -> None:
    source = (
        "from psycopg import Connection\n"
        "from psycopg.sql import SQL as Query\n"
        "def query(conn: Connection):\n"
        "    return conn.execute(Query('SELECT a'))\n"
    )

    assert extract_sql_literals(Path("store.py"), source).literals[0].text == "SELECT a"


@pytest.mark.parametrize(
    "prefix",
    [
        "from vendor import SQL\n",
        "from psycopg.sql import SQL\nSQL = custom_constructor\n",
    ],
)
def test_unproven_or_replaced_constructors_are_not_evaluated(prefix: str) -> None:
    source = prefix + _source("SQL('SELECT a')")

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def _store_source(*, mutation: str = "") -> str:
    source = (
        "from typing import ClassVar, final\n"
        "from psycopg_pool import AsyncConnectionPool\n"
        "from psycopg.sql import SQL\n"
        "@final\n"
        "class Store:\n"
        "    FIELDS: ClassVar[str] = 'a, b'\n"
        "    def __init__(self, pool: AsyncConnectionPool):\n"
        "        self.pool = pool\n"
        "# EXTRA_METHODS\n"
        "    async def query(self):\n"
        "        async with self.pool.connection() as conn:\n"
        "            await conn.execute(SQL('SELECT {} FROM calls').format(SQL(self.FIELDS)))\n"
    )
    return source.replace("# EXTRA_METHODS\n", mutation)


def test_stable_annotated_class_fields_are_resolved() -> None:
    extracted = extract_sql_literals(Path("store.py"), _store_source())

    assert [literal.text for literal in extracted.literals] == ["SELECT a, b FROM calls"]
    assert not extracted.gaps


def test_stable_unannotated_class_fields_are_resolved() -> None:
    source = _store_source().replace("FIELDS: ClassVar[str]", "FIELDS")

    extracted = extract_sql_literals(Path("store.py"), source)

    assert [literal.text for literal in extracted.literals] == ["SELECT a, b FROM calls"]
    assert not extracted.gaps


def test_instance_attribute_writes_disable_class_constant_recovery() -> None:
    source = _store_source(mutation="    def change(self, value):\n        self.FIELDS = value\n")

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


@pytest.mark.parametrize(
    "change",
    [
        "unsealed",
        "base",
        "attribute-hook",
        "dynamic-write",
        "escaped-receiver",
    ],
)
def test_uncertain_class_attribute_lookup_stays_uncovered(change: str) -> None:
    source = _store_source()
    match change:
        case "unsealed":
            source = source.replace("@final\n", "")
        case "base":
            source = source.replace("class Store:", "class Store(Base):")
        case "attribute-hook":
            source = _store_source(mutation="    def __getattribute__(self, name):\n        return 'dynamic'\n")
        case "dynamic-write":
            source += "setattr(Store, 'FIELDS', unknown)\n"
        case _:
            source = _store_source(mutation="    def escape(self):\n        unknown(self)\n")

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_long_join_alias_chain_stays_bounded() -> None:
    source = "from psycopg.sql import SQL, Identifier\nfrom psycopg import Connection\n"
    source += "items0 = [Identifier('id')]\n"
    source += "".join(f"items{index} = items{index - 1}\n" for index in range(1, 40))
    source += "def query(conn: Connection):\n    conn.execute(SQL(', ').join(items39))\n"

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "items.append(Identifier('extra'))",
        "alias = items; alias.clear()",
        "unknown(items)",
    ],
)
def test_join_does_not_recover_mutated_or_escaped_members(mutation: str) -> None:
    source = (
        "from psycopg.sql import SQL, Identifier\nfrom psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    items = [Identifier('id')]\n"
        f"    {mutation}\n"
        "    conn.execute(SQL(', ').join(items))\n"
    )

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_composable_alias_does_not_hide_private_object_mutation() -> None:
    source = (
        "from psycopg.sql import SQL\nfrom psycopg import Connection\n"
        "def query(conn: Connection):\n"
        "    statement = SQL('SELECT a')\n"
        "    statement._obj = unknown\n"
        "    conn.execute(statement)\n"
    )

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_excessive_escaped_format_parts_stay_uncovered() -> None:
    template = "SELECT '" + "{{" * 4097 + "'"
    expression = f"SQL({template!r}).format()"

    extracted = extract_sql_literals(Path("store.py"), _composed_source(expression))

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_escaped_class_object_does_not_supply_a_stale_literal() -> None:
    source = _store_source().replace("SQL(self.FIELDS)", "SQL(Store.FIELDS)")
    source += "unknown(Store)\n"

    extracted = extract_sql_literals(Path("store.py"), source)

    assert not extracted.literals
    assert len(extracted.gaps) == 1


def test_render_work_budget_is_reset_for_each_execution() -> None:
    fragment = "x" * 750_000
    arguments = ", ".join(f"SQL({fragment!r})" for _ in range(3))
    source = _composed_source(f"SQL('SELECT 1').format({arguments})")
    source += "def another(conn: Connection):\n    return conn.execute(SQL('SELECT 2'))\n"

    extracted = extract_sql_literals(Path("store.py"), source)

    assert [literal.text for literal in extracted.literals] == ["SELECT 2"]
    assert len(extracted.gaps) == 1
