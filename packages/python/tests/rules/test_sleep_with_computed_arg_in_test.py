from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_sleep_in_test_body import NoSleepInTestBody
from sarj_python_lint.rules.sleep_with_computed_arg_in_test import SleepWithComputedArgInTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/agent/tests/test_idle_monitor.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return SleepWithComputedArgInTest().check(Path(path), source)


_COMPUTED_SLEEP = """
import asyncio

async def test_thing():
    await asyncio.sleep(POLL_INTERVAL_SECONDS * 4)
    assert done()
"""


# --------------------------------------------------------------------------- #
# Test-path gating.                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "conftest.py", "a/tests/h.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_COMPUTED_SLEEP, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_COMPUTED_SLEEP, path) == []


# --------------------------------------------------------------------------- #
# Positive: every non-literal delay shape.                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "delay",
    [
        "POLL_INTERVAL_SECONDS * 4",
        "POLL_INTERVAL_SECONDS * 2 + 0.05",
        "EXTENDED_SILENCE_SECONDS / 4",
        "delay",
        "settings.poll_interval",
        "compute_delay()",
    ],
)
def test_flags_computed_delays(delay: str):
    src = f"""
import asyncio

async def test_thing():
    await asyncio.sleep({delay})
"""
    assert len(_check(src)) == 1


def test_flags_blocking_time_sleep():
    src = """
import time

def test_thing():
    time.sleep(TIMEOUT * 2)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Disjointness with SARJ031: a literal delay belongs to that rule, and no      #
# single sleep may ever be reported by both.                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("delay", ["0.01", "1", "2.5", "0"])
def test_numeric_literals_belong_to_sarj031(delay: str):
    src = f"""
import asyncio

async def test_thing():
    await asyncio.sleep({delay})
"""
    assert _check(src) == []


@pytest.mark.parametrize("delay", ["0.01", "POLL * 4"])
def test_no_sleep_is_reported_by_both_rules(delay: str):
    src = f"""
import asyncio

async def test_thing():
    await asyncio.sleep({delay})
"""
    combined = len(_check(src)) + len(NoSleepInTestBody().check(Path(TEST_PATH), src))
    assert combined <= 1


# --------------------------------------------------------------------------- #
# FP guard: nearest enclosing function, inherited from SARJ031.                #
# --------------------------------------------------------------------------- #


def test_sleep_in_nested_fake_coroutine_is_exempt():
    # A configured latency simulator exercising a timeout path is the intended
    # use of a computed delay.
    src = """
import asyncio

async def test_thing():
    async def _hang():
        await asyncio.sleep(TIMEOUT * 2)
    await run_with_timeout(_hang)
"""
    assert _check(src) == []


def test_sleep_in_fixture_is_exempt():
    src = """
import asyncio
import pytest

@pytest.fixture
async def slow_thing():
    await asyncio.sleep(DELAY * 2)
    return True
"""
    assert _check(src) == []


def test_sleep_in_module_level_helper_is_exempt():
    src = """
import asyncio

async def _settle():
    await asyncio.sleep(POLL * 3)
"""
    assert _check(src) == []


def test_sleep_in_lambda_is_exempt():
    src = """
import asyncio

def test_thing():
    cb = lambda: asyncio.sleep(DELAY * 2)
    register(cb)
"""
    assert _check(src) == []


def test_unrelated_sleep_receiver_is_exempt():
    src = """
def test_thing():
    scheduler.sleep(DELAY * 2)
"""
    assert _check(src) == []


def test_directly_imported_sleep_is_exempt():
    src = """
from asyncio import sleep

async def test_thing():
    await sleep(DELAY * 2)
"""
    assert _check(src) == []


def test_sleep_with_no_arguments_is_exempt():
    src = """
import asyncio

async def test_thing():
    await asyncio.sleep()
"""
    assert _check(src) == []


def test_module_level_sleep_is_exempt():
    src = """
import time
time.sleep(DELAY * 2)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("async def test_x(:\n    await asyncio.sleep(D * 2)\n") == []


def test_multiple_hits_in_one_file():
    src = """
import asyncio

async def test_one():
    await asyncio.sleep(POLL * 2)

async def test_two():
    await asyncio.sleep(0.01)

async def test_three():
    await asyncio.sleep(POLL * 4)
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_call():
    src = """
import asyncio

async def test_thing():
    await asyncio.sleep(POLL * 4)
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (5, 11)
    assert diag.code == "SARJ047"


def test_diagnostics_are_sorted_by_position():
    src = """
import asyncio

async def test_thing():
    await asyncio.sleep(A * 2)
    await asyncio.sleep(B * 2)
    await asyncio.sleep(C * 2)
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)
