from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_fixed_sleep_before_assert import NoFixedSleepBeforeAssert


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "tests/test_monitor.py") -> list[Diagnostic]:
    return NoFixedSleepBeforeAssert().check(Path(path), dedent(source))


@pytest.mark.parametrize("example", NoFixedSleepBeforeAssert.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_reports_awaited_sleep_followed_by_assert_at_the_sleep_statement() -> None:
    findings = _check(
        """
        import asyncio

        async def test_fires():
            monitor.start()
            await asyncio.sleep(0.5)
            assert monitor.fired
        """
    )

    assert [(finding.code, finding.line, finding.col) for finding in findings] == [("SARJ455", 6, 5)]


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
    source = f"{imports}\n\nasync def test_fires():\n    {call}\n    assert fired\n"

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("imports", "call"),
    [("import time", "time.sleep(0.2)"), ("from time import sleep as pause", "pause(0.2)")],
)
def test_reports_blocking_sleep_in_a_synchronous_test(imports: str, call: str) -> None:
    source = f"{imports}\n\ndef test_fires():\n    {call}\n    assert fired\n"

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "duration",
    [
        "0.05",
        "+0.05",
        "POLL_INTERVAL_SECONDS",
        "_FAST_POLL_SECONDS * 20",
        "POLL_INTERVAL_SECONDS * 2 + 0.05",
        "POLL_INTERVAL_SECONDS * 2 + EXTENDED_SILENCE_SECONDS / 4",
        "SilenceMonitor.POLL_INTERVAL // 2",
        "silence.POLL_INTERVAL_SECONDS - 0.01",
    ],
)
def test_reports_durations_built_from_literals_and_constants(duration: str) -> None:
    source = f"import asyncio\n\nasync def test_fires():\n    await asyncio.sleep({duration})\n    assert fired\n"

    assert len(_check(source)) == 1


def test_reports_sleeps_in_conditional_context_and_exception_blocks() -> None:
    findings = _check(
        """
        import asyncio

        async def test_fires(flag):
            if flag:
                await asyncio.sleep(1)
                assert fired
            else:
                pass
            async with monitor:
                await asyncio.sleep(1)
                assert fired
            try:
                await asyncio.sleep(1)
                assert fired
            finally:
                await asyncio.sleep(1)
                assert stopped
            match flag:
                case True:
                    await asyncio.sleep(1)
                    assert fired
        """
    )

    assert [finding.line for finding in findings] == [6, 11, 14, 17, 21]


def test_reports_methods_of_collected_test_classes_including_nested_ones() -> None:
    findings = _check(
        """
        import time

        class TestMonitor:
            def test_fires(self):
                time.sleep(1)
                assert fired

            class TestNested:
                def test_fires(self):
                    time.sleep(1)
                    assert fired
        """
    )

    assert [finding.line for finding in findings] == [6, 11]


@pytest.mark.parametrize("path", ["tests/test_monitor.py", "src/monitor_test.py", "test_monitor.py"])
def test_inspects_every_pytest_collected_module_name(path: str) -> None:
    source = "import asyncio\n\nasync def test_fires():\n    await asyncio.sleep(1)\n    assert fired\n"

    assert len(_check(source, path)) == 1


@pytest.mark.parametrize("duration", ["0", "0.0"])
def test_ignores_zero_sleeps_that_only_yield_to_the_event_loop(duration: str) -> None:
    source = f"import asyncio\n\nasync def test_fires():\n    await asyncio.sleep({duration})\n    assert fired\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    "duration",
    [
        "delay",
        "settings.poll_interval",
        "interval * 2",
        "POLL.total_seconds()",
        "timedelta(seconds=1).total_seconds()",
        "remaining if remaining > 0 else 0.1",
    ],
)
def test_ignores_durations_read_from_locals_parameters_or_calls(duration: str) -> None:
    source = f"import asyncio\n\nasync def test_fires(delay, settings, interval, remaining):\n    await asyncio.sleep({duration})\n    assert fired\n"

    assert _check(source) == []


def test_ignores_sleeps_inside_polling_loops() -> None:
    source = """
        import asyncio

        async def test_fires():
            for _ in range(50):
                if monitor.fired:
                    break
                await asyncio.sleep(0.01)
                assert attempts
            while not monitor.fired:
                await asyncio.sleep(0.01)
                assert attempts
            else:
                await asyncio.sleep(0.01)
                assert attempts
            assert monitor.fired
        """

    assert _check(source) == []


def test_ignores_sleeps_that_advance_the_clock_for_the_next_action() -> None:
    source = """
        import asyncio

        async def test_orders_by_creation():
            first = await store.create()
            await asyncio.sleep(0.01)
            second = await store.create()
            assert first.created_at < second.created_at
        """

    assert _check(source) == []


def test_ignores_a_trailing_sleep_and_an_assert_outside_the_sleep_block() -> None:
    source = """
        import asyncio

        async def test_fires():
            async with monitor:
                await asyncio.sleep(1)
            assert monitor.fired
            await asyncio.sleep(1)
        """

    assert _check(source) == []


def test_ignores_fixtures_helpers_nested_functions_and_non_test_classes() -> None:
    source = """
        import asyncio
        import pytest

        @pytest.fixture
        async def started_monitor():
            await asyncio.sleep(1)
            assert monitor.fired

        async def wait_then_check():
            await asyncio.sleep(1)
            assert monitor.fired

        async def test_fires():
            async def handler():
                await asyncio.sleep(1)
                assert monitor.fired

            await handler()

        class MonitorHarness:
            async def test_fires(self):
                await asyncio.sleep(1)
                assert monitor.fired
        """

    assert _check(source) == []


def test_leaves_blocking_sleep_in_async_tests_to_ruff() -> None:
    source = "import time\n\nasync def test_fires():\n    time.sleep(1)\n    assert fired\n"

    assert _check(source) == []


def test_ignores_async_sleeps_that_are_not_awaited() -> None:
    source = "import asyncio\n\nasync def test_fires():\n    asyncio.sleep(1)\n    assert fired\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def test_fires():\n    await sleep(1)\n    assert fired\n",
        "from asyncio import sleep\n\ndef sleep(seconds):\n    pass\n\nasync def test_fires():\n    await sleep(1)\n    assert fired\n",
        "import clock\n\nasync def test_fires():\n    await clock.sleep(1)\n    assert fired\n",
        "async def test_fires(fake_clock):\n    await fake_clock.sleep(1)\n    assert fired\n",
    ],
)
def test_ignores_sleeps_that_do_not_resolve_to_a_wall_clock_sleep(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    ["tests/conftest.py", "tests/helpers.py", "tests/fakes/monitor.py", "app/monitor.py", "tests/test_monitor.pyi"],
)
def test_ignores_modules_pytest_does_not_collect_tests_from(path: str) -> None:
    source = "import asyncio\n\nasync def test_fires():\n    await asyncio.sleep(1)\n    assert fired\n"

    assert _check(source, path) == []


def test_ignores_generated_and_malformed_modules() -> None:
    body = "import asyncio\n\nasync def test_fires():\n    await asyncio.sleep(1)\n    assert fired\n"

    assert _check(f"# @generated\n{body}") == []
    assert _check("async def test_fires(:\n    await asyncio.sleep(1)\n") == []
