from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.over_mocked_test import OverMockedTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/agent/tests/test_agent_tools.py"

_IMPORT = "from unittest import mock\nfrom unittest.mock import MagicMock, Mock, patch\n"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return OverMockedTest().check(Path(path), _IMPORT + textwrap.dedent(source))


def _patches(count: int, prefix: str = "app.mod") -> str:
    """Build a test decorated with `count` distinct `@patch`es.

    Returns:
        The source of a single test function at the requested mock count.

    """
    decorators = "\n".join(f'@patch("{prefix}{i}.collaborator")' for i in range(count))
    params = ", ".join(f"m{i}" for i in range(count))
    return f"{decorators}\ndef test_thing({params}):\n    assert run() == 1\n"


# --------------------------------------------------------------------------- #
# The threshold. Measured across 30,678 corpus tests: 99.96% sit at five or     #
# below, so the rule fires above five.                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5], ids=lambda n: f"{n}-mocks-clean")
def test_at_or_below_the_threshold_is_clean(count: int):
    assert _check(_patches(count)) == []


@pytest.mark.parametrize("count", [6, 7, 9], ids=lambda n: f"{n}-mocks-flagged")
def test_above_the_threshold_fires(count: int):
    assert len(_check(_patches(count))) == 1


def test_message_names_the_test_and_the_count():
    [diag] = _check(_patches(6))
    assert "`test_thing`" in diag.message
    assert "6 collaborators" in diag.message
    assert "respx" in diag.message


def test_reports_line_and_column_of_the_function():
    [diag] = _check(_patches(6))
    assert diag.col == 1
    assert diag.code == "SARJ059"


def test_diagnostics_are_sorted_by_position():
    src = _patches(6).replace("test_thing", "test_a") + "\n\n" + _patches(6).replace("test_thing", "test_b")
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == sorted(d.line for d in diags)


# --------------------------------------------------------------------------- #
# Path gating and collection.                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/things.py", "conftest.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_patches(6), path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_patches(6), path) == []


def test_class_method_is_collected():
    src = """
        class TestTransfer:
            @patch("a.one")
            @patch("b.two")
            @patch("c.three")
            @patch("d.four")
            @patch("e.five")
            @patch("f.six")
            def test_it(self, a, b, c, d, e, f):
                assert run() == 1
    """
    assert len(_check(src)) == 1


def test_nested_function_named_test_is_not_collected():
    # pytest collects module-level functions and class methods only, so
    # `test_inner`'s six mock fixtures are nobody's substitutions.
    src = """
        def test_outer(mock_a, mock_b, mock_c):
            def test_inner(mock_d, mock_e, mock_f, mock_g, mock_h, mock_i):
                pass
            assert run() == 1
    """
    assert _check(src) == []


def test_non_test_function_is_ignored():
    assert _check(_patches(8).replace("def test_thing", "def build_thing")) == []


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    thing()\n") == []


# --------------------------------------------------------------------------- #
# What counts: every substitution form contributes.                            #
# --------------------------------------------------------------------------- #


def test_body_patches_count():
    src = """
        def test_thing():
            with patch("a.one"), patch("b.two"), patch("c.three"):
                with patch("d.four"), patch("e.five"), patch("f.six"):
                    assert run() == 1
    """
    assert len(_check(src)) == 1


def test_mock_constructions_bound_to_names_count():
    src = """
        def test_thing():
            a = Mock()
            b = MagicMock()
            c = mock.AsyncMock()
            d = mock.create_autospec(Thing)
            e = Mock()
            f = Mock()
            assert run(a, b, c, d, e, f) == 1
    """
    assert len(_check(src)) == 1


def test_a_mock_not_bound_to_a_name_does_not_count():
    # `patch(..., new=MagicMock())` replaces one thing, not two.
    src = """
        def test_thing():
            with patch("a.one", new=MagicMock()), patch("b.two", new=MagicMock()):
                run(Mock(), Mock(), Mock(), Mock())
                assert True
    """
    assert _check(src) == []


def test_mock_fixture_parameters_count():
    src = """
        def test_thing(mocker, mock_store, api_mock, mock_bus, other_mock, mock_gateway):
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_a_mock_fixture_named_for_a_knob_does_not_count():
    src = """
        def test_thing(mocker, mock_store, api_mock, mock_bus, other_mock, mock_clock_source):
            assert run() == 1
    """
    assert _check(src) == []


def test_ordinary_fixture_parameters_do_not_count():
    src = """
        def test_thing(call_store, task_store, voice_store, agent_profile_store, client, db):
            assert run() == 1
    """
    assert _check(src) == []


def test_monkeypatch_setattr_counts():
    src = """
        def test_thing(monkeypatch):
            monkeypatch.setattr(mod_a, "collaborator", Fake())
            monkeypatch.setattr(mod_b, "collaborator", Fake())
            monkeypatch.setattr(mod_c, "collaborator", Fake())
            monkeypatch.setattr("pkg.mod_d.collaborator", Fake())
            monkeypatch.setattr("pkg.mod_e.collaborator", Fake())
            monkeypatch.setattr("pkg.mod_f.collaborator", Fake())
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_mocker_patch_counts():
    src = """
        def test_thing():
            mocker.patch("a.one")
            mocker.patch("b.two")
            mocker.patch.object(thing_c, "three")
            mocker.patch("d.four")
            mocker.patch("e.five")
            mocker.patch("f.six")
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_patch_multiple_of_one_target_is_one_collaborator():
    # Six attributes of ONE target: the same reduction as six `@patch`es of
    # `app.gateway.*`, which is one substituted collaborator.
    src = """
        @patch.multiple(
            "app.gateway",
            alpha=MagicMock(),
            bravo=MagicMock(),
            charlie=MagicMock(),
            delta=MagicMock(),
            echo=MagicMock(),
            foxtrot=MagicMock(),
        )
        def test_thing(alpha, bravo, charlie, delta, echo, foxtrot):
            assert run() == 1
    """
    assert _check(src) == []


def test_patch_multiple_expands_to_its_attributes_for_the_knob_filter():
    # `alpha` keeps `app.gateway` in the count; five other collaborators take
    # it to six.
    src = """
        @patch.multiple("app.gateway", alpha=MagicMock(), REQUEST_TIMEOUT=1)
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        @patch("f.six")
        def test_thing(alpha, timeout, b, c, d, e, f):
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_patch_multiple_of_only_knobs_drops_out_entirely():
    src = """
        @patch.multiple("app.gateway", REQUEST_TIMEOUT=1, MAX_RETRIES=0)
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        @patch("f.six")
        def test_thing(timeout, retries, b, c, d, e, f):
            assert run() == 1
    """
    assert _check(src) == []


def test_patch_multiple_config_keywords_are_not_replaced_attributes():
    # `autospec` is configuration, so `patch.multiple` injects two parameters
    # here, not three; `mock_c` onward are genuine fixtures and take the count
    # to six. Reading `autospec` as an attribute would skip one more parameter
    # and silently drop the finding.
    src = """
        @patch.multiple("app.gateway", alpha=DEFAULT, bravo=DEFAULT, autospec=True)
        def test_thing(alpha, bravo, mock_c, mock_d, mock_e, mock_f, mock_g):
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_async_test_is_checked():
    src = """
        async def test_thing(mocker, mock_a, mock_b, mock_c, mock_d, mock_e):
            assert await run() == 1
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# A collaborator is an object, not one of its methods. Both reductions were     #
# forced by real false positives; see the module docstring.                     #
# --------------------------------------------------------------------------- #


def test_many_attributes_of_one_module_are_one_collaborator():
    # celery/t/unit/utils/test_platforms.py:467 — eleven `os.*` syscalls are
    # the true external boundary, which is what the rule tells you to mock.
    src = """
        @patch("os.fork")
        @patch("os.setsid")
        @patch("os._exit")
        @patch("os.close")
        @patch("os.closerange")
        @patch("os.open")
        @patch("os.dup2")
        def test_open(dup2, open_, closer, close, exit_, setsid, fork):
            assert run() == 1
    """
    assert _check(src) == []


def test_distinct_modules_are_distinct_collaborators():
    assert len(_check(_patches(6))) == 1


def test_building_out_one_mocks_object_graph_is_one_collaborator():
    # bulbul/agent/tests/test_main_helpers.py:138 — a real `PsqlCallStore`
    # against a real database, with one `mock.Mock(spec=JobContext)`.
    src = """
        async def test_timeout_marks_call_failed(call_store, test_organization, test_user):
            ctx = mock.Mock(spec=JobContext)
            ctx.wait_for_participant = mock.AsyncMock(side_effect=TimeoutError)
            ctx.room = mock.Mock()
            ctx.api = mock.Mock()
            ctx.api.room = mock.Mock()
            ctx.api.room.delete_room = mock.AsyncMock()
            assert await run(ctx) is None
    """
    assert _check(src) == []


def test_six_separate_objects_still_fire():
    src = """
        async def test_thing():
            a = mock.Mock()
            b = mock.Mock()
            c = mock.Mock()
            d = mock.Mock()
            e = mock.Mock()
            f = mock.Mock()
            assert await run(a, b, c, d, e, f) is None
    """
    assert len(_check(src)) == 1


def test_doubles_hung_off_self_are_distinct_collaborators():
    # `self` is the test case, not a double, so these are six collaborators.
    src = """
        class TestThing:
            def test_it(self):
                self.a = Mock()
                self.b = Mock()
                self.c = Mock()
                self.d = Mock()
                self.e = Mock()
                self.f = Mock()
                assert run() == 1
    """
    assert len(_check(src)) == 1


def test_patch_object_of_one_receiver_is_one_collaborator():
    src = """
        def test_thing():
            with (
                patch.object(client, "get"),
                patch.object(client, "post"),
                patch.object(client, "put"),
                patch.object(client.session, "close"),
                patch.object(client.session.transport, "send"),
                patch.object(client, "delete"),
            ):
                assert run() == 1
    """
    assert _check(src) == []


def test_patch_object_of_six_receivers_fires():
    src = """
        def test_thing():
            with (
                patch.object(alpha, "go"),
                patch.object(bravo, "go"),
                patch.object(charlie, "go"),
                patch.object(delta, "go"),
                patch.object(echo, "go"),
                patch.object(foxtrot, "go"),
            ):
                assert run() == 1
    """
    assert len(_check(src)) == 1


def test_the_same_target_patched_twice_counts_once():
    src = """
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        def test_thing(a, b, c, d, e):
            with patch("a.one"):
                assert run() == 1
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Import spellings. The name table is what keeps HTTP `.patch` out, so every    #
# way of reaching `unittest.mock` has to resolve.                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("header", "call"),
    [
        ("import unittest.mock\n", "unittest.mock.patch"),
        ("from unittest import mock as m\n", "m.patch"),
        ("from unittest.mock import patch as p\n", "p"),
        ("import mock\n", "mock.patch"),
        ("from mock import patch\n", "patch"),
    ],
    ids=["submodule", "aliased-module", "aliased-symbol", "backport-module", "backport-symbol"],
)
def test_every_import_spelling_resolves(header: str, call: str):
    body = "\n".join(f'    {call}("mod{i}.collaborator")' for i in range(6))
    src = f"{header}\ndef test_thing():\n{body}\n    assert run() == 1\n"
    assert len(OverMockedTest().check(Path(TEST_PATH), src)) == 1


def test_mocker_needs_no_import():
    body = "\n".join(f'    mocker.patch("mod{i}.collaborator")' for i in range(6))
    src = f"def test_thing(mocker):\n{body}\n    assert run() == 1\n"
    assert len(OverMockedTest().check(Path(TEST_PATH), src)) == 1


def test_fully_qualified_mock_constructions_resolve():
    src = textwrap.dedent("""
        import unittest.mock

        def test_thing():
            a = unittest.mock.Mock()
            b = unittest.mock.MagicMock()
            c = unittest.mock.AsyncMock()
            d = unittest.mock.NonCallableMock()
            e = unittest.mock.Mock()
            f = unittest.mock.Mock()
            assert run(a, b, c, d, e, f) == 1
    """)
    assert len(OverMockedTest().check(Path(TEST_PATH), src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: `client.patch("/items/1")` is an HTTP request, not a mock.          #
# --------------------------------------------------------------------------- #


def test_http_patch_requests_are_not_substitutions():
    src = """
        def test_thing(client):
            client.patch("/items/1", json={})
            client.patch("/items/2", json={})
            client.patch("/items/3", json={})
            client.patch("/items/4", json={})
            client.patch("/items/5", json={})
            client.patch("/items/6", json={})
            assert client.patch("/items/7").status_code == 200
    """
    assert _check(src) == []


def test_mock_module_qualified_patches_are_substitutions():
    src = """
        def test_thing():
            with (
                mock.patch("a.one"),
                mock.patch("b.two"),
                mock.patch("c.three"),
                mock.patch("d.four"),
                mock.patch("e.five"),
                mock.patch("f.six"),
            ):
                assert run() == 1
    """
    assert len(_check(src)) == 1


def test_a_local_patch_helper_is_not_unittest_mock():
    src = textwrap.dedent("""
        def patch(target):
            return target

        def test_thing():
            patch("a.one")
            patch("b.two")
            patch("c.three")
            patch("d.four")
            patch("e.five")
            patch("f.six")
            assert run() == 1
    """)
    # No `unittest.mock` import backs the name, so nothing resolves.
    assert OverMockedTest().check(Path(TEST_PATH), src) == []


def test_a_locally_named_mock_class_is_not_a_double():
    src = textwrap.dedent("""
        class MockClient:
            pass

        def test_thing():
            a = MockClient()
            b = MockClient()
            c = MockClient()
            d = MockClient()
            e = MockClient()
            f = MockClient()
            assert run(a, b, c, d, e, f) == 1
    """)
    assert OverMockedTest().check(Path(TEST_PATH), src) == []


# --------------------------------------------------------------------------- #
# FP guard: environment and test-infrastructure knobs are not collaborators.    #
# --------------------------------------------------------------------------- #


def test_monkeypatch_setenv_is_not_a_substitution():
    src = """
        def test_thing(monkeypatch):
            monkeypatch.setenv("A", "1")
            monkeypatch.setenv("B", "2")
            monkeypatch.setenv("C", "3")
            monkeypatch.setenv("D", "4")
            monkeypatch.setenv("E", "5")
            monkeypatch.setenv("F", "6")
            monkeypatch.delenv("G", raising=False)
            assert run() == 1
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "method",
    ["setitem(cfg, 'a', 1)", "delitem(cfg, 'a')", "chdir(tmp_path)", "syspath_prepend('x')"],
)
def test_other_monkeypatch_methods_are_not_substitutions(method: str):
    src = f"""
        def test_thing(monkeypatch):
            monkeypatch.{method}
            monkeypatch.setattr(a, "one", 1)
            monkeypatch.setattr(b, "one", 1)
            monkeypatch.setattr(c, "one", 1)
            monkeypatch.setattr(d, "one", 1)
            monkeypatch.setattr(e, "one", 1)
            assert run() == 1
    """
    assert _check(src) == []


def test_patch_dict_is_not_a_substitution():
    src = """
        @patch.dict("os.environ", {"A": "1"})
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        def test_thing(a, b, c, d, e):
            assert run() == 1
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "target",
    [
        "app.worker.REQUEST_TIMEOUT",
        "app.worker.MAX_RETRIES",
        "app.worker.RETRY_DELAY",
        "app.worker.POLL_INTERVAL",
        "time.sleep",
        "asyncio.sleep",
        "app.core.settings",
        "app.core.config",
        "app.services.logger",
        "app.clock.now",
        "app.ids.uuid7",
    ],
    ids=lambda t: t.replace(".", "-"),
)
def test_infrastructure_knobs_do_not_count(target: str):
    src = f"""
        @patch("{target}")
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        def test_thing(a, b, c, d, e, knob):
            assert run() == 1
    """
    assert _check(src) == []


def test_a_sixth_real_collaborator_alongside_knobs_still_fires():
    src = """
        @patch("app.worker.REQUEST_TIMEOUT")
        @patch("time.sleep")
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        @patch("f.six")
        def test_thing(a, b, c, d, e, f, sleep, timeout):
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_a_monkeypatched_timeout_does_not_count():
    src = """
        def test_thing(monkeypatch):
            monkeypatch.setattr(worker, "TIMEOUT_SECONDS", 0)
            monkeypatch.setattr(a, "one", 1)
            monkeypatch.setattr(b, "one", 1)
            monkeypatch.setattr(c, "one", 1)
            monkeypatch.setattr(d, "one", 1)
            monkeypatch.setattr(e, "one", 1)
            assert run() == 1
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: class-level `@patch` is the TestCase's shared fixture.              #
# django/tests/backends/base/test_creation.py — five findings from one stack.   #
# --------------------------------------------------------------------------- #


def test_class_level_patches_are_not_attributed_to_each_method():
    src = """
        @patch.object(connection, "ensure_connection")
        @patch.object(connection, "prepare_database")
        @patch("django.db.migrations.recorder.MigrationRecorder.has_table")
        @patch("django.core.management.commands.migrate.Command.sync_apps")
        class TestDbCreationTests:
            @patch("django.db.migrations.executor.MigrationExecutor.migrate")
            def test_migrate_test_setting_true(self, mocked_migrate, *mocked_objects):
                with patch.object(creation, "_create_test_db"):
                    assert run() == 1
    """
    assert _check(src) == []


def test_a_method_that_declares_six_of_its_own_still_fires_inside_such_a_class():
    src = """
        @patch.object(connection, "ensure_connection")
        @patch.object(connection, "prepare_database")
        class TestDbCreationTests:
            @patch("a.one")
            @patch("b.two")
            @patch("c.three")
            @patch("d.four")
            @patch("e.five")
            @patch("f.six")
            def test_it(self, a, b, c, d, e, f, *mocked_objects):
                assert run() == 1
    """
    assert len(_check(src)) == 1


def test_parameters_injected_by_class_level_patches_are_not_recounted():
    src = """
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        class TestThing:
            def test_it(self, mock_a, mock_b, mock_c, mock_d, mock_e, mock_f):
                assert run() == 1
    """
    # Three of the six `mock_*` parameters come from the class decorators.
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a `@patch` injects a `mock_*` parameter — counting both double-     #
# counts every decorated test.                                                  #
# --------------------------------------------------------------------------- #


def test_patch_injected_parameters_are_not_counted_twice():
    src = """
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        @patch("d.four")
        @patch("e.five")
        def test_thing(mock_a, mock_b, mock_c, mock_d, mock_e):
            assert run() == 1
    """
    assert _check(src) == []


def test_mock_fixtures_beyond_the_injected_ones_still_count():
    src = """
        @patch("a.one")
        @patch("b.two")
        @patch("c.three")
        def test_thing(mock_a, mock_b, mock_c, mock_store, mock_bus, mock_clockwork):
            assert run() == 1
    """
    assert len(_check(src)) == 1


def test_patch_with_a_positional_replacement_injects_nothing():
    # `patch(target, new)` supplies the replacement itself, so no parameter is
    # prepended and a `mock_*` fixture in the signature is genuinely a fixture.
    src = """
        @patch("a.one", stub_one)
        @patch("b.two", stub_two)
        def test_thing(mock_c, mock_d, mock_e, mock_f, mock_g, mock_h):
            assert run() == 1
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: composition-root tests must stub every adapter.                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["test_wiring_builds_app", "test_startup_smoke", "test_di_container_resolves"])
def test_seam_test_names_are_exempt(name: str):
    assert _check(_patches(8).replace("def test_thing", f"def {name}")) == []


@pytest.mark.parametrize(
    "path",
    [
        "agent/tests/test_main_wiring.py",
        "webserver/tests/test_logto_smoke.py",
        "t/smoke/tests/test_worker.py",
        "tests/test_lifespan.py",
    ],
)
def test_seam_paths_are_exempt(path: str):
    assert _check(_patches(8), path) == []


def test_seam_class_names_are_exempt():
    src = """
        class TestAppStartup:
            @patch("a.one")
            @patch("b.two")
            @patch("c.three")
            @patch("d.four")
            @patch("e.five")
            @patch("f.six")
            def test_it(self, a, b, c, d, e, f):
                assert run() == 1
    """
    assert _check(src) == []


def test_an_ordinary_name_in_an_ordinary_file_is_not_exempt():
    assert len(_check(_patches(8), "agent/tests/test_main_helpers.py")) == 1


# --------------------------------------------------------------------------- #
# Real shapes from the corpus.                                                  #
# --------------------------------------------------------------------------- #


def test_bulbul_collect_digits_on_exit_fires():
    # bulbul/agent/tests/test_collect_digits_tool.py:598
    src = """
        async def test_on_exit_unregisters_local_user_state_listener(self) -> None:
            task = self._task()
            mock_session = mock.MagicMock()
            mock_session.off = mock.MagicMock()
            mock_room = mock.MagicMock()
            mock_job_ctx = mock.MagicMock()
            mock_job_ctx.room = mock_room
            with (
                mock.patch.object(Agent, "session", new_callable=mock.PropertyMock, return_value=mock_session),
                mock.patch("agent.lk.tools.collect_via_dtmf_tool.get_job_context", return_value=mock_job_ctx),
                mock.patch("livekit.agents.beta.workflows.dtmf_inputs.GetDtmfTask.on_exit"),
            ):
                await task.on_exit()
            assert mock_session.off.called
    """
    [diag] = _check(src)
    assert "6 collaborators" in diag.message


def test_celery_synloop_fires():
    # celery/t/unit/test_loops.py:9 — eight bare doubles, then assert they were
    # called. `clock` is dropped as a time knob, leaving eight of the nine.
    src = """
        def test_synloop_perform_pending_operations_on_system_exit():
            obj = Mock()
            connection = Mock()
            consumer = Mock()
            blueprint = Mock()
            hub = Mock()
            qos = Mock()
            heartbeat = Mock()
            clock = Mock()
            with patch("celery.worker.loops.state") as mock_state:
                mock_state.maybe_shutdown.side_effect = SystemExit
                with pytest.raises(SystemExit):
                    synloop(obj, connection, consumer, blueprint, hub, qos, heartbeat, clock)
    """
    [diag] = _check(src)
    assert "8 collaborators" in diag.message


def test_a_real_dependency_test_with_one_boundary_double_is_clean():
    # The shape the rule steers toward: real stores, one external boundary.
    src = """
        async def test_outbound_call_persists(call_store, task_store, voice_store, agent_profile_store):
            telephony = mock.AsyncMock()
            telephony.dial = mock.AsyncMock(return_value="sid-1")
            service = _make_service(call_store, task_store, voice_store, agent_profile_store, telephony)
            result = await service.start_outbound(config)
            assert result.status == CallStatus.IN_PROGRESS
    """
    assert _check(src) == []
