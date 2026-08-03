from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.mock_without_spec import MockWithoutSpec


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return MockWithoutSpec().check(Path(path), source)


_BARE_MOCK = """
from unittest import mock

def test_thing():
    client = mock.Mock()
    assert client is not None
"""


# Test-path gating: the rule ONLY fires inside test files.                     #


@pytest.mark.parametrize(
    "path",
    [
        "test_call_store.py",
        "call_store_test.py",
        "tests/conftest.py",
        "conftest.py",
        "python/app/tests/stores/seed.py",
        "deeply/nested/tests/data/factory.py",
    ],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_BARE_MOCK, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "python/app/app/calls/call_store.py",
        "src/service.py",
        "a/testing/thing.py",
        "attestation.py",
    ],
)
def test_skips_non_test_paths(path: str):
    assert _check(_BARE_MOCK, path) == []


# Positive: every unspecced construction spelling fires.                       #


@pytest.mark.parametrize(
    "call",
    [
        "mock.Mock()",
        "mock.MagicMock()",
        "mock.AsyncMock()",
        "mock.Mock(return_value=3)",
        "mock.AsyncMock(side_effect=ValueError)",
        "mock.patch('agent.main.thing')",
        "mock.patch.object(Service, 'run')",
    ],
)
def test_flags_unspecced_module_qualified_calls(call: str):
    src = f"""
from unittest import mock

def test_thing():
    double = {call}
    assert double
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "imported",
    ["Mock", "MagicMock", "AsyncMock", "patch"],
)
def test_flags_direct_symbol_imports(imported: str):
    src = f"""
from unittest.mock import {imported}

def test_thing():
    double = {imported}()
    assert double
"""
    assert len(_check(src)) == 1


def test_flags_aliased_module_import():
    src = """
import unittest.mock as m

def test_thing():
    assert m.Mock()
"""
    assert len(_check(src)) == 1


def test_flags_fully_qualified_call():
    src = """
import unittest.mock

def test_thing():
    assert unittest.mock.Mock()
"""
    assert len(_check(src)) == 1


def test_flags_aliased_symbol_import():
    src = """
from unittest.mock import AsyncMock as Fake

def test_thing():
    assert Fake()
"""
    assert len(_check(src)) == 1


# FP guard: a spec-bearing argument gives the double a real contract.          #


@pytest.mark.parametrize(
    "kwarg",
    [
        "spec=Room",
        "spec_set=Room",
        "autospec=True",
        "wraps=real_object",
        "new=replacement",
        "new_callable=Factory",
    ],
)
def test_spec_bearing_kwargs_are_exempt(kwarg: str):
    src = f"""
from unittest import mock

def test_thing():
    assert mock.Mock({kwarg})
"""
    assert _check(src) == []


def test_kwargs_forwarding_is_exempt():
    # `**overrides` may carry a spec; the call site no longer states its own
    # contract, so we decline to guess rather than emit a probable FP.
    src = """
from unittest import mock

def test_thing(overrides):
    assert mock.Mock(**overrides)
"""
    assert _check(src) == []


def test_spec_among_other_kwargs_is_exempt():
    src = """
from unittest import mock

def test_thing():
    assert mock.AsyncMock(spec=Store, return_value=7, name="s")
"""
    assert _check(src) == []


# FP guard: `spec` / `new` are POSITIONAL parameters of these signatures, and  # that is how they are nearly always spelled.


@pytest.mark.parametrize(
    ("exempt", "flagged"),
    [
        # `Mock(spec=None, wraps=None, ...)` — arg 1 is `spec`.
        ("mock.Mock(Room)", "mock.Mock()"),
        ("mock.MagicMock(Room)", "mock.MagicMock()"),
        ("mock.AsyncMock(Room)", "mock.AsyncMock()"),
        # `patch(target, new=DEFAULT, ...)` — arg 2 is `new`.
        ("mock.patch('agent.main.run', fake_run)", "mock.patch('agent.main.run')"),
        # `patch.object(target, attribute, new=DEFAULT, ...)` — arg 3 is `new`.
        (
            "mock.patch.object(Service, 'run', fake_run)",
            "mock.patch.object(Service, 'run')",
        ),
    ],
)
def test_positional_replacement_is_exempt_but_its_absence_is_flagged(exempt: str, flagged: str):
    template = """
from unittest import mock

def test_thing():
    assert {call}
"""
    assert _check(template.format(call=exempt)) == []
    assert len(_check(template.format(call=flagged))) == 1


def test_star_args_forwarding_is_exempt():
    # `*args` may carry the positional `new`; the arity is unknown, so decline
    # to guess rather than emit a probable FP — the `**kwargs` policy, mirrored.
    src = """
from unittest import mock

def test_thing(args):
    assert mock.patch(*args)
"""
    assert _check(src) == []


def test_decorator_form_with_a_positional_replacement_is_exempt():
    src = """
from unittest.mock import patch

@patch("black.dump_to_file", dump_to_stderr)
def test_thing(self):
    assert True
"""
    assert _check(src) == []


# FP guard: a double that is only called and introspected is a stub function / #
# call recorder — there is no collaborator type for `spec=` to name.           #


def test_call_recorder_is_exempt():
    src = """
from unittest import mock

def test_thing():
    validate_stub = mock.MagicMock()
    validate_stub('A', 'pre')
    validate_stub.assert_called_once_with('A', 'pre')
    validate_stub.reset_mock()
    assert validate_stub.call_args_list
"""
    assert _check(src) == []


def test_recorder_that_is_never_called_is_still_flagged():
    # The opposite case: a double merely bound and handed around is a stand-in
    # for an object, and production code can attribute-access it unseen.
    src = """
from unittest import mock

def test_thing():
    dbsession = mock.MagicMock()
    assert dbsession is not None
"""
    assert len(_check(src)) == 1


def test_recorder_read_back_through_a_domain_attribute_is_still_flagged():
    src = """
from unittest import mock

def test_thing():
    session = mock.MagicMock()
    session('ping')
    session.close()
"""
    assert len(_check(src)) == 1


def test_called_recorder_handed_to_production_is_still_flagged():
    src = """
from unittest import mock

def test_thing():
    callback = mock.MagicMock()
    callback('probe')
    run(callback)
    callback.assert_called_once_with('probe')
"""
    assert len(_check(src)) == 1


def test_call_recorder_introspection_passed_to_assertion_helper_is_exempt():
    src = """
from unittest import mock

def test_thing():
    callback = mock.MagicMock()
    callback('probe')
    assert_equal(callback.call_count, 1)
"""
    assert _check(src) == []


# FP guard: an `except ImportError` stand-in has nothing importable to spec.   #


@pytest.mark.parametrize("caught", ["ImportError", "ModuleNotFoundError", "(ImportError, OSError)"])
def test_import_failure_stand_in_is_exempt(caught: str):
    src = f"""
from unittest import mock

try:
    import uvloop
except {caught}:
    uvloop = mock.Mock()
"""
    assert _check(src) == []


def test_stand_in_for_a_non_import_failure_is_still_flagged():
    src = """
from unittest import mock

try:
    backend = load_backend()
except ValueError:
    backend = mock.Mock()
"""
    assert len(_check(src)) == 1


def test_mock_outside_the_import_handler_is_still_flagged():
    src = """
from unittest import mock

try:
    import uvloop
except ImportError:
    uvloop = mock.Mock()

def test_thing():
    assert mock.Mock()
"""
    assert len(_check(src)) == 1


# FP guard: the name is only trusted when a unittest.mock import backs it.     #
# This is what keeps hand-rolled MockFoo/Mock doubles out of the results.      #


def test_locally_defined_mock_class_is_not_flagged():
    src = """
class Mock:
    def __init__(self) -> None:
        self.calls = []

def test_thing():
    assert Mock()
"""
    assert _check(src) == []


def test_hand_rolled_fake_implementing_an_abc_is_not_flagged():
    src = """
from agent.ports import PaymentGatewayClient

class MockPaymentGatewayClient(PaymentGatewayClient):
    async def fetch(self, key: str) -> str:
        return "canned"

def test_thing():
    assert MockPaymentGatewayClient()
"""
    assert _check(src) == []


def test_unrelated_module_named_mock_is_not_flagged():
    src = """
from myapp import mock

def test_thing():
    assert mock.Mock()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "expr",
    [
        "mock.ANY",
        "mock.sentinel.thing",
        "mock.call(1, 2)",
        "mock.create_autospec(Service)",
    ],
)
def test_non_construction_mock_helpers_are_not_flagged(expr: str):
    src = f"""
from unittest import mock

def test_thing():
    assert {expr}
"""
    assert _check(src) == []


def test_bare_reference_without_call_is_not_flagged():
    src = """
from unittest import mock

def test_thing(double: mock.Mock):
    assert isinstance(double, mock.Mock)
"""
    assert _check(src) == []


def test_patch_object_on_a_non_patcher_receiver_is_not_flagged():
    src = """
from unittest import mock

def test_thing():
    assert registry.object("name")
"""
    assert _check(src) == []


# FP guard: `receiver.method = Mock(...)` is a canned stub for one callable,   #
# not an unspecced collaborator — the contract belongs to the receiver.        #


@pytest.mark.parametrize(
    "stub",
    [
        "mock.Mock(return_value=1)",
        "mock.AsyncMock(return_value=1)",
        "mock.MagicMock(side_effect=ValueError)",
    ],
)
def test_canned_method_stub_on_an_attribute_is_exempt(stub: str):
    # `Mock(spec=X)` children are not awaitable, so a *correctly* specced double
    # must stub its async methods this way to be usable at all.
    src = f"""
from unittest import mock

def test_thing():
    store = mock.Mock(spec=Store)
    store.get = {stub}
    run(store)
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "evidence",
    [
        "    store.get.assert_awaited_once_with('id')",
        "    assert store.get.call_count == 1",
        "    store.get('id')",
    ],
)
def test_attribute_stub_proved_callable_by_use_is_exempt(evidence: str):
    src = f"""
from unittest import mock

def test_thing():
    store = mock.Mock(spec=Store)
    store.get = mock.AsyncMock()
    run(store)
{evidence}
"""
    assert _check(src) == []


def test_attribute_double_with_no_callable_evidence_is_still_flagged():
    # Absence of attribute reads is not evidence of callability.
    src = """
from unittest import mock

def test_thing():
    room = mock.Mock(spec=Room)
    room.local_participant = mock.Mock()
    run(room)
"""
    assert len(_check(src)) == 1


def test_attribute_double_read_back_through_a_domain_attribute_is_still_flagged():
    # A namespace double: the file walks it, so `spec=` has a real referent.
    src = """
from unittest import mock

def test_thing():
    api = mock.Mock(spec=LiveKitAPI)
    api.room = mock.Mock(return_value=1)
    api.room.delete_room("r")
"""
    assert len(_check(src)) == 1


def test_every_namespace_level_of_a_walked_chain_is_still_flagged():
    # `ctx.api` and `ctx.api.sip` are namespace doubles; only the leaf stub goes.
    src = """
from unittest import mock

def test_thing():
    ctx = mock.Mock(spec=JobContext)
    ctx.api = mock.Mock()
    ctx.api.sip = mock.Mock()
    ctx.api.sip.create_sip_participant = mock.AsyncMock(return_value=1)
    run(ctx)
"""
    assert len(_check(src)) == 2


@pytest.mark.parametrize(
    "target",
    ["rooms[0].get", "make_room().get", "room.get = other.get"],
)
def test_stub_on_a_non_dotted_target_is_still_flagged(target: str):
    # Two occurrences of `rooms[0]` need not denote the same object, and a
    # chained assignment binds the one double to several places at once, so
    # neither can be reasoned about by path.
    src = f"""
from unittest import mock

def test_thing(rooms, other):
    {target} = mock.AsyncMock(return_value=1)
"""
    assert len(_check(src)) == 1


def test_collaborator_shapes_still_fire_alongside_the_stub_guard():
    # The shapes the rule exists for, in one file, so a future widening of the
    # attribute guard breaks here: a bare bound double, a constructor kwarg, a
    # `patch` context manager, and a `monkeypatch.setattr` replacement.
    src = """
from unittest import mock

def test_thing(monkeypatch):
    session = mock.AsyncMock()
    service = Service(store=mock.Mock())
    monkeypatch.setattr(module, "fetch", mock.AsyncMock(return_value=1))
    with mock.patch("module.send"):
        run(session, service)
"""
    assert len(_check(src)) == 4


# Edge cases: empty / syntax error / multiple hits / position / sort order.    #


@pytest.mark.parametrize("source", ["", "   \n\n  ", "# just a comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    mock.Mock()\n") == []


def test_multiple_hits_in_one_file():
    src = """
from unittest import mock

def test_one():
    assert mock.Mock()

def test_two():
    assert mock.AsyncMock()
    assert mock.MagicMock(spec=Thing)
    assert mock.patch("x.y")
"""
    assert len(_check(src)) == 3


def test_reports_line_and_column_of_the_call():
    src = """
from unittest import mock

def test_thing():
    double = mock.Mock()
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (5, 14)
    assert diag.code == "SARJ040"


def test_diagnostics_are_sorted_by_position():
    src = """
from unittest import mock

def test_thing():
    a = mock.Mock()
    b = mock.AsyncMock()
    c = mock.MagicMock()
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_message_names_the_offending_symbol():
    src = """
from unittest import mock

def test_thing():
    assert mock.patch.object(Service, "run")
"""
    [diag] = _check(src)
    assert "`patch.object`" in diag.message


def test_file_without_any_mock_import_is_skipped_entirely():
    src = """
def test_thing():
    assert Mock()
    assert patch("a.b")
"""
    assert _check(src) == []
