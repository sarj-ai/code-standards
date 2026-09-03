from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.opaque_parametrize_case_needs_id import OpaqueParametrizeCaseNeedsId


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/app/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return OpaqueParametrizeCaseNeedsId().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = OpaqueParametrizeCaseNeedsId.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


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
    assert "3 cases rely" in diag.message
    assert "payload0" in diag.message


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
    assert "1 case relies" in diag.message


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
    ["float('nan')", "int(1e10)", "type(None)", "str(raw)", "bytes(raw)"],
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


def test_invalid_bare_parametrize_import_is_not_treated_as_pytest():
    src = """
from pytest import parametrize

@parametrize("payload", [{"a": 1}, {"a": 2}])
def test_thing(payload):
    assert payload
"""
    assert _check(src) == []


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


@pytest.mark.parametrize(
    "decorator",
    [
        "@custom.parametrize('payload', [{}, {}])",
        "@parametrize('payload', [{}, {}])",
    ],
)
def test_unproven_parametrize_decorators_are_ignored(decorator: str) -> None:
    source = f"""
def parametrize(*args):
    return custom

{decorator}
def test_thing(payload):
    assert payload
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("import_line", "decorator"),
    [
        ("import pytest as pt", "pt.mark.parametrize"),
        ("from pytest import mark as pytest_mark", "pytest_mark.parametrize"),
    ],
)
def test_import_proven_pytest_aliases_are_supported(import_line: str, decorator: str) -> None:
    source = f"""
{import_line}

@{decorator}("payload", [{{}}, {{"status": "invalid"}}])
def test_thing(payload):
    assert payload
"""
    assert len(_check(source)) == 1


def test_rebound_pytest_import_is_ignored() -> None:
    source = """
import pytest
pytest = custom_pytest

@pytest.mark.parametrize("payload", [{}, {}])
def test_thing(payload):
    assert payload
"""
    assert _check(source) == []


def test_keyword_argnames_and_argvalues_are_analyzed() -> None:
    source = """
import pytest

@pytest.mark.parametrize(argnames="payload", argvalues=[{}, {}])
def test_thing(payload):
    assert payload
"""
    assert len(_check(source)) == 1


def test_ids_none_does_not_exempt_cases() -> None:
    source = """
import pytest

@pytest.mark.parametrize("payload", [{}, {}], ids=None)
def test_thing(payload):
    assert payload
"""
    assert len(_check(source)) == 1


def test_literal_none_ids_leave_only_corresponding_cases_unnamed() -> None:
    source = """
import pytest

@pytest.mark.parametrize("payload", [{}, {}], ids=[None, "invalid-status"])
def test_thing(payload):
    assert payload
"""
    [diagnostic] = _check(source)
    assert "1 case relies" in diagnostic.message


def test_positional_none_ids_leave_only_corresponding_cases_unnamed() -> None:
    source = """
import pytest

@pytest.mark.parametrize("payload", [{}, {}], False, [None, "invalid-status"])
def test_thing(payload):
    assert payload
"""
    [diagnostic] = _check(source)
    assert "1 case relies" in diagnostic.message


def test_pytest_param_id_none_does_not_exempt_case() -> None:
    source = """
import pytest

@pytest.mark.parametrize("payload", [pytest.param({}, id=None), pytest.param({}, id="empty")])
def test_thing(payload):
    assert payload
"""
    [diagnostic] = _check(source)
    assert "1 case relies" in diagnostic.message


def test_imported_pytest_param_alias_is_supported() -> None:
    source = """
from pytest import mark, param as case

@mark.parametrize("payload", [case({}, id="empty"), case({}, id="other")])
def test_thing(payload):
    assert payload
"""
    assert _check(source) == []


def test_foreign_param_id_does_not_claim_to_name_a_pytest_case() -> None:
    source = """
import pytest

@pytest.mark.parametrize("payload", [factory.param({}, id="empty"), factory.param({}, id="other")])
def test_thing(payload):
    assert payload
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "value",
    [
        "compile('x = 1', '<test>', 'exec')",
        "codec.compile('x')",
        "...",
    ],
)
def test_non_scalar_calls_and_ellipsis_are_opaque(value: str) -> None:
    source = f"""
import pytest

@pytest.mark.parametrize("value", [{value}, {value}])
def test_thing(value):
    assert value
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        """
        import pytest
        import re

        @pytest.mark.parametrize("value", [re.compile("a"), re.compile("b")])
        def test_thing(value):
            assert value
        """,
        """
        import pytest
        from re import compile as compile_pattern

        @pytest.mark.parametrize("value", [compile_pattern("a"), compile_pattern("b")])
        def test_thing(value):
            assert value
        """,
        """
        import pytest

        @pytest.mark.parametrize("value", ["a".encode(), "b".encode()])
        def test_thing(value):
            assert value
        """,
        """
        import pytest
        import textwrap

        @pytest.mark.parametrize("value", [textwrap.dedent("a").format(), textwrap.dedent("b").format()])
        def test_thing(value):
            assert value
        """,
    ],
)
def test_proven_scalar_calls_are_nameable(source: str) -> None:
    assert _check(source) == []


def test_shadowed_builtin_scalar_constructor_is_opaque() -> None:
    source = """
import pytest

class str:
    pass

@pytest.mark.parametrize("value", [str("a"), str("b")])
def test_thing(value):
    assert value
"""
    assert len(_check(source)) == 1


def test_generated_test_source_is_excluded() -> None:
    assert _check("# @generated\n" + _OPAQUE_TABLE) == []


def test_reports_as_warning() -> None:
    assert _check(_OPAQUE_TABLE)[0].severity.value == "warning"


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
