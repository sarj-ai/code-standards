from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_fixed_sleep_in_loop import NoFixedSleepInLoop


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/poller.py") -> list[Diagnostic]:
    return NoFixedSleepInLoop().check(Path(path), dedent(source))


def _polling(call: str, imports: str = "import asyncio") -> str:
    return f"{imports}\n\nasync def poll(job):\n    while not job.done:\n        {call}\n"


def test_documented_examples() -> None:
    verify_native_rule(NoFixedSleepInLoop, analyze)


def test_reports_one_warning_at_the_awaited_sleep() -> None:
    findings = _check(_polling("await asyncio.sleep(2)"))

    assert [(item.code, item.line, item.col, item.severity) for item in findings] == [
        ("SARJ485", 5, 9, Severity.WARNING)
    ]


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("import asyncio", "await asyncio.sleep(1)"),
        ("import asyncio as aio", "await aio.sleep(1)"),
        ("from asyncio import sleep", "await sleep(1)"),
        ("from asyncio import sleep as pause", "await pause(1)"),
        ("import anyio", "await anyio.sleep(1)"),
        ("import trio", "await trio.sleep(1)"),
        ("import asyncio", "await asyncio.sleep(delay=1)"),
        ("import trio", "await trio.sleep(seconds=1)"),
    ],
)
def test_reports_async_sleep_implementations_and_aliases(imports: str, call: str) -> None:
    assert len(_check(_polling(call, imports))) == 1


@pytest.mark.parametrize(
    ("imports", "call"), [("import time", "time.sleep(0.5)"), ("from time import sleep as pause", "pause(0.5)")]
)
def test_reports_blocking_sleep_in_a_synchronous_loop(imports: str, call: str) -> None:
    source = f"{imports}\n\ndef poll(job):\n    for _ in range(10):\n        {call}\n"

    assert len(_check(source)) == 1


@pytest.mark.parametrize("duration", ["2", "0.05", "+1", "60 * 5", "1 / 2", "3 - 1", "10 // 3", "-(-1)"])
def test_reports_positive_durations_folded_from_literals(duration: str) -> None:
    assert len(_check(_polling(f"await asyncio.sleep({duration})"))) == 1


@pytest.mark.parametrize("duration", ["0", "0.0", "-1", "1 - 1", "1 / 0", "True", "2 ** 3", "'2'"])
def test_ignores_yields_negative_unfoldable_and_non_numeric_durations(duration: str) -> None:
    assert _check(_polling(f"await asyncio.sleep({duration})")) == []


@pytest.mark.parametrize(
    "duration",
    [
        "self._timing.poll_seconds",
        "POLL_SECONDS",
        "_POLL_SECONDS * 2",
        "Timing.POLL_SECONDS",
        "interval.total_seconds()",
        "min(remaining, 2)",
        "_DELAYS[attempt]",
        "poll_seconds",
    ],
)
def test_ignores_durations_read_from_names_attributes_or_calls(duration: str) -> None:
    assert _check(_polling(f"await asyncio.sleep({duration})")) == []


@pytest.mark.parametrize(
    ("constant", "duration"),
    [
        ("POLL_SECONDS = 2", "POLL_SECONDS"),
        ("_POLL_SECONDS: float = 0.5", "_POLL_SECONDS"),
        ("POLL_SECONDS = 1", "POLL_SECONDS * 2 + 0.5"),
        ("POLL_SECONDS = 60 * 5", "POLL_SECONDS"),
    ],
)
def test_reports_module_constants_bound_once_to_a_positive_literal(constant: str, duration: str) -> None:
    assert len(_check(_polling(f"await asyncio.sleep({duration})", f"import asyncio\n\n{constant}"))) == 1


@pytest.mark.parametrize(
    ("module", "duration"),
    [
        ("POLL_SECONDS = 0", "POLL_SECONDS"),
        ("poll_seconds = 2", "poll_seconds"),
        ("POLL_SECONDS = 2\nPOLL_SECONDS = 3", "POLL_SECONDS"),
        ("POLL_SECONDS = 2\nPOLL_SECONDS += 1", "POLL_SECONDS"),
        ("POLL_SECONDS = settings.poll_seconds", "POLL_SECONDS"),
        ("POLL_SECONDS: float", "POLL_SECONDS"),
        ("from app.timing import POLL_SECONDS", "POLL_SECONDS"),
        (
            "POLL_SECONDS = 2\n\ndef configure(seconds):\n    global POLL_SECONDS\n    POLL_SECONDS = seconds",
            "POLL_SECONDS",
        ),
        ("POLL_SECONDS = 2\n\ndef configure(POLL_SECONDS):\n    pass", "POLL_SECONDS"),
        ("class Timing:\n    POLL_SECONDS = 2", "Timing.POLL_SECONDS"),
        ("if fast:\n    POLL_SECONDS = 2", "POLL_SECONDS"),
    ],
)
def test_ignores_constants_that_are_zero_configurable_or_ambiguous(module: str, duration: str) -> None:
    assert _check(_polling(f"await asyncio.sleep({duration})", f"import asyncio\n\n{module}")) == []


def test_reports_every_loop_form_and_nested_blocks_inside_the_body() -> None:
    findings = _check(
        """
        import asyncio

        async def drain(queue, stream):
            for item in queue:
                await asyncio.sleep(1)
            async for chunk in stream:
                if chunk:
                    try:
                        await asyncio.sleep(1)
                    finally:
                        pass
            while True:
                async with queue.lock:
                    match queue.state:
                        case "busy":
                            await asyncio.sleep(1)
                        case _:
                            break
        """
    )

    assert [finding.line for finding in findings] == [6, 10, 17]


def test_reports_methods_and_nested_functions_with_their_own_loops() -> None:
    findings = _check(
        """
        import asyncio

        class Cleaner:
            async def run(self):
                for call in self.calls:
                    await asyncio.sleep(2)

        async def outer():
            async def inner():
                while True:
                    await asyncio.sleep(2)
            await inner()
        """
    )

    assert [finding.line for finding in findings] == [7, 12]


def test_ignores_sleeps_outside_loop_bodies() -> None:
    source = """
        import asyncio

        async def settle(job):
            await asyncio.sleep(2)
            for item in job.items:
                pass
            else:
                await asyncio.sleep(2)
            while await asyncio.sleep(2):
                pass
        """

    assert _check(source) == []


def test_ignores_loops_across_nested_scopes() -> None:
    source = """
        import asyncio
        import time

        async def outer(jobs):
            for job in jobs:
                async def wait():
                    await asyncio.sleep(2)
                handler = lambda: time.sleep(2)

                class Waiter:
                    pause = time.sleep(2)
        """

    assert _check(source) == []


def test_ignores_module_and_class_level_loops() -> None:
    source = """
        import time

        while True:
            time.sleep(5)

        class Settings:
            for _ in range(3):
                time.sleep(1)
        """

    assert _check(source) == []


def test_leaves_blocking_sleep_in_async_functions_to_ruff() -> None:
    source = "import time\n\nasync def poll(job):\n    while True:\n        time.sleep(1)\n"

    assert _check(source) == []


def test_ignores_unawaited_async_sleeps() -> None:
    assert _check(_polling("task = asyncio.sleep(1)")) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def poll(job):\n    while True:\n        await sleep(1)\n",
        "from asyncio import sleep\n\nasync def poll(sleep):\n    while True:\n        await sleep(1)\n",
        "import clock\n\nasync def poll():\n    while True:\n        await clock.sleep(1)\n",
        "async def poll(self):\n    while True:\n        await self._sleep(1)\n",
    ],
)
def test_ignores_sleeps_that_do_not_resolve_to_a_wall_clock_sleep(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_poller.py",
        "app/test_poller.py",
        "app/poller_test.py",
        "tests/helpers.py",
        "conftest.py",
        "app/fakes/poller.py",
        "app/testing.py",
    ],
)
def test_ignores_test_and_test_support_paths(path: str) -> None:
    assert _check(_polling("await asyncio.sleep(1)"), path) == []


def test_ignores_generated_and_malformed_modules() -> None:
    assert _check("# @generated\n" + _polling("await asyncio.sleep(1)")) == []
    assert _check("async def poll(:\n    while True:\n        await asyncio.sleep(1)\n") == []


def test_exact_suppression_silences_only_its_own_code() -> None:
    suppressed = _polling("await asyncio.sleep(1)  # sarj-noqa: SARJ485 -- vendor rate limit")
    other = _polling("await asyncio.sleep(1)  # sarj-noqa: SARJ455")

    assert _check(suppressed) == []
    assert len(_check(other)) == 1


def test_reports_each_sleep_once_through_the_analyzer(tmp_path: Path) -> None:
    module = tmp_path / "app" / "poller.py"
    module.parent.mkdir()
    module.write_text(_polling("await asyncio.sleep(1); await asyncio.sleep(2)"), encoding="utf-8")

    findings = analyze([NoFixedSleepInLoop.id], [module])

    assert [(item.line, item.col) for item in findings] == [(5, 9), (5, 33)]
