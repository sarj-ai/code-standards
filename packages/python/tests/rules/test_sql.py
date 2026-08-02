"""Executable contract for the shared SQL-literal helpers."""

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
    assert not is_store_module(Path(path))


def test_a_plain_string_literal_is_read_as_sql() -> None:
    assert sql_string_value(_expr('"SELECT 1"')) == "SELECT 1"


def test_a_concatenated_literal_is_reassembled() -> None:
    assert sql_string_value(_expr('"SELECT a " + "FROM t " + "JOIN u ON 1"')) == "SELECT a FROM t JOIN u ON 1"


@pytest.mark.parametrize(
    "source",
    ['"SELECT " + name', "name", '"SELECT %s" % name', '"a" * 3'],
)
def test_a_runtime_value_is_not_a_readable_literal(source: str) -> None:
    assert sql_string_value(_expr(source)) is None


def test_a_keyword_inside_a_string_value_is_masked() -> None:
    assert "join" not in strip_sql_noise("SELECT a FROM t WHERE p = 'join'").lower().replace("from t ", "")
    assert "JOIN" not in strip_sql_noise("SELECT a FROM t WHERE p = 'JOIN u ON 1'")


def test_projection_star_and_on_conflict_inside_values_are_masked() -> None:
    stripped = strip_sql_noise("SELECT '*' FROM t WHERE note = 'on conflict'")
    assert "*" not in stripped
    assert "on conflict" not in stripped.lower()


def test_a_comment_marker_inside_a_string_value_does_not_start_a_comment() -> None:
    stripped = strip_sql_noise("SELECT '--' AS dashes, COUNT(*) FROM t")
    assert "COUNT" in stripped


def test_a_quote_inside_a_comment_does_not_open_a_string() -> None:
    stripped = strip_sql_noise("-- don't scan this\nSELECT COUNT(*) FROM t")
    assert "COUNT" in stripped
    assert "scan" not in stripped


def test_a_doubled_quote_stays_part_of_the_value() -> None:
    stripped = strip_sql_noise("SELECT 'it''s a JOIN' AS s, COUNT(*) FROM t")
    assert "JOIN" not in stripped
    assert "COUNT" in stripped


def test_a_doubled_double_quote_stays_part_of_the_value() -> None:
    stripped = strip_sql_noise('SELECT "a "" JOIN b" AS s, COUNT(*) FROM t')
    assert "JOIN" not in stripped
    assert "COUNT" in stripped


def test_a_block_comment_is_blanked_out() -> None:
    stripped = strip_sql_noise("SELECT /* JOIN u ON 1 */ COUNT(*) FROM t")
    assert "JOIN" not in stripped
    assert "COUNT" in stripped


def test_masking_preserves_line_offsets() -> None:
    text = "SELECT 'a\nmultiline\nvalue' -- trailing\nFROM t\n"
    stripped = strip_sql_noise(text)
    assert len(stripped) == len(text)
    assert stripped.count("\n") == text.count("\n")
    assert stripped.splitlines()[3] == "FROM t"
