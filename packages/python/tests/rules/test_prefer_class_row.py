from pathlib import Path
import re
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleExample, is_suppressed
from sarj_python_lint.rules.prefer_class_row import PreferClassRow


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    # Most legacy examples focus on keyword shape rather than import spelling.
    # Give those snippets an explicit, position-preserving psycopg provenance;
    # dedicated adversarial tests below call the rule directly without it.
    checked = source
    if "psycopg.rows.dict_row" in source and "import psycopg" not in source:
        checked += "\nimport psycopg\n"
    elif re.search(r"(?<![\w.])rows\.dict_row", source) and "import psycopg.rows as rows" not in source:
        checked += "\nimport psycopg.rows as rows\n"
    elif re.search(r"(?<![\w.])dict_row\b", source) and "from psycopg.rows import dict_row" not in source:
        checked += "\nfrom psycopg.rows import dict_row\n"
    return PreferClassRow().check(Path(path), checked)


_PUBLIC_EXAMPLES = PreferClassRow.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferClassRow().check(Path(focus.path), focus.source)) == example.expected_count


# Positive family: import-proven psycopg `dict_row` values fire.


@pytest.mark.parametrize(
    "factory",
    [
        "dict_row",
        "rows.dict_row",
        "psycopg.rows.dict_row",
    ],
)
def test_fires_for_name_and_attribute_values(factory: str):
    src = f"cur = conn.cursor(row_factory={factory})\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ013"


def test_fires_async_with_cursor():
    src = """
from psycopg.rows import dict_row

async def get(conn):
    async with conn.cursor(row_factory=dict_row) as cur:
        return await cur.fetchone()
"""
    assert len(_check(src)) == 1


def test_flags_manual_model_validation_after_fetching_dict_row():
    src = """
from psycopg.rows import dict_row

async def get_task(conn):
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, status FROM tasks")
        row = await cur.fetchone()
        return Task.model_validate(row)
"""
    assert len(_check(src)) == 1


def test_allows_cursor_reused_for_multiple_result_shapes() -> None:
    src = """
from psycopg.rows import dict_row

async def update(conn):
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, status FROM tasks")
        task = await cur.fetchone()
        await cur.execute("SELECT id, email FROM users")
        user = await cur.fetchone()
        return task, user
"""
    assert _check(src) == []


def test_allows_single_column_returning_result() -> None:
    source = """
from psycopg.rows import dict_row

async def update(conn):
    query = "UPDATE banks SET active = true RETURNING branding"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return await cur.fetchone()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        """
from psycopg.rows import dict_row
async def get(conn):
    query = "SELECT COUNT(*) AS account_count FROM banks"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return await cur.fetchone()
""",
        """
from psycopg.rows import dict_row
async def get(conn):
    query = "SELECT branding FROM banks"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return await cur.fetchone()
""",
        """
from psycopg.rows import dict_row
async def get(conn):
    query = "SELECT coalesce(branding, '{}'::jsonb) AS branding FROM banks"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return await cur.fetchone()
""",
    ],
)
def test_allows_single_column_result_better_served_by_scalar_row(source: str) -> None:
    assert _check(source) == []


def test_fires_sync_with_cursor():
    src = """
from psycopg.rows import dict_row

def get(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.fetchone()
"""
    assert len(_check(src)) == 1


def test_fires_connection_level_connect():
    src = """
from psycopg.rows import dict_row

def connect():
    return psycopg.connect(dsn, row_factory=dict_row)
"""
    assert len(_check(src)) == 1


def test_fires_inside_nested_function():
    src = """
from psycopg.rows import dict_row

def outer(conn):
    def inner():
        return conn.cursor(row_factory=dict_row)
    return inner
"""
    assert len(_check(src)) == 1


def test_fires_inside_lambda():
    src = "make = lambda conn: conn.cursor(row_factory=dict_row)\n"
    assert len(_check(src)) == 1


def test_fires_inside_comprehension():
    src = "curs = [c.cursor(row_factory=dict_row) for c in conns]\n"
    assert len(_check(src)) == 1


def test_fires_with_other_kwargs_present():
    src = 'cur = conn.cursor(name="s", row_factory=dict_row, scrollable=True)\n'
    assert len(_check(src)) == 1


def test_fires_when_row_factory_is_not_on_cursor_call():
    src = "opts = build(row_factory=dict_row)\n"
    assert len(_check(src)) == 1


# Multiple violations: counted and sorted by (line, col).


def test_flags_multiple_cursors():
    src = """
from psycopg.rows import dict_row

async def store(conn):
    async with conn.cursor(row_factory=dict_row) as a:
        pass
    async with conn.cursor(row_factory=dict_row) as b:
        pass
"""
    assert len(_check(src)) == 2


def test_multiple_violations_sorted_by_line_then_col():
    src = "a = f(row_factory=dict_row)\nb = f(row_factory=dict_row)\nc = f(row_factory=dict_row)\n"
    diags = _check(src)
    assert len(diags) == 3
    assert [d.line for d in diags] == [1, 2, 3]
    assert diags == sorted(diags, key=lambda d: (d.line, d.col))


def test_multiple_on_same_line_sorted_by_col():
    src = "x = f(row_factory=dict_row); y = g(row_factory=dict_row)\n"
    diags = _check(src)
    assert len(diags) == 2
    assert diags[0].line == diags[1].line == 1
    assert diags[0].col < diags[1].col


# Line/column accuracy: diagnostic points at the factory value (1-based col).


def test_reports_line_and_col_of_name_value():
    src = "row = cur(row_factory=dict_row)\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == src.index("dict_row") + 1


def test_reports_line_and_col_of_attribute_value():
    src = "x = c(\n    row_factory=rows.dict_row,\n)\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    line2 = src.splitlines()[1]
    assert diags[0].col == line2.index("rows.dict_row") + 1


# Negative family: other psycopg row factories must NOT fire.


@pytest.mark.parametrize(
    "factory",
    [
        "tuple_row",
        "namedtuple_row",
        "scalar_row",
        "args_row",
        "kwargs_row",
        "dict",
        "DictRow",
        "row_factory",
    ],
)
def test_other_named_factories_do_not_fire(factory: str):
    assert _check(f"cur = conn.cursor(row_factory={factory})\n") == []


def test_class_row_call_does_not_fire():
    src = """
from psycopg.rows import class_row

async def get(conn):
    async with conn.cursor(row_factory=class_row(Task)) as cur:
        return await cur.fetchone()
"""
    assert _check(src) == []


def test_dict_row_called_does_not_fire():
    # `row_factory=dict_row()` is a Call value, not a bare name — rule matches
    # names/attributes only, so this deliberately does not fire.
    assert _check("cur = conn.cursor(row_factory=dict_row())\n") == []


def test_class_row_wrapping_dict_row_does_not_fire():
    assert _check("cur = conn.cursor(row_factory=class_row(dict_row))\n") == []


# Negative family: keyword must be named exactly `row_factory`.


@pytest.mark.parametrize(
    "kw",
    ["parser", "factory", "row_factories", "rowfactory", "Row_Factory", "row"],
)
def test_dict_row_under_other_keyword_does_not_fire(kw: str):
    assert _check(f"cur = conn.cursor({kw}=dict_row)\n") == []


def test_ignores_unrelated_keyword_named_dict_row_value():
    src = """
def configure(dict_row):
    return helper(parser=dict_row)
"""
    assert _check(src) == []


# Negative family: case sensitivity — only the exact literal `dict_row` fires.


@pytest.mark.parametrize("factory", ["Dict_Row", "DICT_ROW", "DictRow", "dictrow", "dict_Row"])
def test_case_variants_do_not_fire(factory: str):
    assert _check(f"cur = conn.cursor(row_factory={factory})\n") == []


# Negative family: aliased import — rule is literal-name based (documented limit).


def test_aliased_dict_row_import_fires():
    src = """
from psycopg.rows import dict_row as dr

def get(conn):
    return conn.cursor(row_factory=dr)
"""
    assert len(_check(src)) == 1


# Negative family: non Name/Attribute value expressions (false-positive guards).


@pytest.mark.parametrize(
    "value",
    [
        'factories["dict_row"]',
        "make(dict_row)",
        "dict_row if flag else tuple_row",
        "factories[0]",
        "None",
        "(dict_row)",  # parenthesised name still resolves — see companion test
    ],
)
def test_non_resolving_value_expressions(value: str):
    diags = _check(f"cur = conn.cursor(row_factory={value})\n")
    # A parenthesised bare name is still an ast.Name and does fire; every other
    # shape here (subscript, call, ternary) resolves to None and must not.
    if value == "(dict_row)":
        assert len(diags) == 1
    else:
        assert diags == []


def test_double_star_kwargs_does_not_fire():
    # `**{...}` is an ast.keyword with arg=None; the dict value is not a keyword.
    src = 'cur = conn.cursor(**{"row_factory": dict_row})\n'
    assert _check(src) == []


def test_double_star_variable_does_not_fire():
    assert _check("cur = conn.cursor(**opts)\n") == []


def test_dict_literal_row_factory_key_does_not_fire():
    src = 'opts = {"row_factory": dict_row}\n'
    assert _check(src) == []


def test_row_factory_assignment_does_not_fire():
    src = "row_factory = dict_row\n"
    assert _check(src) == []


def test_positional_dict_row_argument_does_not_fire():
    # A positional arg is not an ast.keyword, so `arg` never equals row_factory.
    assert _check("cur = conn.cursor(dict_row)\n") == []


def test_docstring_mentioning_dict_row_does_not_fire():
    src = '''
def get(conn):
    """Prefer class_row over row_factory=dict_row here."""
    return conn.cursor(row_factory=class_row(Task))
'''
    assert _check(src) == []


def test_comment_mentioning_dict_row_does_not_fire():
    src = "cur = conn.cursor(row_factory=tuple_row)  # not dict_row\n"
    assert _check(src) == []


# Edge cases: empty / whitespace / comment-only / syntax error inputs.


@pytest.mark.parametrize(
    "src",
    ["", "\n", "   \n\t\n", "# just a comment\n", '"""module docstring"""\n'],
)
def test_empty_and_trivial_sources(src: str):
    assert _check(src) == []


def test_ignores_syntax_error():
    assert _check("def broken(:\n") == []


def test_ignores_syntax_error_mid_cursor_call():
    assert _check("cur = conn.cursor(row_factory=dict_row\n") == []


# Suppression: the rule still emits; `is_suppressed` recognises sarj-noqa.


def test_rule_itself_does_not_apply_suppression():
    src = "cur = conn.cursor(row_factory=dict_row)  # sarj-noqa: SARJ013 — ad-hoc\n"
    assert len(_check(src)) == 1


def test_sarj_noqa_with_code_is_recognised():
    src = "cur = conn.cursor(row_factory=dict_row)  # sarj-noqa: SARJ013 — ad-hoc\n"
    diags = _check(src)
    lines = src.splitlines()
    assert is_suppressed(lines, diags[0].line, diags[0].code)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("SELECT COUNT(*) FROM tasks", "aggregate has no model"),
        ("SELECT dynamic_columns FROM tasks", "dynamic projection"),
    ],
    ids=["aggregate", "dynamic-projection"],
)
def test_plain_mapping_exceptions_can_be_suppressed(query: str, reason: str):
    src = f'cur.execute("{query}")\nrow = conn.cursor(row_factory=dict_row)  # sarj-noqa: SARJ013 — {reason}\n'
    diagnostic = _check(src)[0]
    assert is_suppressed(src.splitlines(), diagnostic.line, diagnostic.code)


def test_bare_sarj_noqa_suppresses():
    src = "cur = conn.cursor(row_factory=dict_row)  # sarj-noqa\n"
    diags = _check(src)
    assert is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


def test_sarj_noqa_for_other_code_does_not_suppress():
    src = "cur = conn.cursor(row_factory=dict_row)  # sarj-noqa: SARJ052 — other\n"
    diags = _check(src)
    assert not is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


# Diagnostic payload fields.


def test_diagnostic_fields_populated():
    diags = _check("cur = conn.cursor(row_factory=dict_row)\n", path="svc/store.py")
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "SARJ013"
    assert d.path == Path("svc/store.py")
    assert "class_row" in d.message
    assert "dict_row" in d.message


def test_message_is_stable_across_shapes():
    a = _check("cur = c(row_factory=dict_row)\n")[0]
    b = _check("import psycopg.rows as rows\ncur = c(row_factory=rows.dict_row)\n")[0]
    assert a.message == b.message


# Adversarial additions: keyword matching is context-free — it fires for ANY
# `row_factory=dict_row` keyword, not just `conn.cursor(...)`.


def test_fires_in_functools_partial():
    src = "import functools\nfunctools.partial(conn.cursor, row_factory=dict_row)\n"
    assert len(_check(src)) == 1


def test_fires_in_call_decorator():
    src = "@register(row_factory=dict_row)\ndef f():\n    pass\n"
    assert len(_check(src)) == 1


def test_fires_in_classdef_keyword():
    # `class C(Base, row_factory=dict_row)` is an ast.keyword on ClassDef, not a
    # Call — the walk still matches it (a keyword is a keyword).
    src = "class C(Base, row_factory=dict_row):\n    pass\n"
    assert len(_check(src)) == 1


def test_fires_in_nested_call_keyword():
    assert len(_check("f(g(row_factory=dict_row))\n")) == 1


def test_fires_with_leading_star_arg():
    assert len(_check("conn.cursor(*a, row_factory=dict_row)\n")) == 1


# Adversarial provenance guards: an unrelated terminal `.dict_row` is clean.


@pytest.mark.parametrize(
    "value",
    [
        "get_rows().dict_row",
        "factories[0].dict_row",
        "(await g()).dict_row",
    ],
)
def test_allows_dict_row_attr_of_exotic_receiver(value: str):
    src = f"async def h(conn):\n    return conn.cursor(row_factory={value})\n"
    assert _check(src) == []


def test_allows_unimported_bare_dict_row():
    src = "cur = conn.cursor(row_factory=dict_row)\n"
    assert PreferClassRow().check(Path("store.py"), src) == []


def test_allows_rebound_imported_dict_row():
    src = "from psycopg.rows import dict_row\ndict_row = local_factory\ncur = f(row_factory=dict_row)\n"
    assert PreferClassRow().check(Path("store.py"), src) == []


def test_attribute_with_nonterminal_dict_row_does_not_fire():
    # Terminal `.attr` is `foo`, not `dict_row`, so `_factory_name` returns "foo".
    assert _check("conn.cursor(row_factory=dict_row.foo)\n") == []


# Adversarial additions: names that merely contain `dict_row` as a substring,
# and `class_row` as a bare name, must not fire (exact-literal match only).


@pytest.mark.parametrize(
    "factory",
    ["dict_rows", "dict_row_factory", "my_dict_row", "dict_row2", "_dict_row", "class_row"],
)
def test_substring_and_class_row_names_do_not_fire(factory: str):
    assert _check(f"conn.cursor(row_factory={factory})\n") == []


# Adversarial additions: compound value expressions collapse to None.


@pytest.mark.parametrize(
    "value",
    [
        "dict_row or tuple_row",
        "tuple_row and dict_row",
        "await get_factory()",
    ],
)
def test_boolop_and_await_values_do_not_fire(value: str):
    src = f"async def h(conn):\n    return conn.cursor(row_factory={value})\n"
    assert _check(src) == []


def test_local_variable_rebind_does_not_fire():
    # Same accepted limitation as the aliased-import case: a name bound to
    # `dict_row` elsewhere is not resolved by the literal-name matcher.
    src = "dr = dict_row\nconn.cursor(row_factory=dr)\n"
    assert _check(src) == []


# Adversarial additions: column points at the START of a dotted chain, not the
# `dict_row` leaf, on a wrapped call.


def test_col_points_to_start_of_dotted_chain():
    src = "cur = conn.cursor(\n    row_factory=psycopg.rows.dict_row,\n)\n"
    diags = _check(src)
    assert len(diags) == 1
    line2 = src.splitlines()[1]
    assert diags[0].line == 2
    assert diags[0].col == line2.index("psycopg") + 1


# Adversarial additions: genuine defect — a walrus-wrapped `dict_row` value is
# still `dict_row` at runtime, but `_factory_name` does not unwrap NamedExpr.


def test_walrus_wrapped_dict_row_should_fire():
    assert len(_check("conn.cursor(row_factory=(rf := dict_row))\n")) == 1
