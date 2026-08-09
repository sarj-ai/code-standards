from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.test_loops_over_literal_cases import TestLoopsOverLiteralCases


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/app/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return TestLoopsOverLiteralCases().check(Path(path), source)


_PUBLIC_EXAMPLES = TestLoopsOverLiteralCases.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


_LITERAL_CASE_LOOP = """
def test_thing():
    for value in ["a", "b", "c"]:
        assert normalize(value) == value
"""


# Test-path gating.                                                            #


@pytest.mark.parametrize(
    "path",
    ["test_x.py", "x_test.py", "conftest.py", "a/tests/helper.py"],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_LITERAL_CASE_LOOP, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_LITERAL_CASE_LOOP, path) == []


# Positive: literal case tables of every display kind.                         #


@pytest.mark.parametrize(
    "literal",
    ['["a", "b"]', '("a", "b")', '{"a", "b"}', "[(1, 2), (3, 4)]", "[{'k': 1}, {'k': 2}]"],
)
def test_flags_literal_iterables(literal: str):
    src = f"""
def test_thing():
    for case in {literal}:
        assert handle(case)
"""
    assert len(_check(src)) == 1


def test_flags_async_for_over_literal():
    src = """
async def test_thing():
    async for case in [1, 2, 3]:
        assert handle(case)
"""
    assert len(_check(src)) == 1


def test_flags_tuple_unpacking_loop():
    src = """
def test_thing():
    for raw, expected in [("a", "A"), ("b", "B")]:
        assert upper(raw) == expected
"""
    assert len(_check(src)) == 1


def test_flags_assert_nested_deeper_in_loop_body():
    src = """
def test_thing():
    for case in ["a", "b"]:
        with context():
            if case:
                assert handle(case)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "verification",
    [
        "self.assertEqual(handle(case), case)",
        "self.assertTrue(handle(case))",
        "with pytest.raises(ValueError):\n            handle(case)",
        "with pytest.warns(UserWarning):\n            handle(case)",
    ],
)
def test_flags_standard_library_verification_apis(verification: str):
    src = f"""
def test_thing(self):
    for case in ["a", "b"]:
        {verification}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("view", ["items", "keys", "values"])
def test_flags_literal_dictionary_views(view: str):
    src = f"""
def test_thing():
    for case in {{"a": 1, "b": 2}}.{view}():
        assert handle(case)
"""
    [diag] = _check(src)
    assert "2 inline cases" in diag.message


def test_starred_literal_dictionary_is_exempt():
    src = """
def test_thing():
    for case in {**extra, "b": 2}.items():
        assert handle(case)
"""
    assert _check(src) == []


def test_message_reports_the_case_count():
    src = """
def test_thing():
    for case in ["a", "b", "c", "d"]:
        assert handle(case)
"""
    [diag] = _check(src)
    assert "4 inline cases" in diag.message


# FP guard: the iterable must be a literal.


@pytest.mark.parametrize(
    "iterable",
    [
        "Language",
        "ProbeName",
        "cases",
        "self.cases",
        "range(5)",
        "enumerate(cases)",
        "zip(a, b)",
        "await store.list_calls()",
        "[c for c in cases]",
        "sorted(cases)",
    ],
)
def test_non_literal_iterables_are_exempt(iterable: str):
    src = f"""
async def test_thing():
    for case in {iterable}:
        assert handle(case)
"""
    assert _check(src) == []


def test_single_element_literal_is_exempt():
    src = """
def test_thing():
    for case in ["only"]:
        assert handle(case)
"""
    assert _check(src) == []


def test_starred_literal_is_exempt():
    src = """
def test_thing():
    for case in [*extra, "b"]:
        assert handle(case)
"""
    assert _check(src) == []


# FP guard: a sub-test already gives each iteration its own report.            #


def test_unittest_subtest_loop_is_exempt():
    src = """
class TestThing:
    def test_rejects_non_string_configs(self):
        for config_key in ["include", "force-exclude"]:
            with self.subTest(config_key=config_key):
                assert reject(config_key)
"""
    assert _check(src) == []


@pytest.mark.parametrize("receiver", ["runner", "case"])
def test_only_self_subtest_is_the_unittest_api(receiver: str):
    src = f"""
def test_thing({receiver}):
    for case in ["a", "b"]:
        with {receiver}.subTest(case=case):
            assert handle(case)
"""
    assert len(_check(src)) == 1


def test_pytest_subtests_loop_is_exempt():
    src = """
def test_thing(subtests):
    for case in ["a", "b"]:
        with subtests.test(case=case):
            assert handle(case)
"""
    assert _check(src) == []


def test_nested_subtest_context_is_exempt():
    src = """
def test_thing(subtests):
    for case in ["a", "b"]:
        if case:
            with subtests.test(case=case):
                assert handle(case)
"""
    assert _check(src) == []


def test_an_unrelated_test_named_context_manager_still_fires():
    # Only `subtests.test(...)` is the plugin; `runner.test(...)` is some
    # other object's method and reports nothing per case.
    src = """
def test_thing(runner):
    for case in ["a", "b"]:
        with runner.test(case):
            assert handle(case)
"""
    assert len(_check(src)) == 1


def test_loop_without_assert_is_exempt():
    # Setup legitimately loops over a literal to build state.
    src = """
def test_thing():
    for name in ["a", "b"]:
        store.insert(name)
    assert store.count() == 2
"""
    assert _check(src) == []


def test_state_building_loop_with_post_loop_contract_is_exempt():
    src = """
def test_thing():
    for name in ["a", "b"]:
        created = store.insert(name)
        assert created.name == name
    assert store.count() == 2
"""
    assert _check(src) == []


# FP guard: nearest enclosing function must be the test itself.                #


def test_loop_in_fixture_is_exempt():
    src = """
import pytest

@pytest.fixture
def seeded():
    for name in ["a", "b"]:
        assert insert(name)
    return True
"""
    assert _check(src) == []


def test_loop_in_nested_helper_is_attributed_to_the_helper():
    src = """
def test_thing():
    def _verify():
        for case in ["a", "b"]:
            assert handle(case)
    _verify()
"""
    assert _check(src) == []


def test_assert_inside_nested_def_does_not_arm_the_loop():
    # The loop itself only registers callbacks; the assert belongs to the closure.
    src = """
def test_thing():
    for case in ["a", "b"]:
        def _cb():
            assert handle(case)
        register(_cb)
"""
    assert _check(src) == []


def test_assert_inside_nested_async_def_does_not_arm_the_loop():
    src = """
def test_thing():
    for case in ["a", "b"]:
        async def _cb():
            assert await handle(case)
        register(_cb)
"""
    assert _check(src) == []


def test_assert_inside_lambda_does_not_arm_the_loop():
    src = """
def test_thing():
    for case in ["a", "b"]:
        register(lambda: (_ for _ in ()).throw(AssertionError))
"""
    assert _check(src) == []


def test_module_level_loop_is_exempt():
    src = """
for case in ["a", "b"]:
    assert handle(case)
"""
    assert _check(src) == []


def test_non_test_function_loop_is_exempt():
    src = """
def helper_thing():
    for case in ["a", "b"]:
        assert handle(case)
"""
    assert _check(src) == []


# Edge cases.                                                                  #


@pytest.mark.parametrize("source", ["", "   \n\n  ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    for a in [1, 2]: assert a\n") == []


def test_multiple_hits_in_one_file():
    src = """
def test_one():
    for case in ["a", "b"]:
        assert handle(case)

def test_two():
    for case in [1, 2, 3]:
        assert handle(case)
    for other in Language:
        assert handle(other)
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_loop():
    src = """
def test_thing():
    for case in ["a", "b"]:
        assert handle(case)
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (3, 5)
    assert diag.code == "SARJ041"


def test_diagnostics_are_sorted_by_position():
    src = """
def test_thing():
    for a in ["x", "y"]:
        assert a
    for b in [1, 2]:
        assert b
    for c in [3, 4]:
        assert c
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_nested_literal_loops_both_fire():
    src = """
def test_thing():
    for outer in ["a", "b"]:
        for inner in [1, 2]:
            assert handle(outer, inner)
"""
    assert len(_check(src)) == 2
