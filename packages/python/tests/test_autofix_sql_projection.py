from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_RULE = "no-select-star"
_PATH = Path("app/literal_rows.py")
_QUERY = 'SELECT * FROM (VALUES (1, 2)) AS "authored"("a", "b")'


def _authored_source() -> str:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix")
    return example.files[0].source


def _source(query: str) -> str:
    return _authored_source().replace(_QUERY, query)


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("query", "projection"),
    [
        (_QUERY, '"authored"."a", "authored"."b"'),
        ('SELECT * FROM (VALUES (0)) AS "select"("from");', '"select"."from"'),
        ('select * from (values (999999999)) as "A"("MixedCase")', '"A"."MixedCase"'),
        (
            'SELECT\t*\tFROM\t(VALUES (1,2,3,4,5,6,7,8)) AS "r"("a","b","c","d","e","f","g","h")',
            ", ".join(f'"r"."{name}"' for name in "abcdefgh"),
        ),
        (
            'SELECT * FROM (VALUES (1)) AS "r"("c")'.replace('"r"', '"' + "r" * 63 + '"').replace(
                '"c"', '"' + "c" * 63 + '"'
            ),
            '"' + "r" * 63 + '"."' + "c" * 63 + '"',
        ),
        ('SELECT * FROM (VALUES (000000001, 2)) AS "r"("A", "a")', '"r"."A", "r"."a"'),
    ],
)
def test_owned_postgres_literal_expands_only_the_authored_star(ending: str, query: str, projection: str) -> None:
    source = _source(query).replace("\n", ending)
    expected = source.replace("*", projection)
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 1
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source) == expected
    assert not REGISTRY[_RULE]().check(_PATH, expected)
    assert fix_source(_PATH, expected, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    original_tree = ast.parse(source)
    fixed_tree = ast.parse(expected)
    original_literals = [node for node in ast.walk(original_tree) if isinstance(node, ast.Constant)]
    fixed_literals = [node for node in ast.walk(fixed_tree) if isinstance(node, ast.Constant)]
    assert len(original_literals) == len(fixed_literals) == 1
    original_literals[0].value = fixed_literals[0].value
    assert ast.dump(original_tree) == ast.dump(fixed_tree)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM (VALUES (1, 2)) AS authored(a, b)",
        'SELECT * FROM (VALUES (1, 2)) AS "r"("a", "a")',
        'SELECT * FROM (VALUES (1, 2)) AS "r"("a")',
        'SELECT * FROM (VALUES (1)) AS "r"("a", "b")',
        'SELECT * FROM (VALUES (1), (2)) AS "r"("a")',
        'SELECT * FROM (VALUES (-1)) AS "r"("a")',
        'SELECT * FROM (VALUES (+1)) AS "r"("a")',
        'SELECT * FROM (VALUES (1.0)) AS "r"("a")',
        'SELECT * FROM (VALUES (1e0)) AS "r"("a")',
        'SELECT * FROM (VALUES (1000000000)) AS "r"("a")',
        'SELECT * FROM (VALUES (NULL)) AS "r"("a")',
        'SELECT * FROM (VALUES (abs(1))) AS "r"("a")',
        'SELECT * FROM (VALUES (1::int)) AS "r"("a")',
        'SELECT * FROM (VALUES (1)) AS "r"("a") WHERE true',
        _QUERY + "; SELECT 1",
        _QUERY + ' CROSS JOIN (VALUES (3)) AS "s"("c")',
        _QUERY.replace("SELECT *", "SELECT /* authored */ *"),
        _QUERY.replace("SELECT *", "SELECT -- authored\\n*"),
        'SELECT * FROM (VALUES (1)) AS "r"("a")'.replace('"r"', '"' + "r" * 64 + '"'),
        'SELECT * FROM (VALUES (1)) AS "r"("c")'.replace('"c"', '"' + "c" * 64 + '"'),
        'SELECT * FROM (VALUES (1,2,3,4,5,6,7,8,9)) AS "r"("a","b","c","d","e","f","g","h","i")',
        _QUERY + " " * 2048,
        _QUERY.replace('"authored"', '"é"'),
        _QUERY.replace('"a"', '"a""b"'),
    ],
    ids=[
        "unquoted-relation-and-labels",
        "duplicate-column-labels",
        "fewer-labels-than-values",
        "more-labels-than-values",
        "multiple-values-rows",
        "negative-literal",
        "unary-plus-literal",
        "decimal-literal",
        "exponent-literal",
        "oversized-integer",
        "null-literal",
        "function-expression",
        "cast-expression",
        "where-clause",
        "second-statement",
        "joined-relation",
        "block-comment",
        "line-comment",
        "relation-identifier-too-long",
        "column-identifier-too-long",
        "too-many-column-values",
        "query-length-limit",
        "unicode-relation-identifier",
        "escaped-quote-in-label",
    ],
)
def test_sql_outside_the_complete_closed_relation_stays_manual(query: str) -> None:
    source = _source(query)
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("from psycopg import Connection", "from other import Connection"),
        ("from psycopg import Connection", "from psycopg import Connection as Connection"),
        ("def literal_rows():", "def literal_rows(Connection):"),
        ("def literal_rows():", "@decorate\ndef literal_rows():"),
        ("def literal_rows():", "def literal_rows[T]():"),
        ("def literal_rows():", "def literal_rows() -> list:"),
        ("def literal_rows():", "def Connection():"),
        ("def literal_rows():", "async def literal_rows():"),
        ("Connection.connect()", "Connection.connect(row_factory=custom)"),
        ("Connection.connect()", "Connection.connect('service=other')"),
        ("Connection.connect()", "Connection.connect(cursor_factory=custom)"),
        ("Connection.connect()", "factory.connect()"),
        (" as connection:", " as Connection:"),
        (" as connection:", " as literal_rows:"),
        ("    with ", "    global Connection\n    with "),
        ("        return ", "        observer(connection)\n        return "),
        ("        return ", "        query = 'observer'\n        return "),
        ("connection.execute(", "other.execute("),
        (".fetchall()", ".fetchone()"),
        (".fetchall()", ".fetchall(extra=True)"),
        (".fetchall()", ".fetchall().__str__()"),
        ("execute('", "execute(r'"),
        ("execute('", "execute(f'"),
        ("execute('", "execute('' '"),
        ("SELECT *", "SEL\\u0045CT *"),
        ("SELECT *", "SELECT\\n*"),
        ("def literal_rows():", "# owner\ndef literal_rows():"),
        ("from psycopg import Connection", "from psycopg import Connection\nConnection.execute = custom"),
        ("from psycopg import Connection", "from psycopg import Connection\nimport other"),
    ],
)
def test_unowned_configured_or_observable_consumers_stay_manual(before: str, after: str) -> None:
    source = _authored_source().replace(before, after)
    assert source != _authored_source()
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    "source",
    [
        f"query = '{_QUERY}'\nprint(query)\n",
        f"query = '{_QUERY}'\nquery += ' CROSS JOIN extra'\n",
        f"def execute(query):\n    return query\nexecute('{_QUERY}')\n",
        f"value = SQL('{_QUERY}').format(other)\n",
        _authored_source() + "Connection.connect = custom\n",
        _authored_source() + "print(literal_rows)\n",
        _authored_source()
        .replace("return connection", "return wrapper(connection")
        .replace("fetchall()", "fetchall())"),
    ],
    ids=[
        "module-query-print",
        "rebound-query-string",
        "unknown-local-executor",
        "composed-sql-wrapper",
        "connection-factory-rebound",
        "function-reference-escape",
        "wrapped-cursor-result",
    ],
)
def test_actual_diagnostic_does_not_authorize_query_text_or_unknown_sink_changes(source: str) -> None:
    assert REGISTRY[_RULE]().check(_PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("path", ["tests/rows.py", "fixtures/rows.py", "examples/rows.py", "generated/rows.py"])
def test_source_ownership_exclusions_are_preserved(path: str) -> None:
    source = _authored_source()
    assert fix_source(Path(path), source, rule_ids=[_RULE]) == source


def test_authored_example_is_the_exact_public_fixed_source() -> None:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix")
    assert fix_source(_PATH, example.files[0].source, rule_ids=[_RULE]) == example.fixed_files[0].source


def test_malformed_source_retains_the_existing_parse_error_boundary() -> None:
    source = _authored_source().replace("return connection", "return wrapper(connection")
    with pytest.raises(ValueError, match="selected Python source could not be parsed"):
        fix_source(_PATH, source, rule_ids=[_RULE])


_ALIAS_RULE = "no-redundant-sql-alias"
_ALIAS_QUERY = 'SELECT "r"."id" AS "id" FROM (VALUES (1)) AS "r"("id")'


def _alias_source(query: str = _ALIAS_QUERY) -> str:
    documentation = REGISTRY[_ALIAS_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix")
    return example.files[0].source.replace(_ALIAS_QUERY, query)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "mixed"])
@pytest.mark.parametrize(
    ("query", "fixed"),
    [
        (_ALIAS_QUERY, _ALIAS_QUERY.replace(' AS "id"', "")),
        (
            "select R.ID as id from (values (999999999)) as r(id);",
            "select R.ID from (values (999999999)) as r(id);",
        ),
        (
            'SELECT "select"."from" AS "from" FROM (VALUES (0)) AS "select"("from")',
            'SELECT "select"."from" FROM (VALUES (0)) AS "select"("from")',
        ),
        (
            'SELECT "r"."B" AS "B", "r"."a" AS a FROM (VALUES (1, 2)) AS "r"("a", "B")',
            'SELECT "r"."B", "r"."a" FROM (VALUES (1, 2)) AS "r"("a", "B")',
        ),
        (
            "SELECT r.id\tAS\tID, r.id AS id FROM (VALUES (000000001)) AS r(id)",
            "SELECT r.id, r.id FROM (VALUES (000000001)) AS r(id)",
        ),
        (
            'SELECT "r"."A" AS "A", "r"."a" AS "a" FROM (VALUES (1,2)) AS "r"("A","a")',
            'SELECT "r"."A", "r"."a" FROM (VALUES (1,2)) AS "r"("A","a")',
        ),
        (
            "SELECT r.b AS b, r.a AS a FROM (VALUES (1, 0), (2, 999999999)) AS r(a, b)",
            "SELECT r.b, r.a FROM (VALUES (1, 0), (2, 999999999)) AS r(a, b)",
        ),
        (
            "SELECT r.id AS id, r.id AS id FROM (VALUES (2), (000000001), (0)) AS r(id)",
            "SELECT r.id, r.id FROM (VALUES (2), (000000001), (0)) AS r(id)",
        ),
        (
            "SELECT r.id AS id FROM (VALUES (0),(1),(2),(3),(4),(5),(6),(7)) AS r(id)",
            "SELECT r.id FROM (VALUES (0),(1),(2),(3),(4),(5),(6),(7)) AS r(id)",
        ),
        (
            "SELECT r.h AS h, r.a AS a FROM (VALUES (0,1,2,3,4,5,6,7),(8,9,10,11,12,13,14,15)) AS r(a,b,c,d,e,f,g,h)",
            "SELECT r.h, r.a FROM (VALUES (0,1,2,3,4,5,6,7),(8,9,10,11,12,13,14,15)) AS r(a,b,c,d,e,f,g,h)",
        ),
        (
            "SELECT r.id AS id, r.value FROM (VALUES (1,2),(3,4)) AS r(id,value)",
            "SELECT r.id, r.value FROM (VALUES (1,2),(3,4)) AS r(id,value)",
        ),
        (
            "SELECT r.id, r.value AS value, r.id FROM (VALUES (1,2),(3,4)) AS r(id,value)",
            "SELECT r.id, r.value, r.id FROM (VALUES (1,2),(3,4)) AS r(id,value)",
        ),
        (
            "SELECT r.id, r.value AS value FROM (VALUES (1,2),(3,4)) AS r(id,value)",
            "SELECT r.id, r.value FROM (VALUES (1,2),(3,4)) AS r(id,value)",
        ),
        (
            'SELECT "r"."ID", "r"."ID" AS "ID", "r"."id" FROM (VALUES (1,2)) AS "r"("ID","id")',
            'SELECT "r"."ID", "r"."ID", "r"."id" FROM (VALUES (1,2)) AS "r"("ID","id")',
        ),
    ],
)
def test_closed_literal_self_alias_preserves_columns_and_physical_lines(ending: str, query: str, fixed: str) -> None:
    source = _alias_source(query)
    if ending == "mixed":
        source = "".join(line + ("\r\n" if index % 2 else "\n") for index, line in enumerate(source.splitlines()))
    else:
        source = source.replace("\n", ending)
    expected = source.replace(query, fixed)
    assert len(REGISTRY[_ALIAS_RULE]().check(_PATH, source)) == 1
    assert fix_source(_PATH, source, rule_ids=[_ALIAS_RULE]) == expected
    assert fix_source(_PATH, source) == expected
    assert not REGISTRY[_ALIAS_RULE]().check(_PATH, expected)
    assert fix_source(_PATH, expected, rule_ids=[_ALIAS_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    before = ast.parse(source)
    after = ast.parse(expected)
    original = [node for node in ast.walk(before) if isinstance(node, ast.Constant)]
    changed = [node for node in ast.walk(after) if isinstance(node, ast.Constant)]
    assert len(original) == len(changed) == 1
    original[0].value = changed[0].value
    assert ast.dump(before) == ast.dump(after)


@pytest.mark.parametrize(
    "query",
    [
        'SELECT "r"."id" AS "id" FROM item AS "r"',
        'SELECT "r"."id" AS "id" FROM item AS item',
        'SELECT "r"."id" AS "other" FROM (VALUES (1)) AS "r"("id")',
        'SELECT "r"."ID" AS id FROM (VALUES (1)) AS "r"("ID")',
        'SELECT "r"."id" AS "ID" FROM (VALUES (1)) AS "r"("id")',
        'SELECT "s"."id" AS "id" FROM (VALUES (1)) AS "r"("id")',
        'SELECT "r"."missing" AS "missing" FROM (VALUES (1)) AS "r"("id")',
        'SELECT "r"."id"::text AS "id" FROM (VALUES (1)) AS "r"("id")',
        'SELECT abs("r"."id") AS "id" FROM (VALUES (1)) AS "r"("id")',
        'SELECT "r"."id" AS "id" FROM (VALUES (1, 2)) AS "r"("id", "id")',
        'SELECT "r"."id" AS "id" FROM (VALUES (1)) AS "r"("id", "other")',
        'SELECT "r"."id" AS "id" FROM (VALUES (1), (2, 3)) AS "r"("id")',
        'SELECT "r"."id" AS "id" FROM (VALUES (NULL)) AS "r"("id")',
        'SELECT "r"."id" AS "id" FROM (VALUES (-1)) AS "r"("id")',
        "SELECT r.id AS id FROM (VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8)) AS r(id)",
        "SELECT r.id AS id FROM (VALUES (0,1,2,3,4,5,6,7,8)) AS r(a,b,c,d,e,f,g,h,id)",
        "SELECT r.id AS id FROM (VALUES (pg_catalog.current_query())) AS r(id)",
        "SELECT r.id AS id FROM (VALUES (1 + 0)) AS r(id)",
        "SELECT v.id AS id FROM v",
        "SELECT v.id AS id FROM public.v AS v",
        "CREATE VIEW v AS SELECT pg_catalog.current_query() AS id; SELECT v.id AS id FROM v",
        "SELECT r.id, r.value AS renamed FROM (VALUES (1,2)) AS r(id,value)",
        "SELECT r.id AS id, r.value AS renamed FROM (VALUES (1,2)) AS r(id,value)",
        "SELECT r.id, r.value FROM (VALUES (1,2)) AS r(id,value)",
        _ALIAS_QUERY + " WHERE true",
        _ALIAS_QUERY + " ORDER BY 1",
        _ALIAS_QUERY + "; SELECT 1",
        _ALIAS_QUERY.replace("SELECT ", "SELECT /* keep */ "),
        _ALIAS_QUERY.replace('"id"', '"é"'),
        _ALIAS_QUERY.replace('"id"', '"' + "i" * 64 + '"'),
        _ALIAS_QUERY + " " * 2048,
    ],
    ids=[
        "external-table-with-role-alias",
        "external-table-self-alias",
        "renamed-column-alias",
        "quoted-to-unquoted-case-change",
        "quoted-output-case-change",
        "unknown-relation-qualifier",
        "missing-values-column",
        "cast-projection",
        "function-projection",
        "duplicate-values-labels",
        "values-label-width-mismatch",
        "mixed-values-row-width",
        "null-values-literal",
        "negative-values-literal",
        "too-many-values-rows",
        "too-many-values-columns",
        "query-text-observing-values-function",
        "values-arithmetic",
        "external-view",
        "schema-qualified-view",
        "observing-view-definition",
        "bare-column-with-renamed-alias",
        "self-alias-with-renamed-alias",
        "no-self-alias",
        "where-clause",
        "order-by-clause",
        "second-statement",
        "block-comment",
        "unicode-identifier",
        "oversized-identifier",
        "query-length-limit",
    ],
)
def test_alias_edits_require_the_entire_closed_relation_and_identifier_contract(query: str) -> None:
    source = _alias_source(query)
    assert fix_source(_PATH, source, rule_ids=[_ALIAS_RULE]) == source


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("from psycopg import Connection", "from other import Connection"),
        ("from psycopg import Connection", "from psycopg import Connection as Connection"),
        ("def literal_rows():", "def literal_rows(Connection):"),
        ("def literal_rows():", "@decorate\ndef literal_rows():"),
        ("def literal_rows():", "def literal_rows[T]():"),
        ("def literal_rows():", "def literal_rows() -> list:"),
        ("def literal_rows():", "async def literal_rows():"),
        ("Connection.connect()", "Connection.connect(row_factory=custom)"),
        ("Connection.connect()", "Connection.connect(cursor_factory=custom)"),
        ("Connection.connect()", "Connection.connect('service=other')"),
        ("Connection.connect()", "factory.connect()"),
        (" as connection:", " as Connection:"),
        (" as connection:", " as literal_rows:"),
        ("        return ", "        observe(connection)\n        return "),
        ("connection.execute(", "other.execute("),
        (".fetchall()", ".fetchone()"),
        (".fetchall()", ".fetchall(extra=True)"),
        ("execute('", "execute(r'"),
        ("execute('", "execute(f'"),
        ("execute('", "execute('' '"),
        ("SELECT ", "SEL\\u0045CT "),
        ("SELECT ", "SELECT\\n"),
        ("def literal_rows():", "# keep\ndef literal_rows():"),
        ("from psycopg import Connection", "from psycopg import Connection\nConnection.execute = custom"),
        ("from psycopg import Connection", "from psycopg import Connection\nimport other"),
    ],
)
def test_alias_fix_preserves_unknown_owners_and_literal_custody(before: str, after: str) -> None:
    source = _alias_source().replace(before, after)
    assert source != _alias_source()
    assert fix_source(_PATH, source, rule_ids=[_ALIAS_RULE]) == source


@pytest.mark.parametrize(
    "source",
    [
        _alias_source().rstrip() + "  # sarj-noqa: SARJ543 -- preserve the generator's alias\n",
        "# Code generated. DO NOT EDIT.\n" + _alias_source(),
        _alias_source() + "print(literal_rows)\n",
        _alias_source().replace("execute('", "execute(SQL('").replace("').fetchall()", "')).fetchall()"),
    ],
    ids=["explicit-suppression", "generated-source", "function-reference-escape", "sql-constructor-composition"],
)
def test_alias_suppression_generation_and_composition_are_not_rewritten(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=[_ALIAS_RULE]) == source


def test_self_alias_public_fixed_example_is_exact() -> None:
    documentation = REGISTRY[_ALIAS_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix")
    assert fix_source(_PATH, example.files[0].source, rule_ids=[_ALIAS_RULE]) == example.fixed_files[0].source
