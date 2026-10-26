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
