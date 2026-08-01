from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.kwarg_heavy_construction_in_test import KwargHeavyConstructionInTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/store/test_call_store.py"

_NINE_KWARGS = ", ".join(f"f{i}={i}" for i in range(9))
_EIGHT_KWARGS = ", ".join(f"f{i}={i}" for i in range(8))


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return KwargHeavyConstructionInTest().check(Path(path), source)


_WIDE_IN_TEST = f"""
def test_thing():
    row = UpsertCall({_NINE_KWARGS})
    assert row

def test_other():
    other = UpsertCall({_NINE_KWARGS})
    assert other
"""


# --------------------------------------------------------------------------- #
# Test-path gating.                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_WIDE_IN_TEST, path)) == 2


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_WIDE_IN_TEST, path) == []


# --------------------------------------------------------------------------- #
# Positive / threshold boundary.                                               #
# --------------------------------------------------------------------------- #


def test_flags_nine_keywords():
    assert len(_check(_WIDE_IN_TEST)) == 2


def test_eight_keywords_is_under_the_threshold():
    src = f"""
def test_thing():
    row = UpsertCall({_EIGHT_KWARGS})
    assert row
"""
    assert _check(src) == []


def test_message_reports_the_keyword_count():
    assert "passes 9 keywords" in _check(_WIDE_IN_TEST)[0].message


def test_flags_construction_nested_in_control_flow():
    src = f"""
def test_thing(flag):
    if flag:
        row = UpsertCall({_NINE_KWARGS})
        assert row

def test_other():
    assert UpsertCall({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


def test_flags_async_test():
    src = f"""
async def test_thing():
    row = await store.upsert(UpsertCall({_NINE_KWARGS}))
    assert row

async def test_other():
    assert await store.upsert(UpsertCall({_NINE_KWARGS}))
"""
    assert len(_check(src)) == 2


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

def test_other():
    assert UpsertCall({_NINE_KWARGS})
"""
    diag = _check(src)[0]
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


def test_mapping_update_is_data_not_a_construction():
    # Minimized from rich's tests/test_table.py: 29 keywords relabelling box
    # characters through `__dict__.update(...)` — entries, not fields.
    src = """
def test_placement_table_box_elements():
    table = Table(box=box.ASCII)
    table.box.__dict__.update(
        top_left="a", top="b", top_divider="c", top_right="d", head_left="1",
        head_vertical="2", head_right="3", head_row_left="e", head_row_cross="g",
    )
    assert render(table)
"""
    assert _check(src) == []


def test_wide_construction_next_to_an_update_still_fires():
    src = """
def test_style():
    style = Style(
        color="red", bgcolor="black", bold=True, dim=True, italic=True,
        underline=True, blink=True, blink2=True, reverse=True,
    )
    assert str(style)

def test_style_again():
    other = Style(
        color="blue", bgcolor="white", bold=False, dim=True, italic=True,
        underline=True, blink=True, blink2=True, reverse=True,
    )
    assert str(other)
"""
    assert len(_check(src)) == 2


# --------------------------------------------------------------------------- #
# FP guard from a first-party review regression: the message promises "every     #
# other test repeats the same boilerplate", so the rule checks that premise      #
# rather than asserting.                                                         #
# --------------------------------------------------------------------------- #


def test_single_construction_in_the_file_is_exempt():
    # One first-party test built the only `Batch(` in its file, with 12
    # required fields. There is no duplication for a builder to remove.
    src = f"""
def test_thing():
    batch = Batch({_NINE_KWARGS})
    assert batch
"""
    assert _check(src) == []


def test_second_construction_of_the_same_callee_arms_the_rule():
    src = f"""
def test_one():
    assert Batch({_NINE_KWARGS})

def test_two():
    assert Batch({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


def test_a_narrow_sibling_construction_still_counts_as_repetition():
    # The duplication is of the *callee*, not of the wide call — one wide site
    # plus a narrow one still means a builder with defaults would pay off.
    src = f"""
def test_one():
    assert Batch({_NINE_KWARGS})

def test_two():
    assert Batch(id="b2")
"""
    assert len(_check(src)) == 1


def test_construction_repeated_only_outside_a_test_still_counts():
    src = f"""
def _seed():
    return Batch(id="seed")

def test_one():
    assert Batch({_NINE_KWARGS})
"""
    assert len(_check(src)) == 1


def test_distinct_callees_do_not_count_toward_each_other():
    src = f"""
def test_one():
    assert Batch({_NINE_KWARGS})

def test_two():
    assert Call({_NINE_KWARGS})
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a mock assertion constructs nothing. 276 of 2,064 corpus findings   #
# (13.4%), no true positive among them — and only three callee names occur      #
# corpus-wide, none of which can build an object.                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method",
    ["assert_called_once_with", "assert_called_with", "assert_awaited_once_with"],
)
def test_mock_assertion_is_not_a_construction(method: str):
    # Defaulting these keywords away would delete the assertion: the whole
    # point is to pin the exact call the code under test made.
    src = f"""
def test_one(mock_hook):
    mock_hook.{method}({_NINE_KWARGS})

def test_two(mock_hook):
    mock_hook.{method}({_NINE_KWARGS})
"""
    assert _check(src) == []


def test_construction_beside_a_mock_assertion_still_fires():
    # The shape the guard was written for, inverted: one third-party operator
    # test flagged the assertion and missed the real construction above it.
    src = f"""
def test_one(mock_hook):
    op = ListJobsOperator({_NINE_KWARGS})
    op.execute(context=None)
    mock_hook.assert_called_once_with({_NINE_KWARGS})

def test_two(mock_hook):
    op = ListJobsOperator({_NINE_KWARGS})
    op.execute(context=None)
    mock_hook.assert_called_once_with({_NINE_KWARGS})
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == [3, 8]


def test_a_callee_merely_beginning_with_the_letters_assert_still_fires():
    # The guard is the prefix `assert_`, not the substring "assert":
    # `assertion_bundle(...)` really does build an object.
    src = f"""
def test_one():
    assert assertion_bundle({_NINE_KWARGS})

def test_two():
    assert assertion_bundle({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


# --------------------------------------------------------------------------- #
# FP guard: the callee IS the helper this rule asks for — a `def` in the same    #
# module. 89 of 2,064 corpus findings (4.3%) across 9 callees, every one a      #
# factory, fixture-factory or shared assertion helper.                          #
# --------------------------------------------------------------------------- #


def test_call_to_a_same_module_helper_is_exempt():
    # The keywords are a hand-rolled parametrize table, not an inlined object.
    src = f"""
def verify(**case):
    assert run(**case)

def test_one():
    verify({_NINE_KWARGS})

def test_two():
    verify({_NINE_KWARGS})
"""
    assert _check(src) == []


def test_call_to_a_same_module_fixture_factory_is_exempt():
    src = f"""
import pytest

@pytest.fixture
def make_order():
    def _make(**overrides):
        return Order(**overrides)
    return _make

def _order(**overrides):
    return Order(**overrides)

def test_one():
    assert _order({_NINE_KWARGS})

def test_two():
    assert _order({_NINE_KWARGS})
"""
    assert _check(src) == []


def test_call_to_a_callee_this_module_does_not_define_still_fires():
    # A domain type imported from production code is exactly the target case.
    src = f"""
from app.models import Order

def test_one():
    assert Order({_NINE_KWARGS})

def test_two():
    assert Order({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


def test_dotted_callee_sharing_a_local_def_name_still_fires():
    # Only a bare `Name` resolves to this module's `def`; `helpers.build(...)`
    # reaches something the file does not own, whatever it is called here.
    src = f"""
def build(**overrides):
    return Order(**overrides)

def test_one():
    assert helpers.build({_NINE_KWARGS})

def test_two():
    assert helpers.build({_NINE_KWARGS})
"""
    assert len(_check(src)) == 2


def test_message_says_helper_not_builder():
    # The largest arguable class is a test invoking the system under test with
    # its full parameter list; "builder" was wrong advice for it, "helper" is not.
    assert "extract a helper with defaults" in _check(_WIDE_IN_TEST)[0].message.lower()
