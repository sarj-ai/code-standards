from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.interaction_only_test import InteractionOnlyTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/integrations/test_zoho_notifications_handler.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return InteractionOnlyTest().check(Path(path), source)


# The motivating shape, widened to two collaborators so it clears the
# distinct-target gate: notify tells the mailer and the audit log, and the test
# never looks at what `notify` returned.
_INTERACTION_ONLY = """
def test_send_notification():
    mailer = MagicMock()
    audit = MagicMock()
    notify(mailer, audit, user)
    mailer.send.assert_called_once_with(user.email)
    audit.record.assert_called_once_with("notified")
"""


# --------------------------------------------------------------------------- #
# Path gating, matching SARJ043: only pytest-collected modules.                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py"])
def test_fires_in_collected_test_paths(path: str):
    assert len(_check(_INTERACTION_ONLY, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_INTERACTION_ONLY, path) == []


@pytest.mark.parametrize(
    "path",
    ["tests/conftest.py", "tests/fakes.py", "tests/helpers.py", "black/tests/data/cases/fmtonoff5.py"],
)
def test_skips_modules_pytest_does_not_collect(path: str):
    # Helper modules and formatter fixtures are not collected, so a "test" in
    # them is not a test.
    assert _check(_INTERACTION_ONLY, path) == []


@pytest.mark.parametrize("path", ["scripts/test_probe.py", "chat/scripts/test_llm_providers.py"])
def test_skips_uncollected_script_probes(path: str):
    assert _check(_INTERACTION_ONLY, path) == []


# --------------------------------------------------------------------------- #
# Positive: every assertion is mock call bookkeeping.                          #
# --------------------------------------------------------------------------- #


def test_flags_the_motivating_shape():
    assert len(_check(_INTERACTION_ONLY)) == 1


def test_message_is_exactly_the_advice_we_mean_to_give():
    [diag] = _check(_INTERACTION_ONLY)
    assert diag.message == (
        "every assertion in `test_send_notification` is about which calls landed on a mock, so it "
        "pins today's call sequence and goes red on a refactor that changes nothing observable. "
        "Assert on the outcome — the returned value, the persisted row, the rendered body — and "
        "keep interaction assertions for side effects you genuinely cannot observe."
    )


def test_reports_line_column_and_code():
    [diag] = _check(_INTERACTION_ONLY)
    assert (diag.line, diag.col, diag.code) == (2, 1, "SARJ063")


def test_reports_the_position_of_a_nested_test_not_the_module_start():
    # The `def` sits on line 4 at column 9, indented inside two nested classes,
    # so neither coordinate is 1 and a hardcoded position cannot pass.
    src = """
class TestOuter:
    class TestInner:
        def test_nested(self):
            handle(store, bus)
            store.save.assert_called_once()
            bus.emit_event.assert_called_once()
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (4, 9)


def test_flags_async_awaited_assertions():
    src = """
async def test_update_fetches_full_lead_from_crm():
    await route_event(handler, payload, crm_service)
    crm_service.get_record.assert_awaited_once_with(module=LEADS, record_id="lead_1")
    call_service.outbound.assert_awaited_once()
"""
    assert len(_check(src)) == 1


def test_flags_test_method_in_a_class():
    src = """
class TestThing:
    def test_get_key(self, mock_get_blob):
        backend.get(b"testkey1")
        mock_get_blob.assert_called_once_with("testkey1")
        mock_blob.download_as_bytes.assert_called_once()
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "assertions",
    [
        pytest.param("assert store.save.called\n    assert bus.emit_event.called", id="called-attr"),
        pytest.param("assert store.save.call_count == 2\n    assert bus.emit_event.call_count == 1", id="call-count"),
        pytest.param(
            'assert store.save.call_args.kwargs["id"] == 3\n    assert bus.emit_event.call_args[0][0] == "x"',
            id="call-args",
        ),
        pytest.param(
            "assert store.save.mock_calls == [call(1)]\n    assert bus.emit_event.mock_calls", id="mock-calls"
        ),
        pytest.param(
            "assert store.save.await_count == 1\n    assert bus.emit_event.await_count == 1", id="await-count"
        ),
        pytest.param(
            "store.save.assert_has_calls([call(1)])\n    bus.emit_event.assert_any_call('x')",
            id="has-calls-any-call",
        ),
    ],
)
def test_flags_every_spelling_of_a_mock_state_assertion(assertions: str):
    src = f"""
def test_thing():
    handle(store, bus)
    {assertions}
"""
    assert len(_check(src)) == 1


def test_flags_unittest_style_interaction_assertions():
    # `self.assertEqual(m.call_count, 2)` is an interaction assertion wearing a
    # unittest coat, not an outcome assertion.
    src = """
class TestThing(TestCase):
    def test_thing(self):
        handle(sender, logger)
        self.assertEqual(sender.deliver.call_count, 2)
        self.assertEqual(logger.info.call_args[0][0], "sent")
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: one non-interaction assertion is enough to clear the test.         #
# This is the boundary with SARJ043, which fires only on zero assertions.      #
# --------------------------------------------------------------------------- #


def test_an_outcome_assertion_alongside_the_interaction_is_exempt():
    # The sibling of the flagged test in the same bulbul class does exactly
    # this: it reads `call_args.kwargs` *and* asserts on the payload.
    src = """
def test_create_contact_uses_webhook_data_directly():
    route_event(handler, payload, crm_service)
    call_service.outbound.assert_called_once()
    crm_service.get_record.assert_called_once()
    variables = call_service.outbound.call_args.kwargs["call_input"].scenario.variables
    assert variables["zoho_module"] == "Contacts"
"""
    assert _check(src) == []


def test_pytest_raises_counts_as_an_outcome_assertion():
    src = """
import pytest

def test_thing():
    with pytest.raises(ValueError):
        handle(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("assert_matches(result, expected)", id="assert-helper"),
        pytest.param("self.assertEqual(result, 3)", id="unittest-helper"),
        pytest.param("verify_payload(result)", id="verify-helper"),
        pytest.param("result.expect.contains_function_call(name='x')", id="fluent-dsl"),
        pytest.param("pytest.fail('nope')", id="pytest-fail"),
    ],
)
def test_a_non_mock_verification_clears_the_test(call: str):
    src = f"""
import pytest

def test_thing():
    result = handle(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
    {call}
"""
    assert _check(src) == []


def test_module_local_helper_that_asserts_an_outcome_is_exempt():
    src = """
def _assert_saved(result):
    assert result.status == "saved"

def test_thing():
    result = handle(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
    _assert_saved(result)
"""
    assert _check(src) == []


def test_module_local_helper_that_only_asserts_interactions_still_flags():
    src = """
def _assert_called(store, bus):
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()

def test_thing():
    handle(store, bus)
    _assert_called(store, bus)
"""
    assert len(_check(src)) == 1


def test_helper_reached_through_another_helper_is_followed():
    src = """
def _check_outcome(result):
    assert result.status == "saved"

def _verify(result):
    _check_outcome(result)

def test_thing():
    result = handle(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
    _verify(result)
"""
    assert _check(src) == []


def test_calling_another_modules_test_is_exempt():
    src = """
from docs_src.app_testing.tutorial002 import test_read_main

def test_main():
    test_read_main()
    client.get.assert_called_once()
    client.post.assert_called_once()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a single collaborator is one notification, not a sequence. Counted  #
# by root object, matching SARJ062: a collaborator is an object, not one of its #
# methods. 56 of the 60 raw django findings were this shape, and counting whole #
# dotted paths instead of roots let one mock satisfy the gate on its own —      #
# 799 of 1,261 OSS findings (63%).                                             #
# --------------------------------------------------------------------------- #


def test_count_and_args_on_one_mock_is_a_single_contract():
    # django/tests/utils_tests/test_autoreload.py:642 — the reloader's whole
    # observable output is the notify callback.
    src = """
class TestThing:
    def test_glob(self, mocked_modules, notify_mock):
        self.reloader.watch_dir(self.tempdir, "*.py")
        self.assertEqual(notify_mock.call_count, 1)
        self.assertCountEqual(notify_mock.call_args[0], [self.existing_file])
"""
    assert _check(src) == []


def test_two_methods_of_one_mock_is_one_collaborator():
    # One object asked two questions is one fact about one collaborator.
    src = """
def test_thing():
    creation.setup_worker_connection(2)
    mock_source_db.backup.assert_called_once_with(mock_target_db)
    mock_source_db.close.assert_called_once()
"""
    assert _check(src) == []


def test_the_same_two_methods_split_across_two_mocks_fires():
    # Removing the root reduction — pinning `backup` and `close` on *different*
    # objects — is the sequence-across-collaborators shape the rule is for.
    src = """
def test_thing():
    creation.setup_worker_connection(2)
    mock_source_db.backup.assert_called_once_with(mock_target_db)
    mock_target_db.close.assert_called_once()
"""
    assert len(_check(src)) == 1


def test_methods_reached_through_return_value_are_one_collaborator():
    # airflow .../operators/test_datafusion.py:221 — three questions asked of
    # one patched hook, a thin adapter passthrough with nothing else observable.
    src = """
class TestStartPipelineOperator:
    def test_execute_check_hook_call(self, mock_hook):
        op.execute(context=MagicMock())
        mock_hook.return_value.get_instance.assert_called_once_with(name=INSTANCE)
        mock_hook.return_value.start_pipeline.assert_called_once_with(name=PIPELINE)
        mock_hook.return_value.wait_for_pipeline_state.assert_called_once_with(timeout=300)
"""
    assert _check(src) == []


def test_the_patched_class_and_its_return_value_are_one_collaborator():
    # airflow .../hooks/test_dataproc_metastore.py:265.
    src = """
class TestHook:
    def test_restore_service(self, mock_client):
        self.hook.restore_service(project_id=PROJECT)
        mock_client.assert_called_once()
        mock_client.return_value.restore_service.assert_called_once_with(request={})
"""
    assert _check(src) == []


def test_mocks_held_on_self_share_the_self_root():
    # A deliberate calibration: `self.conn` / `self.cur` collapse to `self`.
    # Making `self.` transparent restores 20 airflow DBAPI-adapter findings and
    # nothing anywhere else, so the plain root split is what ships.
    src = """
class TestDbApiHook:
    def test_insert_rows(self):
        self.db_hook.insert_rows("table", [("hello",)])
        self.cur.execute.assert_any_call("INSERT INTO table VALUES (%s)", ("hello",))
        assert self.conn.commit.call_count == 2
"""
    assert _check(src) == []


def test_a_single_interaction_assertion_never_fires():
    src = """
def test_thing():
    notify(mailer, user)
    mailer.send.assert_called_once_with(user.email)
"""
    assert _check(src) == []


def test_repeated_assertions_on_the_same_target_never_fire():
    src = """
def test_thing():
    handle(store)
    store.save.assert_any_call(1)
    store.save.assert_any_call(2)
    assert store.save.call_count == 2
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: negative claims. Pure negative space, or a routing contract like    #
# django/tests/check_framework/test_multi_db.py:23.                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "negative",
    [
        pytest.param("other.charge.assert_not_called()", id="assert-not-called"),
        pytest.param("other.charge.assert_not_awaited()", id="assert-not-awaited"),
        pytest.param("assert not other.charge.called", id="assert-not-called-attr"),
        pytest.param("assert other.charge.call_count == 0", id="call-count-zero"),
        pytest.param("assert other.charge.call_args is None", id="call-args-none"),
        pytest.param("self.assertFalse(other.charge.called)", id="unittest-assert-false"),
        pytest.param("self.assertEqual(other.charge.call_count, 0)", id="unittest-equal-zero"),
    ],
)
def test_any_negative_interaction_assertion_is_exempt(negative: str):
    src = f"""
class TestThing:
    def test_thing(self):
        charge_once(card, other)
        card.charge.assert_called_once_with(100)
        {negative}
"""
    assert _check(src) == []


def test_the_same_test_with_the_negative_made_positive_fires():
    src = """
class TestThing:
    def test_thing(self):
        charge_once(card, other)
        card.charge.assert_called_once_with(100)
        other.charge.assert_called_once_with(50)
"""
    assert len(_check(src)) == 1


def test_routing_contract_asserting_one_backend_and_not_the_other_is_exempt():
    src = """
class TestMultiDBChecks:
    def test_checks_on_the_default_database(self):
        model.check(databases={"default", "other"})
        self.assertTrue(mock_check_field_default.called)
        self.assertFalse(mock_check_field_other.called)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: the test name declares the interaction is the contract.            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "test_publishes_downstream_tasks",
        "test_emit_event_on_success",
        "test_dispatch_to_worker",
        "test_broadcast_to_all_nodes",
        "test_retry_calls_transport_three_times",
        "test_retries_with_backoff",
        "test_cache_serves_on_second_get",
        "test_idempotent_replay",
        "test_debounce_window",
        "test_throttling_limits_sends",
        "test_only_once_per_window",
    ],
)
def test_names_declaring_an_interaction_contract_are_exempt(name: str):
    src = f"""
def {name}():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["test_never_gives_up", "test_lazy_loader", "test_does_not_reorder"])
def test_names_the_exemption_deliberately_does_not_cover_still_fire(name: str):
    # An earlier draft matched these too and gutted the rule; they describe the
    # behaviour under test, not an interaction contract.
    src = f"""
def {name}():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: callback registration has no observable result.                    #
# celery/t/unit/fixups/test_django.py:183, bulbul test_silence_monitor.py:79.  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Every pair spans two root objects on purpose: a pair sharing a root
        # never reaches this guard, so it would pass for the wrong reason.
        pytest.param("worker_sigs.task_prerun.connect", "beat_sigs.task_postrun.connect", id="signal-connect"),
        pytest.param("room.on", "session.on", id="event-on"),
        pytest.param("room.off", "session.off", id="event-off"),
        pytest.param("bus.subscribe", "other.unsubscribe", id="subscribe"),
        pytest.param("registry.register", "other.unregister", id="register"),
        pytest.param("emitter.add_listener", "other_emitter.remove_listener", id="listeners"),
    ],
)
def test_registration_only_pins_are_exempt(first: str, second: str):
    src = f"""
def test_thing():
    monitor.start()
    {first}.assert_any_call("a", handler)
    {second}.assert_any_call("b", handler)
"""
    assert _check(src) == []


def test_one_non_registration_target_alongside_a_registration_still_fires():
    # bulbul agent/tests/test_collect_digits_tool.py:598 — deregistering the
    # listener is un-observable, but asserting `super().on_exit()` was awaited
    # is pinning the implementation.
    src = """
async def test_on_exit_unregisters_local_user_state_listener():
    await task.on_exit()
    mock_session.off.assert_any_call("user_state_changed", task._on_user_state_changed_local)
    mock_super_on_exit.assert_awaited_once()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: every target is a patched free function, so no object exists whose  #
# state the test could have asserted on instead.                               #
# --------------------------------------------------------------------------- #


def test_patched_free_functions_only_are_exempt():
    # celery/t/unit/utils/test_platforms.py:327 — `setuid` returns nothing and
    # `os.setuid` has no observable result.
    src = """
def test_setuid(_setuid, parse_uid):
    setuid("user")
    parse_uid.assert_called_with("user")
    _setuid.assert_called_with(5001)
"""
    assert _check(src) == []


def test_patched_lifecycle_hooks_are_exempt():
    # django/tests/test_utils/test_simpletestcase.py:88.
    src = """
class TestThing:
    def test_debug_cleanup(self, _pre_setup, _post_teardown):
        test_suite.debug()
        _pre_setup.assert_called_once_with()
        _post_teardown.assert_called_once_with()
"""
    assert _check(src) == []


def test_one_method_on_a_held_object_makes_it_fire_again():
    src = """
def test_get_key(mock_get_blob):
    backend.get(b"testkey1")
    mock_get_blob.assert_called_once_with("testkey1")
    mock_blob.download_as_bytes.assert_called_once()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: pytest collection — skipped, fixtures, stubs, nested defs.         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("marker", ["skip", "skipif(True)", "xfail(reason='x')"])
def test_skipped_tests_are_exempt(marker: str):
    src = f"""
import pytest

@pytest.mark.{marker}
def test_thing():
    handle(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert _check(src) == []


def test_fixture_named_like_a_test_is_exempt():
    src = """
import pytest

@pytest.fixture
def test_apps(monkeypatch):
    build(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
    yield
"""
    assert _check(src) == []


def test_non_test_helper_function_is_exempt():
    src = """
def check_wiring():
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert _check(src) == []


def test_nested_function_named_test_is_not_collected():
    src = """
def test_subdomain_matching(app, client):
    @app.route("/", subdomain="test")
    def test_index():
        store.save.assert_called_once()
        bus.emit_event.assert_called_once()

    rv = client.get("/")
    assert rv.data == b"test index"
"""
    assert _check(src) == []


def test_stub_body_is_exempt():
    assert _check("def test_thing():\n    ...\n") == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    thing()\n") == []


def test_a_test_with_no_assertion_at_all_is_left_to_sarj043():
    src = """
def test_thing():
    handle(store, bus)
"""
    assert _check(src) == []


def test_a_name_merely_containing_assert_called_is_not_a_mock_assertion():
    # `assert_called_the_hard_way` is not unittest.mock's API, but a helper that
    # verifies something is still a verification either way.
    src = """
def test_thing():
    result = handle(store, bus)
    assert result == 3
    store.save.assert_called_once()
"""
    assert _check(src) == []


def test_multiple_hits_in_one_file():
    src = """
def test_one():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()

def test_two():
    result = run(store, bus)
    assert result == 3
    store.save.assert_called_once()

def test_three():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert len(_check(src)) == 2


def test_diagnostics_are_sorted_by_position():
    src = """
def test_a():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()

def test_b():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()

def test_c():
    run(store, bus)
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_assertions_in_a_nested_run_wrapper_are_counted():
    src = """
import asyncio

def test_thing():
    async def _run():
        result = await compute(store, bus)
        assert result == 3
    asyncio.run(_run())
    store.save.assert_called_once()
    bus.emit_event.assert_called_once()
"""
    assert _check(src) == []
