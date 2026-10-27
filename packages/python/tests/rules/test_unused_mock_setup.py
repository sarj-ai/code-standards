from pathlib import Path
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.unused_mock_setup import UnusedMockSetup


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/app/tests/unit/test_billing.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return UnusedMockSetup().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = UnusedMockSetup.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(UnusedMockSetup().check(Path(focus.path), focus.source)) == example.expected_count


_OVERWRITTEN = """
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    other_mock = Mock()
    charge.return_value = 1
    charge.return_value = 2
    assert billing.charge(gateway) == 2
"""

_ASSERTED_NOT_CALLED = """
from unittest.mock import Mock

def test_no_bearer_skips_lookup():
    lookup = Mock()
    lookup.return_value = None
    client.get("/mcp/test")
    lookup.assert_not_called()
"""


# Path gating.                                                                 #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/y.py", "conftest.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_OVERWRITTEN, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py", "billing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_OVERWRITTEN, path) == []


# Shape A: the configuration is overwritten before anything can read it.       #


def test_flags_adjacent_overwrite():
    assert len(_check(_OVERWRITTEN)) == 1


def test_flags_overwritten_side_effect():
    src = """
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    charge.side_effect = ValueError
    charge.side_effect = TypeError
    billing.charge(gateway)
"""
    assert len(_check(src)) == 1


def test_flags_overwrite_of_a_deep_path():
    src = """
from unittest.mock import Mock

def test_set():
    get = Mock()
    self.backend = Mock(one_client=Mock(kv=Mock(get=get)))
    get.return_value = (1, {})
    get.return_value = (2, {})
    assert self.backend.get("k")
"""
    assert len(_check(src)) == 1


def test_flags_immediately_overwritten_pytest_mock_patch_keyword():
    src = """
def test_cli(mocker, session):
    prompt_session = mocker.patch("app.cli.PromptSession", return_value=None)
    prompt_session.return_value = 2
    run_cli()
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (3, 5)
    assert "`prompt_session.return_value`" in diag.message
    assert "retaining the mock constructor and binding" in diag.message


def test_flags_immediately_overwritten_imported_mock_constructor_keyword():
    src = """
from unittest.mock import Mock

def test_charge():
    gateway = Mock(return_value=1)
    gateway.return_value = 2
    assert charge(gateway) == 2
"""
    assert len(_check(src)) == 1


def test_tracks_independent_constructor_configurations_until_a_use():
    src = """
from unittest.mock import Mock

def test_charge():
    gateway = Mock(return_value=1)
    logger = Mock(return_value="message")
    gateway.return_value = 2
    assert charge(gateway, logger) == 2
"""
    assert len(_check(src)) == 1


_HASHING_KEY = (
    "events = []\nclass Key:\n    def __hash__(self):\n        events.append('hash')\n        return 1\nkey = Key()\n"
)
_SETTER_TARGET = "events = []\nclass Target:\n    @property\n    def side_effect(self):\n        return None\n    @side_effect.setter\n    def side_effect(self, value):\n        events.append(value)\n"
_ITERATING_VALUES = (
    "events = []\nclass Values:\n    def __iter__(self):\n        events.append('iterate')\n        return iter((1,))\n"
)


@pytest.mark.parametrize("terminal_assertion", [False, True])
@pytest.mark.parametrize(
    ("setup", "value", "attribute", "observation", "error", "removable"),
    [
        pytest.param("", "1", "return_value", "", None, True, id="inert-scalar"),
        pytest.param("value = 1\n", "value", "return_value", "", None, True, id="initialized-scalar"),
        pytest.param(
            "events = []\ndef seed():\n    events.append('seed')\n    return 1\n",
            "seed()",
            "return_value",
            "assert events == ['seed']\n",
            None,
            False,
            id="rhs-effect",
        ),
        pytest.param(
            "def seed():\n    raise ValueError('seed')\n",
            "seed()",
            "return_value",
            "",
            "ValueError: seed",
            False,
            id="rhs-error",
        ),
        pytest.param("", "missing", "return_value", "", "NameError", False, id="uninitialized-name"),
        pytest.param(_HASHING_KEY, "{key}", "return_value", "assert events == ['hash']\n", None, False, id="set-hash"),
        pytest.param(
            _HASHING_KEY, "{key: 1}", "return_value", "assert events == ['hash']\n", None, False, id="dict-hash"
        ),
        pytest.param(
            f"{_ITERATING_VALUES}values = Values()\n",
            "values",
            "side_effect",
            "assert events == ['iterate']\n",
            None,
            False,
            id="native-setter-iteration",
        ),
        pytest.param(
            f"import builtins\n{_ITERATING_VALUES}builtins.ValueError = Values()\n",
            "ValueError",
            "side_effect",
            "assert events == ['iterate']\n",
            None,
            False,
            id="mutated-builtin-exception",
        ),
        pytest.param(
            f"{_ITERATING_VALUES}__import__('builtins').ValueError = Values()\n",
            "ValueError",
            "side_effect",
            "assert events == ['iterate']\n",
            None,
            False,
            id="dynamic-builtin-namespace",
        ),
        pytest.param(
            "events = []\nnative = Mock.__setattr__\ndef configure(self, name, value):\n    if name == 'side_effect' and value == 1:\n        events.append('set')\n    native(self, name, value)\nMock.__setattr__ = configure\n",
            "1",
            "side_effect",
            "assert events == ['set']\n",
            None,
            False,
            id="mutated-native-constructor",
        ),
        pytest.param(
            _SETTER_TARGET,
            "1",
            "return_value.side_effect",
            "assert events == [1, 2]\n",
            None,
            False,
            id="configured-custom-receiver",
        ),
        pytest.param(
            _SETTER_TARGET,
            "1",
            "child.side_effect",
            "assert events == [1, 2]\n",
            None,
            False,
            id="assigned-custom-receiver",
        ),
    ],
)
def test_removable_operation_preserves_native_effects(
    tmp_path: Path,
    *,
    setup: str,
    value: str,
    attribute: str,
    observation: str,
    error: str | None,
    removable: bool,
    terminal_assertion: bool,
) -> None:
    assignment = f"    mock.{attribute} = {value}\n"
    factory = "Mock(return_value=Target())" if attribute == "return_value.side_effect" else "Mock()"
    receiver = "mock.child = Target()\n" if attribute == "child.side_effect" else ""
    finish = (
        "mock.assert_not_called()\n"
        if terminal_assertion
        else (
            ("mock.side_effect = None\n" if attribute == "side_effect" else "")
            + "mock.return_value = 2\nassert mock() == 2\n"
        )
    )
    if "." in attribute:
        finish = "mock.assert_not_called()\n" if terminal_assertion else f"mock.{attribute} = 2\n"
        observation = "assert events == [1]\n" if terminal_assertion else observation
    source = (
        "from unittest.mock import Mock\n\ndef test_configuration():\n"
        + textwrap.indent(f"{setup}mock = {factory}\n{receiver}", "    ")
        + assignment
        + textwrap.indent(finish + observation, "    ")
        + "\ntest_configuration()\n"
    )
    assert bool(_check(source)) is removable
    for index, program in enumerate((source, source.replace(assignment, ""))):
        path = tmp_path / f"configuration_{index}.py"
        path.write_text(
            "import builtins\nsaved = builtins.ValueError\ntry:\n"
            + textwrap.indent(program, "    ")
            + "finally:\n    builtins.ValueError = saved\n"
        )
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=10, check=False)
        expected_error = error if index == 0 else "AssertionError" if not removable and error is None else None
        if expected_error is None:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode == 1
            assert expected_error in result.stderr


def test_constructor_remediation_keeps_the_native_mock_binding(tmp_path: Path) -> None:
    source = "from unittest.mock import Mock\ndef test_charge():\n    gateway = Mock(return_value=1)\n    gateway.return_value = 2\n    assert gateway() == 2\ntest_charge()\n"
    [diagnostic] = _check(source)
    assert "Remove the overwritten constructor keyword" in diagnostic.message
    path = tmp_path / "configuration.py"
    path.write_text(source.replace("Mock(return_value=1)", "Mock()"))
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "def test_charge(value):\n    mock = Mock()\n    mock.side_effect = value\n    mock.side_effect = None\n",
        "def test_charge(ValueError):\n    mock = Mock()\n    mock.side_effect = ValueError\n    mock.side_effect = None\n",
        "def test_charge():\n    mock = Mock(return_value=missing)\n    mock.return_value = 2\n",
        "def test_charge():\n    mock = Mock()\n    mock.return_value = {[1]: 2}\n    mock.return_value = 2\n",
        "def test_charge():\n    mock.return_value = 1\n    mock = Mock()\n    mock.return_value = 2\n",
        "def test_charge(enabled):\n    if enabled:\n        mock = Mock()\n    mock.return_value = 1\n    mock.return_value = 2\n",
    ],
)
def test_unresolved_or_non_native_values_are_not_removable(source: str) -> None:
    assert _check(f"from unittest.mock import Mock\n{source}") == []


@pytest.mark.parametrize(
    "prefix", ["import builtins as native\n", "from builtins import ValueError\n", "namespace = __builtins__\n"]
)
def test_explicit_builtin_namespace_access_excludes_native_assumptions(prefix: str) -> None:
    assert _check(prefix + _OVERWRITTEN) == []


@pytest.mark.parametrize(
    "factory",
    [
        "mocker.patch('app.target', new=Target())",
        "mocker.patch('app.target', Target())",
        "mocker.patch('app.target', new_callable=Target)",
        "mocker.patch(*arguments)",
        "mocker.patch.object(Holder, 'target', new=Target())",
        "mocker.patch.object(Holder, 'target', Target())",
        "mocker.patch.object(Holder, 'target', **options)",
        "mocker.patch.object(Holder, *arguments)",
        "mocker.Mock(_mock_delegate=Target())",
    ],
)
def test_patch_replacement_options_do_not_prove_a_native_receiver(factory: str) -> None:
    source = (
        f"def test_configuration(mocker):\n    mock = {factory}\n    mock.side_effect = 1\n    mock.side_effect = 2\n"
    )
    assert _check(source) == []


def test_dotted_assignment_can_substitute_a_custom_receiver(tmp_path: Path) -> None:
    assignment = "    holder.child.side_effect = 1\n"
    source = (
        f"from unittest.mock import Mock\n{_SETTER_TARGET}"
        "class Holder:\n    def __setattr__(self, name, value):\n        object.__setattr__(self, name, Target())\n"
        "def test_configuration():\n    holder = Holder()\n    holder.child = Mock()\n"
        f"{assignment}    holder.child.side_effect = 2\n    assert events == [1, 2]\n"
        "test_configuration()\n"
    )
    assert _check(source) == []
    for index, program in enumerate((source, source.replace(assignment, ""))):
        path = tmp_path / f"receiver_{index}.py"
        path.write_text(program)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == index, result.stderr
        if index:
            assert "AssertionError" in result.stderr


@pytest.mark.parametrize(
    ("before", "after", "entry"),
    [
        ("observe(mock)\n", "", "test_configuration()"),
        ("alias = mock\nobserve(alias)\n", "", "test_configuration()"),
        ("", "return mock\n", "observe(test_configuration())"),
    ],
    ids=("passed", "aliased", "returned"),
)
def test_escaped_receiver_can_observe_configuration_without_calling(
    tmp_path: Path, before: str, after: str, entry: str
) -> None:
    assignment = "    mock.return_value = 1\n"
    body = textwrap.indent(f"{before}mock.assert_not_called()\n{after}", "    ")
    source = (
        "from unittest.mock import Mock\nevents = []\n"
        "def observe(value):\n    if value.return_value == 1:\n        events.append(1)\n"
        f"def test_configuration():\n    mock = Mock()\n{assignment}{body}{entry}\nassert events == [1]\n"
    )
    assert _check(source) == []
    for index, program in enumerate((source, source.replace(assignment, ""))):
        path = tmp_path / f"observer_{index}.py"
        path.write_text(program)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == index, result.stderr
        if index:
            assert "AssertionError" in result.stderr


def test_effectful_call_after_mock_construction_can_observe_initial_configuration():
    src = """
def test_cli(mocker, session):
    prompt_session = mocker.patch("app.cli.PromptSession", return_value=session)
    run_cli()
    prompt_session.return_value = replacement
"""
    assert _check(src) == []


def test_unproven_mock_like_constructor_is_not_assumed_to_be_a_mock():
    src = """
def test_charge():
    gateway = Mock(return_value=first)
    gateway.return_value = second
    assert charge(gateway) == second
"""
    assert _check(src) == []


def test_flags_three_writes_as_two_findings():
    src = """
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    charge.return_value = 1
    charge.return_value = 2
    charge.return_value = 3
    assert billing.charge(gateway) == 3
"""
    assert len(_check(src)) == 2


def test_message_names_the_overwriting_line():
    [diag] = _check(_OVERWRITTEN)
    assert "overwritten on line 9" in diag.message
    assert "`charge.return_value`" in diag.message


def test_reports_the_first_of_the_pair():
    [diag] = _check(_OVERWRITTEN)
    assert (diag.line, diag.col) == (8, 5)
    assert diag.code == "SARJ067"


@pytest.mark.parametrize(
    "filler",
    [
        pytest.param("expected = 7", id="literal-assign"),
        pytest.param("expected = [1, 2, {'a': 'b'}]", id="literal-collection"),
        pytest.param("pass", id="pass"),
        pytest.param("import json", id="import"),
        pytest.param('"a note about the mock"', id="string-expression"),
        pytest.param("other_mock.return_value = 1", id="other-mock-config"),
    ],
)
def test_inert_statements_between_the_writes_still_flag(filler: str):
    src = f"""
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    other_mock = Mock()
    charge.return_value = 1
    {filler}
    charge.return_value = 2
    assert billing.charge(gateway) == 2
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "filler",
    [
        pytest.param("billing.charge(gateway)", id="call"),
        pytest.param("result = billing.charge(gateway)", id="call-in-assignment"),
        pytest.param("value = config.timeout", id="attribute-load-may-be-a-property"),
        pytest.param("value = rows[0]", id="subscript-may-be-getitem"),
        pytest.param("config.timeout = 3", id="attribute-store-may-be-a-setter"),
        pytest.param("rows[0] = 3", id="subscript-store-may-be-setitem"),
        pytest.param("del charge", id="del"),
        pytest.param("return None", id="return"),
        pytest.param("assert charge() == 1", id="assert-that-calls"),
    ],
)
def test_effectful_statement_between_the_writes_is_exempt(filler: str):
    src = f"""
def test_charge():
    charge.return_value = 1
    {filler}
    charge.return_value = 2
    assert billing.charge(gateway) == 2
"""
    assert _check(src) == []


def test_await_between_the_writes_is_exempt():
    src = """
async def test_charge():
    charge.return_value = 1
    await billing.charge(gateway)
    charge.return_value = 2
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
        pytest.param("if flag:\n        charge.return_value = 2", id="if"),
        pytest.param("with patch('x'):\n        charge.return_value = 2", id="with"),
        pytest.param("for _ in range(2):\n        charge.return_value = 2", id="for"),
        pytest.param("try:\n        charge.return_value = 2\n    except OSError:\n        pass", id="try"),
    ],
)
def test_a_write_in_a_nested_block_does_not_pair_with_the_outer_one(nested: str):
    src = f"""
def test_charge():
    charge.return_value = 1
    {nested}
    assert billing.charge(gateway)
"""
    assert _check(src) == []


def test_two_writes_inside_the_same_nested_block_still_flag():
    src = """
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    if flag:
        charge.return_value = 1
        charge.return_value = 2
    assert billing.charge(gateway)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("charge.return_value = 1", "charge.side_effect = ValueError", id="return-then-side-effect"),
        pytest.param("charge.side_effect = None", "charge.return_value = 1", id="side-effect-cleared-then-return"),
        pytest.param("charge.return_value = 1", "gateway.refund.return_value = 2", id="different-attribute"),
        pytest.param("alpha.charge.return_value = 1", "beta.charge.return_value = 2", id="different-mock"),
        pytest.param(
            "charge.return_value = 1",
            "charge.return_value.ok = True",
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


# Shape B: the test asserts the configured path was never called.              #


def test_flags_configuration_contradicted_by_assert_not_called():
    assert len(_check(_ASSERTED_NOT_CALLED)) == 1


def test_flags_assert_not_awaited():
    src = """
from unittest.mock import AsyncMock

async def test_skips_lookup():
    lookup = AsyncMock()
    lookup.return_value = None
    await handle(request)
    lookup.assert_not_awaited()
"""
    assert len(_check(src)) == 1


def test_parent_negative_assertion_does_not_prove_child_configuration_dead():
    src = """
from unittest.mock import Mock

def test_skips_fetch():
    client = Mock()
    client.get.return_value.json.return_value = {"a": 1}
    service.run()
    client.get.assert_not_called()
"""
    assert _check(src) == []


def test_flags_side_effect_configuration_too():
    src = """
from unittest.mock import Mock

def test_skips_lookup():
    lookup = Mock()
    lookup.side_effect = ValueError
    handle(request)
    lookup.assert_not_called()
"""
    assert len(_check(src)) == 1


def test_flags_inside_a_test_method():
    src = """
from unittest.mock import Mock

class TestIndex:
    def test_conflict_leaves_update_alone(self):
        update = Mock()
        x = Mock()
        update.return_value = {"result": "updated"}
        x._set_with_state(task_id, result, state)
        update.assert_not_called()
"""
    assert len(_check(src)) == 1


def test_trailing_plain_assertions_do_not_rescue_the_setup():
    src = """
from unittest.mock import Mock

def test_skips_lookup():
    lookup = Mock()
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    assert sink.entries[0].auth_method == "none"
"""
    assert len(_check(src)) == 1


def test_trailing_assertion_call_on_another_mock_does_not_rescue_the_setup():
    src = """
from unittest.mock import Mock

def test_skips_lookup():
    lookup = Mock()
    audit = Mock()
    audit.record = Mock()
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    audit.record.assert_called_once_with("none")
"""
    assert len(_check(src)) == 1


def test_trailing_mock_assertion_with_an_effectful_argument_rescues_the_setup():
    src = """
def test_skips_lookup():
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    audit.record.assert_called_once_with(build_expected_record())
"""
    assert _check(src) == []


def test_message_names_the_asserted_path():
    [diag] = _check(_ASSERTED_NOT_CALLED)
    assert "`lookup`" in diag.message
    assert "never" in diag.message


def test_the_exact_assert_not_called_message():
    [diag] = _check(_ASSERTED_NOT_CALLED)
    assert diag.message == (
        "`lookup.return_value` is configured here, but the test ends by proving "
        "`lookup` was never called, so its behavior cannot affect the test. "
        "Delete this inert configuration; retain the mock constructor and binding"
    )


def test_the_act_on_the_assertions_own_line_still_precedes_it():
    # Boundary on `last_effect <= line`: the last thing that can drive the mock shares a line with the assertion, so it still ran *before* it and nothing follows.
    src = """
from unittest.mock import Mock

def test_skips_lookup():
    lookup = Mock()
    lookup.return_value = None
    handle(request); lookup.assert_not_called()
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "positive",
    [
        pytest.param("lookup.assert_called_once()", id="assert_called_once"),
        pytest.param("lookup.assert_called_with(1)", id="assert_called_with"),
        pytest.param("lookup.assert_awaited_once()", id="assert_awaited_once"),
        pytest.param("lookup.assert_has_calls([call(1)])", id="assert_has_calls"),
        pytest.param("lookup.assert_any_call(1)", id="assert_any_call"),
        pytest.param("assert lookup.call_count == 2", id="call_count"),
        pytest.param("assert lookup.called", id="called"),
        pytest.param("assert lookup.call_args.args == (1,)", id="call_args"),
        pytest.param("assert lookup.await_count == 1", id="await_count"),
        pytest.param("lookup.reset_mock()", id="reset_mock"),
        pytest.param("assert service.assert_called_once", id="positive-on-the-base-mock"),
        pytest.param("lookup.inner.assert_called_once()", id="positive-on-an-extension"),
    ],
)
def test_a_positive_call_assertion_anywhere_exempts_the_setup(positive: str):
    # `pool_close.assert_not_awaited()` then `await shutdown()` then
    # `pool_close.assert_awaited_once()` is a mid-test checkpoint; the setup
    # fires two lines later.
    src = f"""
def test_lookup_is_deferred():
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    {positive}
"""
    assert _check(src) == []


def test_a_positive_call_assertion_in_a_nested_helper_exempts_the_setup():
    src = """
def test_lookup_is_deferred():
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()

    def verify_later():
        lookup.assert_called_once()
"""
    assert _check(src) == []


def test_a_positive_assertion_on_a_sibling_path_does_not_exempt():
    # `x._server.get` being called says nothing about `update`.
    src = """
from unittest.mock import Mock

def test_conflict():
    update = Mock()
    x = Mock()
    update.return_value = {"result": "updated"}
    x._set_with_state(task_id, result, state)
    assert x._server.get.call_count == 1
    x._server.index.assert_called_once_with(id=task_id)
    update.assert_not_called()
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param("handle(other_request)", id="second-act"),
        pytest.param("result = handle(other_request)", id="second-act-with-result"),
        pytest.param("assert handle(other_request) is None", id="second-act-inside-assert"),
        pytest.param("lookup.return_value = 2\n    handle(other_request)", id="reconfigured-then-second-act"),
    ],
)
def test_code_after_the_assertion_that_can_run_the_mock_is_exempt(tail: str):
    src = f"""
def test_lookup():
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    {tail}
    assert True
"""
    assert _check(src) == []


def test_reconfiguring_after_the_assertion_without_a_second_act_still_flags():
    # Nothing runs after either write, so both the assertion and the rewrite
    # confirm the first value was never observed.
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = None
    handle(request)
    lookup.assert_not_called()
    lookup.return_value = 2
    assert True
"""
    assert len(_check(src)) == 1


def test_an_await_after_the_assertion_is_exempt():
    src = """
async def test_lookup():
    lookup.return_value = None
    await handle(request)
    lookup.assert_not_called()
    await shutdown()
"""
    assert _check(src) == []


def test_assertion_before_the_configuration_is_exempt():
    # An assertion before setup does not consume the later configured mock.
    src = """
def test_lookup():
    lookup.assert_not_called()
    lookup.return_value = None
    assert True
"""
    assert _check(src) == []


def test_a_configuration_on_the_assertions_own_line_is_still_for_what_comes_next():
    # Boundary on `line > stmt.lineno`: same line, configuration second.
    src = """
def test_lookup():
    lookup.assert_not_called(); lookup.return_value = None
    assert True
"""
    assert _check(src) == []


def test_configuration_then_assertion_on_the_same_line_is_exempt():
    src = """
def test_lookup():
    lookup.return_value = None; lookup.assert_not_called()
"""
    assert _check(src) == []


def test_assert_not_called_on_an_unrelated_path_is_exempt():
    src = """
def test_lookup():
    lookup.return_value = None
    handle(request)
    audit.record.assert_not_called()
"""
    assert _check(src) == []


def test_assert_not_called_on_an_extension_of_the_configured_path_is_exempt():
    # `lookup.inner` never being called says nothing about whether
    # `lookup` itself returned the configured value.
    src = """
def test_lookup():
    lookup.return_value = None
    handle(request)
    lookup.inner.assert_not_called()
"""
    assert _check(src) == []


def test_assert_not_called_in_a_nested_helper_does_not_reach_the_outer_setup():
    src = """
def test_lookup():
    lookup.return_value = None

    def _later():
        lookup.assert_not_called()

    register(_later)
"""
    assert _check(src) == []


def test_a_nested_helpers_configuration_does_not_pair_with_the_outer_assertion():
    # The mirror of the case above, and the one that pins `_NESTED_SCOPES`: a nested `def` owns its own scope, so the rule refuses to pair across the boundary in either direction.
    src = """
def test_lookup():
    def _arrange():
        lookup.return_value = None

    _arrange()
    handle(request)
    lookup.assert_not_called()
"""
    assert _check(src) == []


# Proven no-match boundaries.                                                  #


def test_reading_the_configured_value_between_writes_observes_the_first_setup():
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = first
    observed = lookup.return_value
    lookup.return_value = second
    assert observed is first
"""
    assert _check(src) == []


def test_a_mock_constructor_keyword_can_observe_another_pending_mock():
    src = """
from unittest.mock import Mock

def test_lookup():
    service = Mock(return_value=first)
    wrapper = Mock(return_value=service())
    service.return_value = second
    assert wrapper() is first
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    ("configuration", "observation", "replacement"),
    [
        pytest.param(
            "value.__add__.return_value = 7",
            "observed = value + 1",
            "value.__add__.return_value = 8",
            id="addition",
        ),
        pytest.param(
            "value.__eq__.return_value = True",
            "observed = value == sentinel",
            "value.__eq__.return_value = False",
            id="equality",
        ),
        pytest.param(
            "value.__iter__.return_value = iter(items)",
            "observed = [*value]",
            "value.__iter__.return_value = iter(())",
            id="iteration",
        ),
        pytest.param(
            "value.__format__.return_value = 'shown'",
            "observed = f'{value}'",
            "value.__format__.return_value = 'replaced'",
            id="formatting",
        ),
    ],
)
def test_magic_method_execution_observes_the_configured_value(
    configuration: str,
    observation: str,
    replacement: str,
):
    src = f"""
from unittest.mock import MagicMock

def test_protocol(items, sentinel):
    value = MagicMock()
    {configuration}
    {observation}
    {replacement}
    assert observed is not None
"""
    assert _check(src) == []


def test_directly_asserting_the_return_value_observes_the_setup():
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = result
    assert lookup.return_value is result
    lookup.assert_not_called()
"""
    assert _check(src) == []


def test_mutually_exclusive_configuration_and_negative_assertion_do_not_pair():
    src = """
from unittest.mock import Mock

def test_lookup(enabled):
    lookup = Mock()
    if enabled:
        lookup.return_value = result
    else:
        lookup.assert_not_called()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    ("path", "banner"),
    [
        pytest.param("tests/generated/test_client.py", "", id="generated-directory"),
        pytest.param(
            TEST_PATH,
            "# Code generated by the API compiler. DO NOT EDIT.\n",
            id="generated-banner",
        ),
    ],
)
def test_generated_tests_are_excluded(path: str, banner: str):
    source = """
from unittest.mock import Mock

def test_charge():
    charge = Mock()
    gateway = Mock(charge=charge)
    charge.return_value = 1
    charge.return_value = 2
    assert billing.charge(gateway) == 2
"""
    assert _check(banner + source, path) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
events = []

class Configuration:
    @property
    def return_value(self):
        return None

    @return_value.setter
    def return_value(self, value):
        events.append(value)

def test_configuration():
    config = Configuration()
    config.return_value = first
    config.return_value = second
    assert events == [first, second]
""",
            id="ordinary-property-setter",
        ),
        pytest.param(
            """
def test_configuration():
    config.return_value = result
    exercise(config)
    config.assert_not_called()
""",
            id="custom-negative-assert-api",
        ),
    ],
)
def test_unproven_mock_like_apis_are_excluded(source: str):
    assert _check(source) == []


def test_rebound_mocker_parameter_is_not_treated_as_the_pytest_mock_fixture():
    src = """
def test_lookup(mocker):
    mocker = custom_factory
    service = mocker.patch("app.service", return_value=first)
    service.return_value = second
    assert service() is second
"""
    assert _check(src) == []


def test_unknown_assert_method_after_negative_assertion_can_observe_the_setup():
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = result
    exercise(service)
    lookup.assert_not_called()
    verifier.assert_consistent(service)
"""
    assert _check(src) == []


def test_returning_the_mock_after_a_negative_assertion_escapes_its_configuration():
    src = """
from unittest.mock import Mock

def configured_service():
    lookup = Mock()
    lookup.return_value = result
    exercise(service)
    lookup.assert_not_called()
    return service
"""
    assert _check(src) == []


def test_a_loop_backedge_does_not_make_the_previous_iteration_setup_dead():
    src = """
from unittest.mock import Mock

def test_lookup(results):
    lookup = Mock()
    for result in results:
        lookup.return_value = result
    assert lookup.return_value is results[-1]
"""
    assert _check(src) == []


def test_parent_not_called_does_not_prove_a_configured_child_was_unused():
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = result
    exercise(lookup)
    service.assert_not_called()
"""
    assert _check(src) == []


# Shapes the rule deliberately cannot see — documented in the docstring.       #


def test_a_configured_path_never_mentioned_again_is_not_flagged():
    # The dominant real-world shape and the reason shape 1 was dropped: the SUT
    # is handed the whole mock and picks `.refund` off it.
    src = """
def test_charge():
    gateway = MagicMock()
    charge.return_value = Receipt(ok=True)
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


def test_attach_mock_configuration_is_not_flagged():
    src = """
def test_charge():
    gateway.attach_mock(refund, "refund")
    assert billing.charge(gateway, 100).ok
"""
    assert _check(src) == []


def test_mock_constructor_configuration_is_not_flagged():
    src = """
def test_charge():
    gateway = Mock(**{"refund.return_value": Receipt(ok=True)})
    assert billing.charge(gateway, 100).ok
"""
    assert _check(src) == []


def test_a_fixture_configuring_a_mock_for_its_caller_is_not_flagged():
    src = """
@pytest.fixture
def gateway():
    mock_gateway = MagicMock()
    mock_charge.return_value = Receipt(ok=True)
    return mock_gateway
"""
    assert _check(src) == []


def test_setup_method_configuring_a_shared_mock_is_not_flagged():
    src = """
class TestBilling:
    def setup_method(self):
        self.gateway = MagicMock()
        self.charge.return_value = Receipt(ok=True)

    def test_charge(self):
        assert billing.charge(self.gateway, 100).ok
"""
    assert _check(src) == []


def test_module_level_configuration_is_not_flagged():
    src = """
charge.return_value = 1
charge.return_value = 2
"""
    assert _check(src) == []


# Edge cases.                                                                  #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    a.return_value = 1\n") == []


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
    charge.return_value = gateway.refund.return_value = 1
    charge.return_value = 2
    assert billing.charge(gateway)
"""
    assert _check(src) == []


def test_a_statement_dead_under_both_shapes_is_reported_once():
    src = """
from unittest.mock import Mock

def test_lookup():
    lookup = Mock()
    lookup.return_value = 1
    lookup.return_value = 2
    handle(request)
    lookup.assert_not_called()
"""
    assert len(_check(src)) == 2


def test_multiple_hits_in_one_file_are_sorted_by_position():
    src = """
from unittest.mock import Mock

def test_one():
    a = Mock()
    m = Mock(a=a)
    a.return_value = 1
    a.return_value = 2
    run(m)

def test_two():
    assert run(m)

def test_three():
    b = Mock()
    m = Mock(b=b)
    b.return_value = 1
    b.return_value = 2
    run(m)
"""
    diags = _check(src)
    assert [d.line for d in diags] == [7, 17]


def test_diagnostics_carry_the_rule_code():
    assert all(d.code == "SARJ067" for d in _check(_ASSERTED_NOT_CALLED))


def test_the_exact_overwrite_message():
    [diag] = _check(_OVERWRITTEN)
    assert diag.message == (
        "`charge.return_value` is set here and overwritten on line 9 with nothing in between "
        "that could call the mock, so this value is never used. Delete the dead setup, or move the code "
        "under test between the two configurations"
    )


def test_reports_the_position_of_a_finding_nested_in_a_class_and_a_with_block():
    src = """
from unittest.mock import Mock, patch

class TestBilling:
    def test_charge(self):
        charge = Mock()
        gateway = Mock(charge=charge)
        with patch("billing.clock"):
            charge.return_value = 1
            charge.return_value = 2
            assert billing.charge(gateway) == 2
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (9, 13)
