from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.parametrize_case_needs_id import ParametrizeCaseNeedsId


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return ParametrizeCaseNeedsId().check(Path(path), source)


_OPAQUE_TABLE = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}])
def test_thing(payload):
    assert handle(payload)
"""


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_OPAQUE_TABLE, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_OPAQUE_TABLE, path) == []


@pytest.mark.parametrize(
    "case",
    [
        '{"a": 1}',
        "{1, 2}",
        "Config(x=1)",
        "[k for k in keys]",
        "{k: 1 for k in keys}",
        "{k for k in keys}",
        "(k for k in keys)",
    ],
)
def test_flags_opaque_case_values(case: str):
    src = f"""
import pytest

@pytest.mark.parametrize("payload", [{case}, {case}])
def test_thing(payload):
    assert payload
"""
    assert len(_check(src)) == 1


def test_flags_case_whose_columns_are_all_opaque():
    src = """
import pytest

@pytest.mark.parametrize(("cfg", "other"), [(Config(1), Config(2)), (Config(3), Config(4))])
def test_thing(cfg, other):
    assert run(cfg, other)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "case",
    [
        "(Config(1), True)",
        '("0.0", Decimal("0.0"))',
        '(datetime(2012, 4, 9), "2012-04-09")',
        '(UUID("ebcdab58-6eb8-46fb-a190-d07a33e9eac8"), 1)',
        '(Err("too short"), "input is too short")',
    ],
)
def test_one_nameable_column_is_enough(case: str):
    src = f"""
import pytest

@pytest.mark.parametrize(("a", "b"), [{case}, {case}])
def test_thing(a, b):
    assert run(a, b)
"""
    assert _check(src) == []


def test_flags_unnamed_pytest_param_with_opaque_payload():
    src = """
import pytest

@pytest.mark.parametrize("cfg", [pytest.param(Config(1)), pytest.param(Config(2))])
def test_thing(cfg):
    assert cfg
"""
    assert len(_check(src)) == 1


def test_unnamed_pytest_param_with_one_nameable_column_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize(("label", "cfg"), [pytest.param("on", Config(1)), pytest.param("off", Config(2))])
def test_thing(label, cfg):
    assert label and cfg
"""
    assert _check(src) == []


def test_message_reports_how_many_cases_are_unnameable():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, "scalar", {"b": 2}, {"c": 3}])
def test_thing(payload):
    assert payload
"""
    [diag] = _check(src)
    assert "3 of this table's cases" in diag.message


def test_one_diagnostic_per_table_not_per_case():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}, {"a": 5}])
def test_thing(payload):
    assert payload
"""
    assert len(_check(src)) == 1


def test_decorator_level_ids_exempts_the_whole_table():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}], ids=["one", "two"])
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_callable_ids_exempts_the_table():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}], ids=repr)
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_per_case_pytest_param_id_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize(
    "cfg",
    [pytest.param(Config(1), id="enabled"), pytest.param(Config(2), id="disabled")],
)
def test_thing(cfg):
    assert cfg
"""
    assert _check(src) == []


def test_bare_param_alias_id_is_exempt():
    src = """
from pytest import param, mark

@mark.parametrize("cfg", [param(Config(1), id="a"), param(Config(2), id="b")])
def test_thing(cfg):
    assert cfg
"""
    assert _check(src) == []


def test_partially_named_table_still_flags_the_unnamed_cases():
    src = """
import pytest

@pytest.mark.parametrize(
    "cfg",
    [pytest.param(Config(1), id="named"), pytest.param(Config(2))],
)
def test_thing(cfg):
    assert cfg
"""
    [diag] = _check(src)
    assert "1 of this table's cases" in diag.message


@pytest.mark.parametrize(
    "case",
    ['"text"', "429", "True", "None", "3.5", "Language.AR", "b'bytes'"],
)
def test_scalar_cases_are_exempt(case: str):
    src = f"""
import pytest

@pytest.mark.parametrize("value", [{case}, {case}])
def test_thing(value):
    assert value is not ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "case",
    ["float('nan')", "int(1e10)", "type(None)", "str(raw)", "bytes(raw)", "re.compile('a')"],
)
def test_builtin_scalar_constructor_cases_are_exempt(case: str):
    src = f"""
import pytest

@pytest.mark.parametrize("value", [{case}, {case}])
def test_thing(value):
    assert value is not ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "case",
    ["Decimal('0.0')", "datetime(2012, 4, 9)", "dict(a=1)", "timedelta(hours=10)"],
)
def test_other_constructor_cases_still_flag(case: str):
    src = f"""
import pytest

@pytest.mark.parametrize("value", [{case}, {case}])
def test_thing(value):
    assert value is not ...
"""
    assert len(_check(src)) == 1


def test_scalar_constructor_next_to_an_opaque_column_is_enough():
    src = """
import pytest

@pytest.mark.parametrize(
    ("kwargs", "input_value", "expected"),
    [({'lt': 0}, float('nan'), Err('x')), ({'gt': 0}, float('inf'), Decimal('inf'))],
)
def test_thing(kwargs, input_value, expected):
    assert run(kwargs, input_value) == expected
"""
    assert _check(src) == []


def test_parametrize_call_outside_a_decorator_is_exempt():
    src = """
parametrize(
    (
        {},
        {},
    ),
    (
        {},
        {},
    ),
)
"""
    assert _check(src) == []


def test_parametrize_decorating_a_class_still_fires():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}])
class TestThing:
    def test_thing(self, payload):
        assert payload
"""
    assert len(_check(src)) == 1


def test_bare_parametrize_decorator_still_fires():
    src = """
from pytest import parametrize

@parametrize("payload", [{"a": 1}, {"a": 2}])
def test_thing(payload):
    assert payload
"""
    assert len(_check(src)) == 1


def test_parametrize_decorating_an_async_function_still_fires():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}])
async def test_thing(payload):
    assert payload
"""
    assert len(_check(src)) == 1


def test_non_literal_values_argument_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize("payload", CASES)
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_values_built_by_a_call_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize("payload", build_cases())
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_empty_table_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize("payload", [])
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_decorator_with_only_argnames_is_exempt():
    src = """
import pytest

@pytest.mark.parametrize("payload")
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


def test_unrelated_decorator_is_not_flagged():
    src = """
import pytest

@pytest.mark.usefixtures("db")
def test_thing():
    assert handle({"a": 1})
"""
    assert _check(src) == []


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check('@pytest.mark.parametrize("a", [{:}])\ndef test_x(:\n') == []


def test_multiple_tables_in_one_file():
    src = """
import pytest

@pytest.mark.parametrize("a", [{"x": 1}, {"x": 2}])
def test_one(a):
    assert a

@pytest.mark.parametrize("b", ["s1", "s2"])
def test_two(b):
    assert b

@pytest.mark.parametrize("c", [{"y": 1}, {"y": 2}])
def test_three(c):
    assert c
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_decorator():
    src = """
import pytest

@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}])
def test_thing(payload):
    assert payload
"""
    [diag] = _check(src)
    assert diag.line == 4
    assert diag.code == "SARJ042"


def test_diagnostics_are_sorted_by_position():
    src = """
import pytest

@pytest.mark.parametrize("a", [{"x": 1}, {"x": 2}])
def test_one(a):
    assert a

@pytest.mark.parametrize("b", [{"y": 1}, {"y": 2}])
def test_two(b):
    assert b
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_stacked_parametrize_decorators_both_fire():
    src = """
import pytest

@pytest.mark.parametrize("a", [{"x": 1}, {"x": 2}])
@pytest.mark.parametrize("b", [{"y": 1}, {"y": 2}])
def test_thing(a, b):
    assert a and b
"""
    assert len(_check(src)) == 2


def test_flags_list_values_for_one_parameter():
    src = """
import pytest
@pytest.mark.parametrize("items", [[1, 2], [3, 4]])
def test_thing(items): assert items
"""
    assert len(_check(src)) == 1


def test_flags_tuple_values_for_one_parameter_even_with_scalar_members():
    src = """
import pytest
@pytest.mark.parametrize("pair", [("left", 1), ("right", 2)])
def test_thing(pair): assert pair
"""
    assert len(_check(src)) == 1


def test_list_rows_use_per_column_ids_for_multiple_parameters():
    src = """
import pytest
@pytest.mark.parametrize(["label", "cfg"], [["on", Config(1)], ["off", Config(2)]])
def test_thing(label, cfg): assert label and cfg
"""
    assert _check(src) == []
