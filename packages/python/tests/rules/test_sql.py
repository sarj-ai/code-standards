"""Direct tests for the SQL-literal helpers shared by SARJ018-021 and SARJ036.

Five rules scan raw SQL for keywords. Every one of them is only as correct as
`strip_sql_noise`, which decides what counts as SQL *code* rather than SQL
string-literal *value* -- and as `is_store_module`, which decides whether the
store-layer premises apply at all. Both were tested only through the rules, so a
regression in either read as five unrelated rule failures.
"""

import ast
from pathlib import Path

import pytest

from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


def _expr(source: str) -> ast.expr:
    parsed = ast.parse(source, mode="eval")
    return parsed.body


@pytest.mark.parametrize(
    "path",
    ["app/stores/widget.py", "app/widget_store.py", "app/stores/nested/thing.py"],
)
def test_the_store_layer_is_recognised_by_name_and_by_directory(path: str) -> None:
    assert is_store_module(Path(path))


@pytest.mark.parametrize(
    "path",
    ["app/views/widget.py", "app/storefront.py", "app/store.py"],
)
def test_non_store_modules_are_out_of_scope(path: str) -> None:
    assert not is_store_module(Path(path))


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_widget_store.py",
        "app/stores/conftest.py",
        "app/tests/widget_store.py",
        "app/stores/tests/helpers.py",
    ],
)
def test_a_test_file_is_never_a_store_module(path: str) -> None:
    """`test_<x>_store.py` ends with `_store.py`, which swept tests into the store rules.

    Every store-semantics premise fails in a test: a `COUNT(*)` runs over a
    handful of per-test fixture rows, and a seed helper inserts one row per test
    so a bare `INSERT` needs no `ON CONFLICT`. Four suppressed findings across
    two first-party store test modules, none of them a defect. Raw SQL in tests
    is judged by SARJ036 instead, on test-appropriate terms.
    """
    assert not is_store_module(Path(path))


def test_a_plain_string_literal_is_read_as_sql() -> None:
    assert sql_string_value(_expr('"SELECT 1"')) == "SELECT 1"


def test_a_concatenated_literal_is_reassembled() -> None:
    # Long queries are routinely split across `+`; reading only the first half
    # loses whichever keyword landed in the second.
    assert sql_string_value(_expr('"SELECT a " + "FROM t " + "JOIN u ON 1"')) == "SELECT a FROM t JOIN u ON 1"


@pytest.mark.parametrize(
    "source",
    ['"SELECT " + name', "name", '"SELECT %s" % name', '"a" * 3'],
)
def test_a_runtime_value_is_not_a_readable_literal(source: str) -> None:
    assert sql_string_value(_expr(source)) is None


def test_a_keyword_inside_a_string_value_is_masked() -> None:
    """`WHERE p = 'join'` holds no JOIN; scanning raw text says it does."""
    assert "join" not in strip_sql_noise("SELECT a FROM t WHERE p = 'join'").lower().replace("from t ", "")
    assert "JOIN" not in strip_sql_noise("SELECT a FROM t WHERE p = 'JOIN u ON 1'")


def test_a_comment_marker_inside_a_string_value_does_not_start_a_comment() -> None:
    # Left-to-right precedence: the string opens first, so the `--` is data.
    stripped = strip_sql_noise("SELECT '--' AS dashes, COUNT(*) FROM t")
    assert "COUNT" in stripped


def test_a_quote_inside_a_comment_does_not_open_a_string() -> None:
    # The other precedence direction: an unbalanced apostrophe in a comment must
    # not swallow the rest of the statement.
    stripped = strip_sql_noise("-- don't scan this\nSELECT COUNT(*) FROM t")
    assert "COUNT" in stripped
    assert "scan" not in stripped


def test_a_doubled_quote_stays_part_of_the_value() -> None:
    """`''` is SQL's in-string escape, so an escaped apostrophe must not expose the rest."""
    stripped = strip_sql_noise("SELECT 'it''s a JOIN' AS s, COUNT(*) FROM t")
    assert "JOIN" not in stripped
    assert "COUNT" in stripped


def test_a_block_comment_is_blanked_out() -> None:
    stripped = strip_sql_noise("SELECT /* JOIN u ON 1 */ COUNT(*) FROM t")
    assert "JOIN" not in stripped
    assert "COUNT" in stripped


def test_masking_preserves_line_offsets() -> None:
    """Diagnostic positions come from these offsets, so nothing may shift."""
    text = "SELECT 'a\nmultiline\nvalue' -- trailing\nFROM t\n"
    stripped = strip_sql_noise(text)
    assert len(stripped) == len(text)
    assert stripped.count("\n") == text.count("\n")
    assert stripped.splitlines()[3] == "FROM t"
