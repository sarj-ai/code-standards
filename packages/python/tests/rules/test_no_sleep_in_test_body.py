from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_sleep_in_test_body import NoSleepInTestBody


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/stores/test_call_flag_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return NoSleepInTestBody().check(Path(path), source)


_ASYNC_SLEEP = """
import asyncio

async def test_thing():
    await asyncio.sleep(0.01)
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
        "python/app/tests/stores/seed.py",
        "a/b/test/helper.py",
        "deeply/nested/tests/data/factory.py",
    ],
)
def test_fires_in_test_paths(path: str):
    assert len(_check(_ASYNC_SLEEP, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "python/app/app/calls/call_store.py",
        "src/service.py",
        "a/testing/thing.py",
        "a/contest.py",
        "attestation.py",
        "conftest/service.py",
    ],
)
def test_skips_non_test_paths(path: str):
    assert _check(_ASYNC_SLEEP, path) == []


# --------------------------------------------------------------------------- #
# Positive: nonzero sleep directly in a `test_*` body.                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "await asyncio.sleep(0.01)",
        "await asyncio.sleep(1)",
        "await asyncio.sleep(0.1)",
        "await asyncio.sleep(60)",
        "time.sleep(1)",
        "time.sleep(0.5)",
        "time.sleep(2)",
    ],
)
def test_flags_nonzero_sleep_in_async_test_body(call: str):
    src = f"async def test_x():\n    {call}\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "call",
    [
        "time.sleep(1)",
        "time.sleep(0.25)",
    ],
)
def test_flags_nonzero_sleep_in_sync_test_body(call: str):
    src = f"def test_x():\n    {call}\n"
    assert len(_check(src)) == 1


def test_flags_float_and_int():
    src = """
async def test_x():
    await asyncio.sleep(0.01)

async def test_y():
    time.sleep(3)
"""
    assert len(_check(src)) == 2


def test_flags_sleep_deeper_in_test_body_straight_line():
    src = """
async def test_x():
    setup()
    if True:
        await asyncio.sleep(0.5)
"""
    assert len(_check(src)) == 1


def test_code_and_message():
    diags = _check(_ASYNC_SLEEP)
    assert len(diags) == 1
    assert diags[0].code == "SARJ031"
    assert "sleep" in diags[0].message


def test_diagnostic_path_preserved():
    diags = _check(_ASYNC_SLEEP)
    assert diags[0].path == Path(TEST_PATH)


# --------------------------------------------------------------------------- #
# Negative: sleep(0) and non-literal args are deliberate, not flaky syncs.     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "await asyncio.sleep(0)",
        "await asyncio.sleep(0.0)",
        "time.sleep(0)",
    ],
)
def test_allows_zero_sleep(call: str):
    src = f"async def test_x():\n    {call}\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        "await asyncio.sleep(delay)",
        "await asyncio.sleep(self.timeout)",
        "await asyncio.sleep(POLL_INTERVAL)",
        "time.sleep(wait_s)",
        "await asyncio.sleep(-1)",
        "await asyncio.sleep(compute())",
    ],
)
def test_allows_non_literal_arg(call: str):
    src = f"async def test_x():\n    {call}\n"
    assert _check(src) == []


def test_allows_sleep_with_no_args():
    src = "async def test_x():\n    await asyncio.sleep()\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Critical FP guard: sleeps inside a NESTED function within the test.          #
# --------------------------------------------------------------------------- #


def test_allows_sleep_in_nested_async_helper():
    src = """
async def test_cancellation():
    async def _hang():
        await asyncio.sleep(60)

    task = create(_hang)
    task.cancel()
"""
    assert _check(src) == []


def test_allows_sleep_in_nested_sync_helper():
    src = """
def test_x():
    def _slow():
        time.sleep(60)

    run(_slow)
"""
    assert _check(src) == []


def test_allows_sleep_in_nested_mock_coroutine():
    src = """
async def test_parallel_queries():
    async def mock_is_blocked(org):
        await asyncio.sleep(0.05)
        return False

    await run(mock_is_blocked)
"""
    assert _check(src) == []


def test_allows_sleep_in_lambda_within_test():
    src = "async def test_x():\n    fn = lambda: asyncio.sleep(1)\n    schedule(fn)\n"
    assert _check(src) == []


def test_allows_sleep_in_deeply_nested_helper():
    src = """
async def test_x():
    async def outer():
        async def inner():
            await asyncio.sleep(1)
        return inner
"""
    assert _check(src) == []


def test_fires_for_test_body_but_not_its_nested_helper():
    src = """
async def test_x():
    async def _slow():
        await asyncio.sleep(60)

    await asyncio.sleep(0.01)
    await run(_slow)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6


# --------------------------------------------------------------------------- #
# Negative: non-test functions, module scope, other receivers.                #
# --------------------------------------------------------------------------- #


def test_allows_sleep_in_non_test_helper_in_test_file():
    src = """
def helper():
    time.sleep(1)

async def _wait_for():
    await asyncio.sleep(0.05)
"""
    assert _check(src) == []


def test_allows_sleep_in_fixture_named_function():
    src = """
async def fixture_thing():
    await asyncio.sleep(1)
"""
    assert _check(src) == []


def test_allows_module_level_sleep():
    src = "import asyncio\nawait asyncio.sleep(1)\n"
    assert _check("async def _m():\n    await asyncio.sleep(1)\n") == []
    assert _check(src) == []


@pytest.mark.parametrize(
    "recv",
    ["obj", "self", "trio", "client", "loop", "mock"],
)
def test_allows_non_asyncio_time_receiver(recv: str):
    src = f"async def test_x():\n    await {recv}.sleep(1)\n"
    assert _check(src) == []


def test_allows_bare_sleep_call():
    src = "async def test_x():\n    sleep(1)\n"
    assert _check(src) == []


def test_allows_attribute_chain_receiver():
    src = "async def test_x():\n    await mod.asyncio.sleep(1)\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases: empty / whitespace / syntax error.                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "   ", "\n\n", "# just a comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def test_x(:\n    pass",
        "def test_x(:\n",
        "async def test_x():\n await asyncio.sleep(1)\n  bad_indent\n",
    ],
)
def test_syntax_error_returns_empty(source: str):
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Counts, line/col, sorting.                                                   #
# --------------------------------------------------------------------------- #


def test_multiple_sleeps_in_one_test_all_fire():
    src = """
async def test_x():
    await asyncio.sleep(0.01)
    do_work()
    await asyncio.sleep(0.02)
    time.sleep(1)
"""
    assert len(_check(src)) == 3


def test_line_col_async_sleep():
    src = "async def test_x():\n    await asyncio.sleep(0.01)\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 11


def test_line_col_sync_sleep():
    src = "def test_x():\n    time.sleep(1)\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


def test_results_sorted_by_line_col():
    src = """
async def test_a():
    await asyncio.sleep(0.03)

async def test_b():
    time.sleep(1)
    await asyncio.sleep(2)
"""
    diags = _check(src)
    assert len(diags) == 3
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_sibling_tests_flagged_independently():
    src = """
async def test_a():
    await asyncio.sleep(0.01)

async def test_b():
    await asyncio.sleep(0.02)
"""
    assert len(_check(src)) == 2


# --------------------------------------------------------------------------- #
# FP-hardening (famous-repo sweep): a sleep inside a while loop is polling —   #
# the remedy this rule's own message prescribes (trio's OS-thread waits).      #
# --------------------------------------------------------------------------- #


def test_sleep_in_while_poll_loop_is_exempt():
    # Minimized from trio's test_threads.py: poll until the OS thread finishes.
    src = """
import time

def test_thread_finishes(register):
    while register[0] != "finished":
        time.sleep(0.01)
"""
    assert _check(src) == []


def test_sleep_in_while_condition_poll_with_body_is_exempt():
    src = """
import time

def test_thread_dies(q2):
    thread = q2.get()
    while thread.is_alive():
        time.sleep(0.01)
    assert done()
"""
    assert _check(src) == []


def test_bare_sleep_after_while_loop_still_fires():
    src = """
import time

def test_thread(q):
    while q.empty():
        pass
    time.sleep(1)
    assert done()
"""
    assert len(_check(src)) == 1


def test_sleep_in_nested_def_inside_while_still_attributed_to_helper():
    src = """
import time

def test_x():
    while cond():
        def _helper():
            time.sleep(1)
        _helper()
"""
    assert _check(src) == []


def test_sleep_in_bounded_poll_for_loop_is_exempt():
    src = """
import time

def test_thread_exits(initial_count):
    for _ in range(10):
        if threading.active_count() == initial_count:
            return
        time.sleep(0.1)
    pytest.fail("thread did not exit")
"""
    assert _check(src) == []


def test_async_sleep_in_bounded_poll_for_loop_is_exempt():
    src = """
import asyncio

async def test_task_starts(started):
    for _ in range(20):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
"""
    assert _check(src) == []


def test_sleep_in_for_loop_without_conditional_exit_still_fires():
    src = """
import time

def test_growing_display(live):
    for step in range(10):
        live.update(step)
        time.sleep(0.2)
"""
    assert len(_check(src)) == 1


def test_sleep_after_poll_for_loop_still_fires():
    src = """
import time

def test_ready(flag):
    for _ in range(10):
        if flag.is_set():
            break
        time.sleep(0.01)
    time.sleep(2)
    assert flag.is_set()
"""
    assert len(_check(src)) == 1
