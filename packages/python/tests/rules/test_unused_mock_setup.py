from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.unused_mock_setup import UnusedMockSetup


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/unit/test_billing.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return UnusedMockSetup().check(Path(path), textwrap.dedent(source))


_OVERWRITTEN = """
def test_charge():
    gateway.charge.return_value = 1
    gateway.charge.return_value = 2
    assert billing.charge(gateway) == 2
"""

_ASSERTED_NOT_CALLED = """
def test_no_bearer_skips_lookup():
    subject_service.extract_api_key_user.return_value = None
    client.get("/mcp/test")
    subject_service.extract_api_key_user.assert_not_called()
"""


# --------------------------------------------------------------------------- #
# Path gating.                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/y.py", "conftest.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_OVERWRITTEN, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py", "billing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_OVERWRITTEN, path) == []


# --------------------------------------------------------------------------- #
# Shape A: the configuration is overwritten before anything can read it.       #
# --------------------------------------------------------------------------- #


def test_flags_adjacent_overwrite():
    assert len(_check(_OVERWRITTEN)) == 1


def test_flags_overwritten_side_effect():
    src = """
def test_charge():
    gateway.charge.side_effect = ValueError
    gateway.charge.side_effect = TypeError
    billing.charge(gateway)
"""
    assert len(_check(src)) == 1


def test_flags_overwrite_of_a_deep_path():
    src = """
def test_set():
    self.backend.one_client.kv.get.return_value = (1, {})
    self.backend.one_client.kv.get.return_value = (2, {})
    assert self.backend.get("k")
"""
    assert len(_check(src)) == 1


def test_flags_three_writes_as_two_findings():
    src = """
def test_charge():
    gateway.charge.return_value = 1
    gateway.charge.return_value = 2
    gateway.charge.return_value = 3
    assert billing.charge(gateway) == 3
"""
    assert len(_check(src)) == 2


def test_message_names_the_overwriting_line():
    [diag] = _check(_OVERWRITTEN)
    assert "overwritten on line 4" in diag.message
    assert "`gateway.charge.return_value`" in diag.message


def test_reports_the_first_of_the_pair():
    [diag] = _check(_OVERWRITTEN)
    assert (diag.line, diag.col) == (3, 5)
    assert diag.code == "SARJ064"


@pytest.mark.parametrize(
    "filler",
    [
        pytest.param("expected = 7", id="literal-assign"),
        pytest.param("expected = [1, 2, {'a': 'b'}]", id="literal-collection"),
        pytest.param("pass", id="pass"),
        pytest.param("import json", id="import"),
        pytest.param('"a note about the mock"', id="string-expression"),
        pytest.param("other_mock.ping.return_value = 1", id="other-mock-config"),
    ],
)
def test_inert_statements_between_the_writes_still_flag(filler: str):
    src = f"""
def test_charge():
    gateway.charge.return_value = 1
    {filler}
    gateway.charge.return_value = 2
    assert billing.charge(gateway) == 2
"""
    assert len(_check(src)) == 1


# ---- false-positive guards: something in between could have read the value ----


@pytest.mark.parametrize(
    "filler",
    [
        pytest.param("billing.charge(gateway)", id="call"),
        pytest.param("result = billing.charge(gateway)", id="call-in-assignment"),
        pytest.param("value = config.timeout", id="attribute-load-may-be-a-property"),
        pytest.param("value = rows[0]", id="subscript-may-be-getitem"),
        pytest.param("config.timeout = 3", id="attribute-store-may-be-a-setter"),
        pytest.param("rows[0] = 3", id="subscript-store-may-be-setitem"),
        pytest.param("del gateway.charge", id="del"),
        pytest.param("return None", id="return"),
        pytest.param("assert gateway.charge() == 1", id="assert-that-calls"),
    ],
)
def test_effectful_statement_between_the_writes_is_exempt(filler: str):
    src = f"""
def test_charge():
    gateway.charge.return_value = 1
    {filler}
    gateway.charge.return_value = 2
    assert billing.charge(gateway) == 2
"""
    assert _check(src) == []


def test_await_between_the_writes_is_exempt():
    src = """
async def test_charge():
    gateway.charge.return_value = 1
    await billing.charge(gateway)
    gateway.charge.return_value = 2
    assert await billing.charge(gateway) == 2
"""
    assert _check(src) == []


def test_nested_def_between_the_writes_is_exempt():
    # celery's `raise_on_second_call` closure reassigns `setuid.side_effect`
    # and is *called* later, so the pair is not dead.
    src = """
def test_with_uid():
    def raise_on_second_call(*args):
        setuid.side_effect = OSError()

    setuid.side_effect = raise_on_second_call
    maybe_drop_privileges(uid="user")
"""
    assert _check(src) == []


def test_a_write_inside_a_nested_def_does_not_pair_with_one_outside():
    src = """
def test_with_uid():
    setuid.side_effect = first
    def bump(*args):
        setuid.side_effect = OSError()
    maybe_drop_privileges(uid="user")
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "nested",
    [
        pytest.param("if flag:\n        gateway.charge.return_value = 2", id="if"),
        pytest.param("with patch('x'):\n        gateway.charge.return_value = 2", id="with"),
        pytest.param("for _ in range(2):\n        gateway.charge.return_value = 2", id="for"),
        pytest.param("try:\n        gateway.charge.return_value = 2\n    except OSError:\n        pass", id="try"),
    ],
)
def test_a_write_in_a_nested_block_does_not_pair_with_the_outer_one(nested: str):
    src = f"""
def test_charge():
    gateway.charge.return_value = 1
    {nested}
    assert billing.charge(gateway)
"""
    assert _check(src) == []


def test_two_writes_inside_the_same_nested_block_still_flag():
    src = """
def test_charge():
    if flag:
        gateway.charge.return_value = 1
        gateway.charge.return_value = 2
    assert billing.charge(gateway)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            "gateway.charge.return_value = 1", "gateway.charge.side_effect = ValueError", id="return-then-side-effect"
        ),
        pytest.param(
            "gateway.charge.side_effect = None", "gateway.charge.return_value = 1", id="side-effect-cleared-then-return"
        ),
        pytest.param("gateway.charge.return_value = 1", "gateway.refund.return_value = 2", id="different-attribute"),
        pytest.param("alpha.charge.return_value = 1", "beta.charge.return_value = 2", id="different-mock"),
        pytest.param(
            "gateway.charge.return_value = 1",
            "gateway.charge.return_value.ok = True",
            id="mutating-the-configured-value",
        ),
    ],
)
def test_writes_to_different_targets_are_exempt(first: str, second: str):
    src = f"""
def test_charge():
    {first}
    {second}
    assert billing.charge(gateway)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Shape B: the test asserts the configured path was never called.              #
# --------------------------------------------------------------------------- #


def test_flags_configuration_contradicted_by_assert_not_called():
    assert len(_check(_ASSERTED_NOT_CALLED)) == 1


def test_flags_assert_not_awaited():
    src = """
async def test_skips_lookup():
    service.lookup.return_value = None
    await handle(request)
    service.lookup.assert_not_awaited()
"""
    assert len(_check(src)) == 1


def test_flags_when_the_assertion_is_on_a_dotted_prefix():
    # `client.get` is never called, so configuring the response it would have
    # returned is dead too.
    src = """
def test_skips_fetch():
    client.get.return_value.json.return_value = {"a": 1}
    service.run()
    client.get.assert_not_called()
"""
    assert len(_check(src)) == 1


def test_flags_side_effect_configuration_too():
    src = """
def test_skips_lookup():
    service.lookup.side_effect = ValueError
    handle(request)
    service.lookup.assert_not_called()
"""
    assert len(_check(src)) == 1


def test_flags_inside_a_test_method():
    src = """
class TestIndex:
    def test_conflict_leaves_update_alone(self):
        x._server.update.return_value = {"result": "updated"}
        x._set_with_state(task_id, result, state)
        x._server.update.assert_not_called()
"""
    assert len(_check(src)) == 1


def test_trailing_plain_assertions_do_not_rescue_the_setup():
    src = """
def test_skips_lookup():
    service.lookup.return_value = None
    handle(request)
    service.lookup.assert_not_called()
    assert sink.entries[0].auth_method == "none"
"""
    assert len(_check(src)) == 1


def test_trailing_assertion_call_on_another_mock_does_not_rescue_the_setup():
    src = """
def test_skips_lookup():
    service.lookup.return_value = None
    handle(request)
    service.lookup.assert_not_called()
    audit.record.assert_called_once_with("none")
"""
    assert len(_check(src)) == 1


def test_message_names_the_asserted_path():
    [diag] = _check(_ASSERTED_NOT_CALLED)
    assert "`subject_service.extract_api_key_user`" in diag.message
    assert "never" in diag.message


# ---- false-positive guards: the assertion is a checkpoint, not the verdict ----


@pytest.mark.parametrize(
    "positive",
    [
        pytest.param("service.lookup.assert_called_once()", id="assert_called_once"),
        pytest.param("service.lookup.assert_called_with(1)", id="assert_called_with"),
        pytest.param("service.lookup.assert_awaited_once()", id="assert_awaited_once"),
        pytest.param("service.lookup.assert_has_calls([call(1)])", id="assert_has_calls"),
        pytest.param("service.lookup.assert_any_call(1)", id="assert_any_call"),
        pytest.param("assert service.lookup.call_count == 2", id="call_count"),
        pytest.param("assert service.lookup.called", id="called"),
        pytest.param("assert service.lookup.call_args.args == (1,)", id="call_args"),
        pytest.param("assert service.lookup.await_count == 1", id="await_count"),
        pytest.param("service.lookup.reset_mock()", id="reset_mock"),
        pytest.param("assert service.assert_called_once", id="positive-on-the-base-mock"),
        pytest.param("service.lookup.inner.assert_called_once()", id="positive-on-an-extension"),
    ],
)
def test_a_positive_call_assertion_anywhere_exempts_the_setup(positive: str):
    # `pool_close.assert_not_awaited()` then `await shutdown()` then
    # `pool_close.assert_awaited_once()` is a mid-test checkpoint; the setup
    # fires two lines later.
    src = f"""
def test_lookup_is_deferred():
    service.lookup.return_value = None
    handle(request)
    service.lookup.assert_not_called()
    {positive}
"""
    assert _check(src) == []


def test_a_positive_assertion_on_a_sibling_path_does_not_exempt():
    # `x._server.get` being called says nothing about `x._server.update`.
    src = """
def test_conflict():
    x._server.update.return_value = {"result": "updated"}
    x._set_with_state(task_id, result, state)
    assert x._server.get.call_count == 1
    x._server.index.assert_called_once_with(id=task_id)
    x._server.update.assert_not_called()
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param("handle(other_request)", id="second-act"),
        pytest.param("result = handle(other_request)", id="second-act-with-result"),
        pytest.param("assert handle(other_request) is None", id="second-act-inside-assert"),
        pytest.param("service.lookup.return_value = 2\n    handle(other_request)", id="reconfigured-then-second-act"),
    ],
)
def test_code_after_the_assertion_that_can_run_the_mock_is_exempt(tail: str):
    src = f"""
def test_lookup():
    service.lookup.return_value = None
    handle(request)
    service.lookup.assert_not_called()
    {tail}
    assert True
"""
    assert _check(src) == []


def test_reconfiguring_after_the_assertion_without_a_second_act_still_flags():
    # Nothing runs after either write, so both the assertion and the rewrite
    # confirm the first value was never observed.
    src = """
def test_lookup():
    service.lookup.return_value = None
    handle(request)
    service.lookup.assert_not_called()
    service.lookup.return_value = 2
    assert True
"""
    assert len(_check(src)) == 1


def test_an_await_after_the_assertion_is_exempt():
    src = """
async def test_lookup():
    service.lookup.return_value = None
    await handle(request)
    service.lookup.assert_not_called()
    await shutdown()
"""
    assert _check(src) == []


def test_assertion_before_the_configuration_is_exempt():
    # The assertion describes the state *before* the arrange block; the setup
    # is for whatever the test does next.
    src = """
def test_lookup():
    service.lookup.assert_not_called()
    service.lookup.return_value = None
    assert True
"""
    assert _check(src) == []


def test_assert_not_called_on_an_unrelated_path_is_exempt():
    src = """
def test_lookup():
    service.lookup.return_value = None
    handle(request)
    audit.record.assert_not_called()
"""
    assert _check(src) == []


def test_assert_not_called_on_an_extension_of_the_configured_path_is_exempt():
    # `service.lookup.inner` never being called says nothing about whether
    # `service.lookup` itself returned the configured value.
    src = """
def test_lookup():
    service.lookup.return_value = None
    handle(request)
    service.lookup.inner.assert_not_called()
"""
    assert _check(src) == []


def test_assert_not_called_in_a_nested_helper_does_not_reach_the_outer_setup():
    src = """
def test_lookup():
    service.lookup.return_value = None

    def _later():
        service.lookup.assert_not_called()

    register(_later)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Shapes the rule deliberately cannot see — documented in the docstring.       #
# --------------------------------------------------------------------------- #


def test_a_configured_path_never_mentioned_again_is_not_flagged():
    # The dominant real-world shape and the reason shape 1 was dropped: the SUT
    # is handed the whole mock and picks `.refund` off it.
    src = """
def test_charge():
    gateway = MagicMock()
    gateway.charge.return_value = Receipt(ok=True)
    gateway.refund.return_value = Receipt(ok=True)
    result = billing.charge(gateway, 100)
    assert result.ok
"""
    assert _check(src) == []


def test_a_patch_bound_mock_configured_and_never_mentioned_is_not_flagged():
    src = """
def test_never_cache_headers():
    with mock.patch("time.time") as mocked_time:
        mocked_time.return_value = 1167616461.0
        response = never_cache(view)(request)
    assert response.headers["Expires"] == "Thu, 01 Jan 1970 00:00:00 GMT"
"""
    assert _check(src) == []


def test_an_entirely_unused_mock_is_left_to_ruff_f841():
    src = """
def test_charge():
    gateway = MagicMock()
    assert billing.charge(real_gateway, 100).ok
"""
    assert _check(src) == []


def test_configure_mock_keys_are_not_flagged():
    src = """
def test_charge():
    gateway.configure_mock(**{"refund.return_value": Receipt(ok=True)})
    assert billing.charge(gateway, 100).ok
"""
    assert _check(src) == []


def test_a_fixture_configuring_a_mock_for_its_caller_is_not_flagged():
    src = """
@pytest.fixture
def gateway():
    mock_gateway = MagicMock()
    mock_gateway.charge.return_value = Receipt(ok=True)
    return mock_gateway
"""
    assert _check(src) == []


def test_setup_method_configuring_a_shared_mock_is_not_flagged():
    src = """
class TestBilling:
    def setup_method(self):
        self.gateway = MagicMock()
        self.gateway.charge.return_value = Receipt(ok=True)

    def test_charge(self):
        assert billing.charge(self.gateway, 100).ok
"""
    assert _check(src) == []


def test_module_level_configuration_is_not_flagged():
    src = """
gateway.charge.return_value = 1
gateway.charge.return_value = 2
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    m.a.return_value = 1\n") == []


def test_a_config_target_not_rooted_in_a_name_is_ignored():
    src = """
def test_charge():
    make_gateway().charge.return_value = 1
    make_gateway().charge.return_value = 2
    assert billing.charge(gateway)
"""
    assert _check(src) == []


def test_chained_assignment_is_ignored():
    src = """
def test_charge():
    gateway.charge.return_value = gateway.refund.return_value = 1
    gateway.charge.return_value = 2
    assert billing.charge(gateway)
"""
    assert _check(src) == []


def test_a_statement_dead_under_both_shapes_is_reported_once():
    src = """
def test_lookup():
    service.lookup.return_value = 1
    service.lookup.return_value = 2
    handle(request)
    service.lookup.assert_not_called()
"""
    assert len(_check(src)) == 2


def test_multiple_hits_in_one_file_are_sorted_by_position():
    src = """
def test_one():
    m.a.return_value = 1
    m.a.return_value = 2
    run(m)

def test_two():
    assert run(m)

def test_three():
    m.b.return_value = 1
    m.b.return_value = 2
    run(m)
"""
    diags = _check(src)
    assert [d.line for d in diags] == [3, 11]


def test_diagnostics_carry_the_rule_code():
    assert all(d.code == "SARJ064" for d in _check(_ASSERTED_NOT_CALLED))
