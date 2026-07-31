from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.conditional_assertion_in_test import ConditionalAssertionInTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/unit/test_conditions.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return ConditionalAssertionInTest().check(Path(path), textwrap.dedent(source))


_LOOP_ONLY = """
def test_results():
    rows = fetch()
    for row in rows:
        assert row.id > 0
"""


# --------------------------------------------------------------------------- #
# Path gating.                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py"])
def test_fires_in_collected_test_paths(path: str):
    assert len(_check(_LOOP_ONLY, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_LOOP_ONLY, path) == []


@pytest.mark.parametrize("path", ["tests/conftest.py", "tests/helpers.py", "scripts/test_probe.py"])
def test_skips_modules_pytest_does_not_collect(path: str):
    assert _check(_LOOP_ONLY, path) == []


# --------------------------------------------------------------------------- #
# Positive: no path through the test is guaranteed to assert.                  #
# --------------------------------------------------------------------------- #


def test_flags_loop_only_assertion():
    assert len(_check(_LOOP_ONLY)) == 1


def test_flags_if_without_else():
    src = """
    def test_flagged():
        if user.is_admin:
            assert can_delete(user)
    """
    assert len(_check(src)) == 1


def test_flags_async_test():
    src = """
    async def test_thing():
        rows = await fetch()
        for row in rows:
            assert row.id
    """
    assert len(_check(src)) == 1


def test_flags_test_method_in_a_class():
    src = """
    class TestThing:
        def test_rows(self):
            for row in load():
                assert row
    """
    assert len(_check(src)) == 1


def test_flags_while_loop():
    src = """
    def test_drains():
        while queue.pending():
            assert queue.pop() is not None
    """
    assert len(_check(src)) == 1


def test_flags_assertion_helper_call_inside_a_loop():
    # The helper is an assertion, so the test *has* one — it just may not run.
    src = """
    def test_rows():
        for row in fetch():
            _assert_valid(row)
    """
    assert len(_check(src)) == 1


def test_flags_unittest_assertion_inside_a_loop():
    src = """
    class TestThing:
        def test_rows(self):
            for row in fetch():
                self.assertEqual(row.state, "ok")
    """
    assert len(_check(src)) == 1


def test_message_is_the_whole_advice_verbatim():
    [diag] = _check(_LOOP_ONLY)
    assert diag.message == (
        "every assertion in `test_results` sits inside a conditional or loop that may not run, "
        "so the test passes without checking anything when the branch is not taken or the "
        "iterable is empty. Assert unconditionally, assert the collection's size before "
        "looping (`assert len(rows) == 3`), or give the `if` an `else` that also asserts."
    )


def test_reports_line_and_column_of_the_function():
    [diag] = _check(_LOOP_ONLY)
    assert (diag.line, diag.col) == (2, 1)
    assert diag.code == "SARJ065"


def test_reports_the_indented_position_of_a_method():
    # Both coordinates are non-1 here, so a hardcoded `col=1` cannot pass.
    src = """
    class TestThing:
        def test_rows(self):
            for row in fetch():
                assert row
    """
    [diag] = _check(src)
    assert (diag.line, diag.col) == (3, 5)


def test_diagnostics_are_sorted_by_position():
    # The class is walked after the module body, so the class's method is found
    # second and has to be sorted back in front of the module-level test.
    src = """
    class TestEarly:
        def test_first(self):
            for row in fetch():
                assert row

    def test_second():
        for row in fetch():
            assert row
    """
    assert [(d.line, d.col) for d in _check(src)] == [(3, 5), (7, 1)]


# --------------------------------------------------------------------------- #
# Guard: an unconditional assertion anywhere clears the test.                  #
# --------------------------------------------------------------------------- #


def test_top_level_assertion_alongside_a_conditional_one_is_exempt():
    src = """
    def test_thing():
        result = compute()
        assert result is not None
        for row in result.rows:
            assert row.id
    """
    assert _check(src) == []


def test_exhaustive_if_else_is_exempt():
    src = """
    def test_thing():
        if cond:
            assert a()
        else:
            assert b()
    """
    assert _check(src) == []


def test_elif_chain_with_a_final_else_is_exempt():
    src = """
    def test_thing():
        if a:
            assert one()
        elif b:
            assert two()
        else:
            assert three()
    """
    assert _check(src) == []


def test_elif_chain_without_a_final_else_still_flags():
    src = """
    def test_thing():
        if a:
            assert one()
        elif b:
            assert two()
    """
    assert len(_check(src)) == 1


def test_branch_that_asserts_opposite_a_branch_that_returns_is_exempt():
    src = """
    def test_thing():
        if cond:
            assert a()
        else:
            return
    """
    assert _check(src) == []


def test_two_branches_that_both_bail_out_assert_nothing():
    src = """
    def test_thing():
        if cond:
            return
        else:
            return
        for row in fetch():
            assert row
    """
    assert len(_check(src)) == 1


def test_top_level_pytest_raises_is_exempt():
    src = """
    import pytest

    def test_thing():
        with pytest.raises(ValueError):
            parse("bad")
        if extra:
            assert other()
    """
    assert _check(src) == []


def test_assert_raises_context_manager_is_exempt():
    src = """
    class TestThing:
        def test_thing(self):
            with self.assertRaisesMessage(ValueError, "bad"):
                parse("bad")
    """
    assert _check(src) == []


def test_top_level_raise_is_exempt():
    # The `raise` is the whole verdict: falling out of the search loop means the
    # fixture never produced the row the test was looking for. Nothing here is
    # named like an assertion, so only the `ast.Raise` arm can clear it.
    src = """
    def test_thing():
        for row in fetch():
            if row.bad:
                assert row.error
                return
        raise RuntimeError("no bad row in the fixture")
    """
    assert _check(src) == []


def test_for_else_clause_that_asserts_is_exempt():
    src = """
    def test_thing():
        for row in fetch():
            if row.bad:
                break
        else:
            assert True is not False
    """
    assert _check(src) == []


def test_match_with_a_wildcard_case_is_exempt():
    src = """
    def test_thing():
        match kind:
            case "a":
                assert one()
            case _:
                assert two()
    """
    assert _check(src) == []


def test_match_without_a_wildcard_case_still_flags():
    src = """
    def test_thing():
        match kind:
            case "a":
                assert one()
            case "b":
                assert two()
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: a one-armed `if` that fails the test is the assertion.             #
# --------------------------------------------------------------------------- #


_AGGREGATOR = """
import pytest

def test_all_models():
    failures = []
    for model in discover():
        if not check(model):
            failures.append(model)
    if failures:
        {verdict}
"""


@pytest.mark.parametrize(
    "verdict",
    [
        'pytest.fail("; ".join(failures))',
        'fail("; ".join(failures))',
        'raise AssertionError("; ".join(failures))',
        "assert False, failures",
        "assert 0",
    ],
)
def test_failure_aggregator_is_the_assertion(verdict: str):
    # litellm tests/e2e/claude_code/**: collect every model's error, fail once.
    assert _check(_AGGREGATOR.format(verdict=verdict)) == []


@pytest.mark.parametrize(
    "verdict",
    [
        'pytest.skip("nothing to check")',
        "log(failures)",
        "assert True",
    ],
)
def test_a_one_armed_if_that_does_not_fail_still_flags(verdict: str):
    # Skipping is not failing, and `assert True` is not a verdict either.
    assert len(_check(_AGGREGATOR.format(verdict=verdict))) == 1


def test_unittest_self_fail_aggregator_is_the_assertion():
    src = """
    class TestThing:
        def test_all(self):
            failures = []
            for model in discover():
                failures.append(model)
            if failures:
                self.fail("some models failed")
    """
    assert _check(src) == []


def test_a_verdict_reached_through_a_nested_if_or_a_with_is_still_a_verdict():
    src = """
    import pytest

    def test_all():
        for model in discover():
            assert model
        if failures:
            with capture_report():
                if strict:
                    pytest.fail("strict")
                else:
                    raise RuntimeError("lenient")
    """
    assert _check(src) == []


def test_a_verdict_on_only_one_arm_of_a_nested_if_still_flags():
    src = """
    import pytest

    def test_all():
        for model in discover():
            assert model
        if failures:
            if strict:
                pytest.fail("strict")
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [("flag or slow_path()", "not flag"), ("not flag", "flag")],
)
def test_complementary_if_elif_without_an_else_is_exempt(first: str, second: str):
    # sentry-python tests/integrations/threading/test_threading.py:224.
    src = f"""
    def test_thing(flag):
        if {first}:
            assert one()
        elif {second}:
            assert two()
    """
    assert _check(src) == []


def test_an_elif_that_does_not_complete_the_chain_still_flags():
    src = """
    def test_thing(flag):
        if flag:
            assert one()
        elif other:
            assert two()
    """
    assert len(_check(src)) == 1


def test_a_complementary_chain_with_a_silent_final_else_still_flags():
    # Writing an `else` after `elif not flag` says the author did not think the
    # chain was total, and the arm they wrote there asserts nothing.
    src = """
    def test_thing(flag):
        if flag:
            assert one()
        elif not flag:
            assert two()
        else:
            log()
    """
    assert len(_check(src)) == 1


def test_a_complementary_chain_whose_first_arm_asserts_nothing_still_flags():
    src = """
    def test_thing(flag):
        if flag:
            log()
        elif not flag:
            assert two()
    """
    assert len(_check(src)) == 1


def test_while_true_runs_its_body_and_is_exempt():
    src = """
    def test_thing():
        while True:
            assert step()
            break
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: the collection was sized before (or after) the loop.               #
# --------------------------------------------------------------------------- #


def test_size_claim_inline_before_the_loop_is_exempt():
    src = """
    def test_thing():
        rows = fetch()
        assert len(rows) == 3
        for row in rows:
            assert row.id
    """
    assert _check(src) == []


def test_size_claim_after_the_loop_is_exempt():
    src = """
    def test_thing():
        rows = fetch()
        for row in rows:
            assert row.id
        assert len(rows) == 3
    """
    assert _check(src) == []


# A size claim made in a *sibling* test is the case that exercises the machinery
# — an inline `assert len(rows) == 3` would clear the test by being an
# unconditional assertion in its own right. A first-party corpus test is
# written exactly this way.
_SIBLING_CLAIM = """
rows = build_rows()

def test_size():
    {claim}

def test_rows():
    for row in rows:
        assert row.id
"""


@pytest.mark.parametrize(
    "claim",
    [
        "assert len(rows) == 3",
        "assert len(rows) > 0",
        "assert len(rows) >= 1",
        "assert len(rows) != 0",
        "assert 3 == len(rows)",
        "assert 0 < len(rows)",
        "assert 1 <= len(rows)",
        "assert rows",
        "assert rows == [1, 2, 3]",
        "assert 7 in rows",
        "self.assertEqual(len(rows), 2)",
        "self.assertEqual(2, len(rows))",
        "self.assertGreater(len(rows), 0)",
        "self.assertGreaterEqual(len(rows), 1)",
        "self.assertTrue(rows)",
        "self.assertEqual(rows, [1, 2])",
        "self.assertIn(7, rows)",
        "self.assertLen(rows, 3)",
    ],
)
def test_a_sibling_size_claim_clears_the_loop(claim: str):
    assert _check(_SIBLING_CLAIM.format(claim=claim)) == []


@pytest.mark.parametrize(
    "claim",
    [
        "assert len(rows) == 0",
        "assert len(other) == 3",
        "assert total > 0",
        # An upper bound is not a lower bound, whichever side `len` reads on.
        "assert len(rows) <= 5",
        "assert 5 > len(rows)",
        "assert 5 >= len(rows)",
        "self.assertEqual(len(rows), 0)",
        "self.assertLess(len(rows), 5)",
        "self.assertLen(rows, 0)",
    ],
)
def test_a_sibling_claim_that_does_not_size_the_loop_still_flags(claim: str):
    assert len(_check(_SIBLING_CLAIM.format(claim=claim))) == 1


def test_an_emptiness_guard_that_bails_out_is_exempt():
    src = """
    import pytest

    def test_thing():
        rows = fetch()
        if not rows:
            pytest.skip("nothing seeded")
        for row in rows:
            assert row.id
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: loops over literal collections.                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "iterable",
    [
        "[1, 2, 3]",
        "(1, 2)",
        "{1, 2}",
        '{"a": 1}.items()',
        '"abc"',
        "range(3)",
        "range(1, 4)",
        "range(0, 10, 2)",
        "range(len([1, 2]))",
        "range(n + 1)",
        "sorted([3, 1])",
        "enumerate(['a'])",
        "list(('a', 'b'))",
        "[x for x in [1, 2]]",
        "zip([1, 2], other)",
        "dict.fromkeys(['a', 'b'], 0).items()",
        '"a,b".split(",")',
        "[0] * 3",
    ],
)
def test_loop_over_a_literal_collection_is_exempt(iterable: str):
    src = f"""
    def test_thing():
        for item in {iterable}:
            assert f(item)
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "iterable",
    [
        "[]",
        "()",
        "{}",
        "range(0)",
        "range(5, 2)",
        # Not the builtin, or not a usable one: no keyword arguments, one to
        # three positional arguments, and a non-zero step.
        "range(stop=3)",
        "range(3, step=2)",
        "range()",
        "range(1, 2, 3, 4)",
        "range(1, 10, 0)",
        "range(2, n)",
        "[x for x in [1, 2] if x > 1]",
        "fetch()",
    ],
)
def test_loop_over_a_possibly_empty_iterable_still_flags(iterable: str):
    src = f"""
    def test_thing():
        for item in {iterable}:
            assert f(item)
    """
    assert len(_check(src)) == 1


def test_loop_over_a_local_bound_to_a_literal_is_exempt():
    src = """
    def test_thing():
        cases = [(1, 2), (3, 4)]
        for a, b in cases:
            assert f(a) == b
    """
    assert _check(src) == []


def test_loop_over_a_module_constant_bound_to_a_literal_is_exempt():
    src = """
    cases = [(1, 2), (3, 4)]

    def test_thing():
        for a, b in cases:
            assert f(a) == b
    """
    assert _check(src) == []


def test_loop_over_a_module_name_bound_to_an_empty_literal_still_flags():
    src = """
    cases = []

    def test_thing():
        for a in cases:
            assert f(a)
    """
    assert len(_check(src)) == 1


def test_loop_over_a_default_argument_literal_is_exempt():
    # celery t/unit/worker/test_state.py:119.
    src = """
    class TestThing:
        def test_merge(self, p, data=["foo", "bar"]):
            for item in data:
                assert item in state.revoked
    """
    assert _check(src) == []


def test_loop_over_an_accumulator_filled_by_a_running_loop_is_exempt():
    src = """
    def test_thing():
        results = []
        for i in range(10):
            results.append(compute(i))
        for result in results:
            assert result is not None
    """
    assert _check(src) == []


def test_loop_over_an_accumulator_filled_by_a_maybe_empty_loop_still_flags():
    src = """
    def test_thing():
        results = []
        for i in fetch():
            results.append(compute(i))
        for result in results:
            assert result is not None
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: parametrize columns whose every row is a non-empty literal.        #
# --------------------------------------------------------------------------- #


def test_loop_over_a_parametrized_non_empty_column_is_exempt():
    src = """
    import pytest

    @pytest.mark.parametrize("present", [["a"], ["b", "c"]])
    def test_thing(present):
        result = render()
        for fragment in present:
            assert fragment in result
    """
    assert _check(src) == []


def test_loop_over_a_parametrized_column_with_an_empty_row_still_flags():
    src = """
    import pytest

    @pytest.mark.parametrize("present", [["a"], []])
    def test_thing(present):
        result = render()
        for fragment in present:
            assert fragment in result
    """
    assert len(_check(src)) == 1


def test_parametrized_column_picked_out_of_a_multi_argument_table():
    src = """
    import pytest

    @pytest.mark.parametrize("name,present", [("x", ["a"]), ("y", ["b", "c"])])
    def test_thing(name, present):
        result = render(name)
        for fragment in present:
            assert fragment in result
    """
    assert _check(src) == []


def test_parametrized_column_reached_through_pytest_param():
    src = """
    import pytest

    @pytest.mark.parametrize(
        "name,present",
        [pytest.param("x", ["a"], id="x"), pytest.param("y", ["b"], id="y")],
    )
    def test_thing(name, present):
        result = render(name)
        for fragment in present:
            assert fragment in result
    """
    assert _check(src) == []


def test_the_wrong_parametrized_column_does_not_clear_the_loop():
    src = """
    import pytest

    @pytest.mark.parametrize("present,absent", [(["a"], []), (["b"], [])])
    def test_thing(present, absent):
        result = render()
        for fragment in absent:
            assert fragment not in result
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: fixed tables — enums, class fixtures, imported constants.          #
# --------------------------------------------------------------------------- #


def test_loop_over_an_enum_class_is_exempt():
    src = """
    def test_every_role_resolves():
        for role in UserRole:
            assert permissions_for_role(role) is not None
    """
    assert _check(src) == []


def test_loop_over_a_lowercase_computed_collection_still_flags():
    src = """
    def test_every_role_resolves():
        for role in discovered_roles():
            assert permissions_for_role(role) is not None
    """
    assert len(_check(src)) == 1


def test_loop_over_a_self_attribute_fixture_is_exempt():
    # django tests/gis_tests/gdal_tests/test_geom.py:75.
    src = """
    class TestThing:
        def test_wkt(self):
            for g in self.geometries.wkt_out:
                self.assertEqual(g.wkt, OGRGeometry(g.wkt).wkt)
    """
    assert _check(src) == []


def test_loop_over_a_class_rooted_chain_is_exempt():
    # django tests/gis_tests/geoapp/test_functions.py:346.
    src = """
    class TestThing:
        def test_envelope(self):
            countries = Country.objects.annotate(envelope=Envelope("mpoly"))
            for country in countries:
                self.assertTrue(country.envelope)
    """
    assert _check(src) == []


def test_loop_over_a_constructed_objects_attribute_is_exempt():
    # django tests/auth_tests/test_validators.py:328.
    src = """
    class TestThing:
        def test_passwords(self):
            validator = CommonPasswordValidator()
            for password in validator.passwords:
                self.assertEqual(password, password.lower())
    """
    assert _check(src) == []


def test_loop_over_an_imported_name_is_exempt():
    # Lowercase on purpose: a capitalised name would be cleared by the CapWords
    # check before the imported-name guard is ever reached.
    src = """
    from voice.filters import srlist

    def test_thing():
        for s in srlist:
            assert filt.process(s) == ""
    """
    assert _check(src) == []


def test_loop_over_the_same_name_unimported_still_flags():
    src = """
    def test_thing():
        for s in srlist:
            assert filt.process(s) == ""
    """
    assert len(_check(src)) == 1


def test_loop_over_a_capitalised_attribute_is_exempt():
    src = """
    def test_thing():
        for code in registry.KNOWN_CODES:
            assert lookup(code) is not None
    """
    assert _check(src) == []


def test_loop_over_a_lowercase_attribute_chain_still_flags():
    src = """
    def test_thing():
        for code in registry.known_codes:
            assert lookup(code) is not None
    """
    assert len(_check(src)) == 1


def test_loop_over_a_passthrough_method_on_a_literal_receiver_is_exempt():
    src = """
    def test_thing():
        rows = [1, 2]
        for item in rows.copy():
            assert item
    """
    assert _check(src) == []


def test_loop_over_a_passthrough_method_on_a_computed_receiver_still_flags():
    src = """
    def test_thing():
        for item in fetch().copy():
            assert item
    """
    assert len(_check(src)) == 1


def test_a_chain_of_aliases_resolves_to_the_literal():
    src = """
    def test_thing():
        a = [1, 2]
        b = a
        c = b
        d = c
        for item in d:
            assert item
    """
    assert _check(src) == []


def test_a_self_referential_binding_terminates_and_still_flags():
    # Both halves of the `+` resolve back to `rows`; without the once-per-path
    # rule this walk branches in two at every step and never finishes.
    src = """
    def test_thing():
        rows = rows + rows
        for row in rows:
            assert row.ok
    """
    assert len(_check(src)) == 1


def test_bindings_that_refer_to_each_other_terminate_and_still_flag():
    # Resolving `rows` reaches `other`, which reaches `rows` again; following a
    # name at most once per path is what stops the walk.
    src = """
    def test_thing():
        rows = other
        other = rows
        for row in rows:
            assert row.ok
    """
    assert len(_check(src)) == 1


def test_loop_over_an_imported_function_call_still_flags():
    # One first-party site loops over a registry lookup this way — the
    # registry could come back empty and the test would go green.
    src = """
    from tools import get_all_tool_classes

    def test_all_tools_appear():
        schemas = generate_tool_schemas()
        for tool_class in get_all_tool_classes():
            assert tool_class.slug in schemas
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: inner loops reached through a proven outer loop.                   #
# --------------------------------------------------------------------------- #


def test_inner_loop_over_the_outer_items_structure_is_exempt():
    src = """
    def test_thing():
        for pair in [(1, 2), (3, 4)]:
            for value in pair.parts:
                assert value
    """
    assert _check(src) == []


def test_inner_loop_when_the_outer_loop_may_be_empty_still_flags():
    src = """
    def test_thing():
        for pair in fetch():
            for value in pair.parts:
                assert value
    """
    assert len(_check(src)) == 1


def test_inner_loop_over_an_unrelated_collection_still_flags():
    src = """
    def test_thing():
        for pair in [(1, 2), (3, 4)]:
            for value in fetch():
                assert value
    """
    assert len(_check(src)) == 1


def test_a_one_armed_if_inside_a_proven_loop_still_flags():
    src = """
    def test_thing():
        for value in [1, 2, 3]:
            if value.interesting:
                assert value.ok
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: a branch that bails out owes no assertion.                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bail",
    [
        'pytest.skip("no gpu")',
        'pytest.xfail("known bad")',
        'pytest.exit("cannot continue")',
        "return",
        "self.skipTest('no gpu')",
        'pytest.importorskip("numpy")',
    ],
)
def test_a_branch_that_bails_out_owes_no_assertion(bail: str):
    # The `else` is the only arm that asserts; the test is clean only because
    # the other arm never reaches the end of the test.
    src = f"""
    import pytest

    class TestThing:
        def test_thing(self):
            if not has_gpu:
                {bail}
            else:
                assert compute() == 1
    """
    assert _check(src) == []


def test_a_guard_that_does_not_bail_out_still_flags():
    src = """
    def test_thing():
        if not has_gpu:
            configure()
        else:
            assert compute() == 1
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize("bail", ["continue", "break"])
def test_a_loop_branch_that_bails_out_owes_no_assertion(bail: str):
    src = f"""
    def test_thing():
        for row in [1, 2]:
            if row.uninteresting:
                {bail}
            else:
                assert row.ok
    """
    assert _check(src) == []


def test_an_early_exit_on_an_unrelated_condition_does_not_size_a_later_loop():
    # The docstring's limit: skipping when there is no GPU says nothing about
    # `fetch()` having returned anything, so this is still a vacuous test.
    src = """
    import pytest

    def test_thing():
        if not has_gpu:
            pytest.skip("no gpu")
        for row in fetch():
            assert row.ok
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: try/except as long-hand assertRaises.                              #
# --------------------------------------------------------------------------- #


def test_try_except_whose_handler_asserts_is_exempt():
    # django tests/forms_tests/field_tests/test_datefield.py:212.
    src = """
    class TestThing:
        def test_strptime(self):
            try:
                f.strptime("31 mai 2011", "%d-%b-%y")
            except Exception as e:
                self.assertEqual(e.__class__, ValueError)
    """
    assert _check(src) == []


def test_try_except_else_that_fails_is_exempt():
    # django tests/admin_views/test_related_object_lookups.py:183.
    src = """
    class TestThing:
        def test_popup(self):
            try:
                self.wait_until(lambda d: len(d.window_handles) == 1, 1)
            except TimeoutException:
                pass
            else:
                self.fail("The popup was unexpectedly closed.")
    """
    assert _check(src) == []


def test_try_whose_only_assertion_is_in_a_loop_still_flags():
    src = """
    def test_thing():
        try:
            for row in fetch():
                assert row
        except ValueError:
            pass
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: capability probes.                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "condition",
    [
        "connection.features.supports_expression_indexes",
        'hasattr(signal, "setitimer")',
        "self.engine.debug",
        "numpy_is_installed",
        "sys.version_info >= (3, 12)",
    ],
)
def test_assertion_gated_on_a_capability_probe_is_exempt(condition: str):
    src = f"""
    class TestThing:
        def test_thing(self):
            if {condition}:
                self.assertEqual(run(), 1)
    """
    assert _check(src) == []


@pytest.mark.parametrize("condition", ["user.is_admin", "record.active", "response.ok"])
def test_assertion_gated_on_ordinary_state_still_flags(condition: str):
    src = f"""
    class TestThing:
        def test_thing(self):
            if {condition}:
                self.assertEqual(run(), 1)
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: sub-tests, hypothesis, nested defs, skips and fixtures.            #
# --------------------------------------------------------------------------- #


def test_unittest_subtest_block_is_exempt():
    src = """
    class TestThing:
        def test_names(self):
            for name in load():
                with self.subTest(name=name):
                    self.assertTrue(name)
    """
    assert _check(src) == []


def test_pytest_subtests_fixture_is_exempt():
    src = """
    def test_names(subtests):
        if retry is False:
            with subtests.test("does not retry"):
                assert connect() is None
    """
    assert _check(src) == []


def test_hypothesis_given_test_is_exempt():
    src = """
    from hypothesis import given

    @given(st.integers())
    def test_thing(value):
        if value > 0:
            assert f(value) > 0
    """
    assert _check(src) == []


def test_assertions_inside_a_nested_def_are_exempt():
    src = """
    import asyncio

    def test_thing():
        async def _run():
            for row in fetch():
                assert row
        asyncio.run(_run())
    """
    assert _check(src) == []


@pytest.mark.parametrize("marker", ["skip", "skipif(True)", "xfail(reason='x')"])
def test_skipped_tests_are_exempt(marker: str):
    src = f"""
    import pytest

    @pytest.mark.{marker}
    def test_thing():
        for row in fetch():
            assert row
    """
    assert _check(src) == []


def test_fixture_is_exempt():
    src = """
    import pytest

    @pytest.fixture
    def test_rows():
        for row in fetch():
            assert row
        yield
    """
    assert _check(src) == []


def test_decorator_that_is_an_asserting_local_helper_is_not_a_body_assertion():
    # django tests/gis_tests/test_gis_tests_utils.py — `@test_mutation()` wraps
    # the body in an assertRaisesMessage; the body itself asserts nothing, so
    # this is SARJ043's business, not ours.
    src = """
    def test_mutation():
        def wrapper(func):
            def test(case):
                with case.assertRaisesMessage(AssertionError, "x"):
                    func()
            return test
        return wrapper

    class TestThing:
        @test_mutation()
        def test_mutated_attribute(func):
            func.attribute = "mutated"
    """
    assert _check(src) == []


def test_nested_function_named_test_is_not_collected():
    src = """
    def test_outer():
        def test_index():
            for row in fetch():
                assert row
        assert test_index is not None
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Boundary with SARJ043: a test with no assertion at all is not this rule.     #
# --------------------------------------------------------------------------- #


def test_a_test_with_no_assertion_anywhere_is_left_to_sarj043():
    src = """
    def test_thing():
        for row in fetch():
            compute(row)
    """
    assert _check(src) == []


def test_a_helper_function_is_not_a_test():
    src = """
    def helper_thing():
        for row in fetch():
            assert row
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
        for row in fetch():
            assert row

    def test_two():
        assert compute()

    def test_three():
        if cond:
            assert compute()
    """
    assert len(_check(src)) == 2


def test_flags_a_fluent_dsl_assertion_inside_a_loop():
    # `result.expect.contains_call(...)` verifies through a marker partway along
    # the chain; without it the test would read as asserting nothing at all and
    # would belong to SARJ043 instead of being reported here.
    src = """
    def test_thing():
        result = analyse()
        for name in result.names:
            result.expect.contains_call(name)
    """
    assert len(_check(src)) == 1


def test_a_fluent_dsl_assertion_outside_the_loop_clears_the_test():
    src = """
    def test_thing():
        result = analyse()
        result.expect.contains_call("send")
        for name in result.names:
            result.expect.contains_call(name)
    """
    assert _check(src) == []


def test_an_ordinary_attribute_call_in_a_loop_is_not_an_assertion():
    src = """
    def test_thing():
        for row in fetch():
            client.send(row)
    """
    assert _check(src) == []


def test_local_helper_that_asserts_counts_as_the_assertion():
    src = """
    def _compare(actual, expected):
        assert actual == expected

    def test_thing():
        result = compute()
        _compare(result, 3)
        for row in result.rows:
            _compare(row.id, 1)
    """
    assert _check(src) == []
