from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.zero_assertion_test import ZeroAssertionTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/unit/test_conditions.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return ZeroAssertionTest().check(Path(path), source)


_BARE_TEST = """
def test_thing():
    evaluate_conditions(record, conditions)
"""


# --------------------------------------------------------------------------- #
# Test-path gating, plus the uncollected-scripts exclusion.                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_BARE_TEST, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_BARE_TEST, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "app/chat/scripts/test_llm_providers.py",
        "scripts/test_probe.py",
    ],
)
def test_skips_uncollected_script_probes(path: str):
    assert _check(_BARE_TEST, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "black/tests/data/cases/class_blank_parentheses.py",
        "black/tests/data/cases/fmtonoff5.py",
        "tests/helpers.py",
        "tests/conftest.py",
    ],
)
def test_skips_modules_pytest_does_not_collect(path: str):
    # `is_test_path` accepts anything under `tests/`; pytest only imports
    # `test_*.py` / `*_test.py`. black's formatter fixtures live under
    # `tests/data/cases/` and are arbitrary Python, not tests.
    assert _check(_BARE_TEST, path) == []


def test_still_fires_for_a_collected_module_in_the_same_tree():
    assert len(_check(_BARE_TEST, "black/tests/test_black.py")) == 1


# --------------------------------------------------------------------------- #
# Positive: the result is computed and dropped on the floor.                   #
# --------------------------------------------------------------------------- #


def test_flags_discarded_return_value():
    assert len(_check(_BARE_TEST)) == 1


def test_flags_async_test():
    src = """
async def test_thing():
    await adapter.send_first_message("hello")
"""
    assert len(_check(src)) == 1


def test_flags_test_method_in_a_class():
    src = """
class TestThing:
    def test_registers_no_handler(self):
        adapter.emit("event")
"""
    assert len(_check(src)) == 1


def test_message_names_the_test():
    [diag] = _check(_BARE_TEST)
    assert "`test_thing`" in diag.message


# --------------------------------------------------------------------------- #
# FP guard: pytest.raises. This is the whole ballgame — 223 of 264             #
# assertion-free tests in the audited corpora verify this way.                 #
# --------------------------------------------------------------------------- #


def test_pytest_raises_context_manager_is_exempt():
    src = """
import pytest

def test_thing():
    with pytest.raises(ValueError):
        parse("bad")
"""
    assert _check(src) == []


def test_pytest_raises_with_match_is_exempt():
    src = """
import pytest

def test_thing():
    with pytest.raises(ValueError, match="bad input"):
        parse("bad")
"""
    assert _check(src) == []


def test_pytest_warns_is_exempt():
    src = """
import pytest

def test_thing():
    with pytest.warns(DeprecationWarning):
        legacy()
"""
    assert _check(src) == []


def test_pytest_fail_is_exempt():
    src = """
import pytest

def test_thing():
    if broken():
        pytest.fail("should not happen")
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        "pytest.deprecated_call(match='gone')",
        "pytest.RaisesGroup(pytest.RaisesExc(TypeError))",
        "pytest_raises_user_error_for_undefined_type('Foobar', 'UndefinedType')",
    ],
)
def test_raises_token_anywhere_in_the_name_is_exempt(call: str):
    # pytest 8.4's RaisesGroup/RaisesExc and pydantic's own
    # `pytest_raises_user_error_for_undefined_type` all expect a throw.
    src = f"""
import pytest

def test_thing():
    with {call}:
        parse("bad")
"""
    assert _check(src) == []


@pytest.mark.parametrize("call", ["response.raise_for_status()", "warn_user(result)"])
def test_a_name_merely_near_raise_is_not_a_verification(call: str):
    src = f"""
def test_thing():
    {call}
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: pytest-benchmark. 93 of 291 third-party hits were benchmarks.      #
# --------------------------------------------------------------------------- #


def test_called_benchmark_fixture_is_exempt():
    src = """
def test_model_eq_extra_forbid(benchmark):
    m1 = ModelNoExtra()
    benchmark(model_eq, m1, m1)
"""
    assert _check(src) == []


def test_benchmark_applied_as_a_decorator_is_exempt():
    src = """
def test_validators_build(benchmark) -> None:
    @benchmark
    def bench() -> None:
        build()
"""
    assert _check(src) == []


def test_declaring_benchmark_without_using_it_still_flags():
    src = """
def test_thing(benchmark):
    compute()
"""
    assert len(_check(src)) == 1


def test_calling_something_named_benchmark_without_the_fixture_still_flags():
    src = """
def test_thing():
    benchmark(compute)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: delegated assertion helpers and fluent DSLs.                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "_assert_default(env, 'attr', 3)",
        "assert_matches(result, expected)",
        "self.assertEqual(a, b)",
        "verify_payload(result)",
        "validate_schema(result)",
        "expect_ok(result)",
    ],
)
def test_assertion_helper_calls_are_exempt(call: str):
    src = f"""
def test_thing():
    {call}
"""
    assert _check(src) == []


def test_fluent_expect_dsl_is_exempt():
    src = """
async def test_thing(agent_session):
    result = await agent_session.run("hi")
    result.expect.contains_function_call(name="collect_digits")
"""
    assert _check(src) == []


def test_fluent_expect_deeper_in_the_chain_is_exempt():
    src = """
async def test_thing(agent_session):
    result = await agent_session.run("hi")
    result.expect.next_event().is_message(role="assistant")
"""
    assert _check(src) == []


def test_assertion_in_a_nested_run_wrapper_is_exempt():
    # `async def _run(): assert ...` + `asyncio.run(_run())` keeps the real
    # assertions one scope below the test body.
    src = """
import asyncio

def test_thing():
    async def _run():
        result = await compute()
        assert result == 3
    asyncio.run(_run())
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: helpers defined in the same module. Resolving called names against  #
# the module's own defs cleared 50 third-party hits (black's `invokeBlack`,     #
# flask's `common_object_test`, pydantic's `inspect_type_hints`).               #
# --------------------------------------------------------------------------- #


def test_module_local_helper_that_asserts_is_exempt():
    src = """
def common_object_test(app):
    assert app.config["TEST_KEY"] == "foo"

def test_config_from_object():
    app = flask.Flask(__name__)
    common_object_test(app)
"""
    assert _check(src) == []


def test_helper_defined_below_its_caller_is_still_found():
    src = """
def test_root_model_as_field():
    inspect_type_hints(MyModel)

def inspect_type_hints(obj):
    assert get_type_hints(obj)
"""
    assert _check(src) == []


def test_sibling_method_helper_reached_through_self_is_exempt():
    src = """
class BlackTestCase:
    def invokeBlack(self, args, exit_code=0):
        result = BlackRunner().invoke(black.main, args)
        assert result.exit_code == exit_code

    def test_no_src_fails(self):
        self.invokeBlack([], exit_code=1)
"""
    assert _check(src) == []


def test_helper_that_only_delegates_to_another_helper_is_exempt():
    # black's `compare_results` holds no assert of its own; the one it calls does.
    src = """
def check_ast_equivalence(src, dst):
    assert black.assert_equivalent(src, dst) is None

def compare_results(result, expected):
    check_ast_equivalence(result, expected)

def test_expression(self):
    compare_results(run(), EXPECTED)
"""
    assert _check(src) == []


def test_module_local_helper_that_asserts_nothing_still_flags():
    src = """
def import_from(dotted_path):
    return importlib.import_module(dotted_path)

def test_moved_on_v2(module):
    import_from(module)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: re-running another module's tests. 17 third-party hits, all in the  #
# fastapi/sqlmodel tutorial suites.                                            #
# --------------------------------------------------------------------------- #


def test_calling_an_imported_test_function_is_exempt():
    src = """
from docs_src.app_testing.tutorial002_py310 import test_read_main

def test_main():
    test_read_main()
"""
    assert _check(src) == []


def test_calling_a_test_off_a_module_object_is_exempt():
    src = """
def test_tutorial(modules):
    modules.test.test_create_hero()
"""
    assert _check(src) == []


def test_calling_a_locally_defined_test_that_verifies_nothing_still_flags():
    # The delegate is right here and it asserts nothing, so nothing is verified.
    src = """
def test_inner():
    return compute()

def test_outer():
    test_inner()
"""
    assert len(_check(src)) == 2


def test_assertion_inside_control_flow_is_exempt():
    src = """
def test_thing(cases):
    for case in cases:
        if case.active:
            assert handle(case)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: skipped tests and intentional stubs.                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("marker", ["skip", "skipif(True)", "xfail(reason='x')"])
def test_skipped_tests_are_exempt(marker: str):
    src = f"""
import pytest

@pytest.mark.{marker}
def test_thing():
    do_something()
"""
    assert _check(src) == []


@pytest.mark.parametrize("body", ["...", "pass", '"""Placeholder."""'])
def test_stub_bodies_are_exempt(body: str):
    src = f"""
def test_thing():
    {body}
"""
    assert _check(src) == []


def test_non_test_function_is_exempt():
    src = """
def helper_thing():
    do_something()
"""
    assert _check(src) == []


def test_fixture_is_exempt():
    src = """
import pytest

@pytest.fixture
def thing():
    return build()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    thing()\n") == []


def test_multiple_hits_in_one_file():
    src = """
def test_one():
    compute()

def test_two():
    assert compute()

def test_three():
    compute()
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_function():
    src = """
def test_thing():
    compute()
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (2, 1)
    assert diag.code == "SARJ043"


def test_diagnostics_are_sorted_by_position():
    src = """
def test_a():
    compute()

def test_b():
    compute()

def test_c():
    compute()
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


# --------------------------------------------------------------------------- #
# FP guard: pytest only collects module-level functions and class methods.     #
# A third-party sweep found 36 nested-callback hits, all false positives.      #
# --------------------------------------------------------------------------- #


def test_nested_route_handler_named_test_is_not_a_test():
    # The canonical Flask shape: a view function named for its route, declared
    # inside a test that asserts on the response afterwards.
    src = """
def test_subdomain_matching(app, client):
    @app.route("/", subdomain="test")
    def test_index():
        return "test index"

    rv = client.get("/", "http://test.localhost.localdomain/")
    assert rv.data == b"test index"
"""
    assert _check(src) == []


def test_nested_test_named_function_without_asserts_is_still_not_flagged():
    src = """
def test_outer():
    def test_inner():
        return 1
    test_inner()
    assert True is not False
"""
    assert _check(src) == []


def test_class_method_is_still_collected():
    src = """
class TestThing:
    def test_does_nothing(self):
        compute()
"""
    assert len(_check(src)) == 1


def test_fixture_named_test_something_is_exempt():
    # flask/tests/conftest.py defines `test_apps` as a fixture; asserting
    # nothing is exactly right for it.
    src = """
import pytest

@pytest.fixture
def test_apps(monkeypatch):
    monkeypatch.syspath_prepend("x")
    yield
"""
    assert _check(src) == []
