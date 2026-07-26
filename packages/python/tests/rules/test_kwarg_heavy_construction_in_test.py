from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.kwarg_heavy_construction_in_test import KwargHeavyConstructionInTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/store/test_call_store.py"

_NINE_KWARGS = ", ".join(f"f{i}={i}" for i in range(9))
_EIGHT_KWARGS = ", ".join(f"f{i}={i}" for i in range(8))


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return KwargHeavyConstructionInTest().check(Path(path), source)


_WIDE_IN_TEST = f"""
def test_thing():
    row = UpsertCall({_NINE_KWARGS})
    assert row
"""


# --------------------------------------------------------------------------- #
# Test-path gating.                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_WIDE_IN_TEST, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_WIDE_IN_TEST, path) == []


# --------------------------------------------------------------------------- #
# Positive / threshold boundary.                                               #
# --------------------------------------------------------------------------- #


def test_flags_nine_keywords():
    assert len(_check(_WIDE_IN_TEST)) == 1


def test_eight_keywords_is_under_the_threshold():
    src = f"""
def test_thing():
    row = UpsertCall({_EIGHT_KWARGS})
    assert row
"""
    assert _check(src) == []


def test_message_reports_the_keyword_count():
    [diag] = _check(_WIDE_IN_TEST)
    assert "passes 9 keywords" in diag.message


def test_flags_construction_nested_in_control_flow():
    src = f"""
def test_thing(flag):
    if flag:
        row = UpsertCall({_NINE_KWARGS})
        assert row
"""
    assert len(_check(src)) == 1


def test_flags_async_test():
    src = f"""
async def test_thing():
    row = await store.upsert(UpsertCall({_NINE_KWARGS}))
    assert row
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: the factory is allowed to be verbose exactly once. Without the     #
# nearest-function check the corpus population is 113 rather than 17, and the  #
# rule would nag at already well-factored helpers.                             #
# --------------------------------------------------------------------------- #


def test_module_level_builder_is_exempt():
    src = f"""
def _build_call(**overrides):
    return UpsertCall({_NINE_KWARGS})

def test_thing():
    assert _build_call()
"""
    assert _check(src) == []


def test_fixture_is_exempt():
    src = f"""
import pytest

@pytest.fixture
def call_row():
    return UpsertCall({_NINE_KWARGS})
"""
    assert _check(src) == []


def test_nested_helper_inside_a_test_is_exempt():
    src = f"""
def test_thing():
    def _make():
        return UpsertCall({_NINE_KWARGS})
    assert _make()
"""
    assert _check(src) == []


def test_dict_literal_call_is_exempt():
    src = f"""
def test_thing():
    payload = dict({_NINE_KWARGS})
    assert payload
"""
    assert _check(src) == []


def test_positional_arguments_are_not_counted():
    src = """
def test_thing():
    row = UpsertCall(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    assert row
"""
    assert _check(src) == []


def test_kwargs_forwarding_is_not_counted_as_a_keyword():
    src = f"""
def test_thing(overrides):
    row = UpsertCall({_EIGHT_KWARGS}, **overrides)
    assert row
"""
    assert _check(src) == []


def test_non_test_function_is_exempt():
    src = f"""
def helper_thing():
    return UpsertCall({_NINE_KWARGS})
"""
    assert _check(src) == []


def test_module_level_construction_is_exempt():
    src = f"""
ROW = UpsertCall({_NINE_KWARGS})
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    UpsertCall(a=1)\n") == []


def test_multiple_hits_in_one_file():
    src = f"""
def test_one():
    assert UpsertCall({_NINE_KWARGS})

def test_two():
    assert UpsertCall({_EIGHT_KWARGS})

def test_three():
    assert UpsertCall({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_call():
    src = f"""
def test_thing():
    row = UpsertCall({_NINE_KWARGS})
    assert row
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (3, 11)
    assert diag.code == "SARJ045"


def test_diagnostics_are_sorted_by_position():
    src = f"""
def test_thing():
    a = UpsertCall({_NINE_KWARGS})
    b = UpsertCall({_NINE_KWARGS})
    assert a and b
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)
