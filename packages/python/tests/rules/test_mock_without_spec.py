from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.mock_without_spec import MockWithoutSpec


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return MockWithoutSpec().check(Path(path), source)


_BARE_MOCK = """
from unittest import mock

def test_thing():
    client = mock.Mock()
    assert client is not None
"""


# --------------------------------------------------------------------------- #
# Test-path gating: the rule ONLY fires inside test files.                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "test_call_store.py",
        "call_store_test.py",
        "tests/conftest.py",
        "conftest.py",
        "python/bulbul/tests/stores/seed.py",
        "deeply/nested/tests/data/factory.py",
    ],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_BARE_MOCK, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "python/bulbul/bulbul/calls/call_store.py",
        "src/service.py",
        "a/testing/thing.py",
        "attestation.py",
    ],
)
def test_skips_non_test_paths(path: str):
    assert _check(_BARE_MOCK, path) == []


# --------------------------------------------------------------------------- #
# Positive: every unspecced construction spelling fires.                       #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# FP guard: a spec-bearing argument gives the double a real contract.          #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# FP guard: the name is only trusted when a unittest.mock import backs it.     #
# This is what keeps hand-rolled MockFoo/Mock doubles out of the results.      #
# --------------------------------------------------------------------------- #


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
from agent.ports import VisionBankClient

class MockVisionBankClient(VisionBankClient):
    async def fetch(self, key: str) -> str:
        return "canned"

def test_thing():
    assert MockVisionBankClient()
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


# --------------------------------------------------------------------------- #
# Edge cases: empty / syntax error / multiple hits / position / sort order.    #
# --------------------------------------------------------------------------- #


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
