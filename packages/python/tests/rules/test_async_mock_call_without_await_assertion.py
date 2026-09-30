import asyncio
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock  # ruff: ignore[banned-api] — regression tests exercise AsyncMock assertion semantics

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rules.async_mock_call_without_await_assertion import AsyncMockCallWithoutAwaitAssertion


if TYPE_CHECKING:
    from collections.abc import Coroutine

    from _pytest.capture import CaptureFixture

    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "tests/test_delivery.py") -> list[Diagnostic]:
    return AsyncMockCallWithoutAwaitAssertion().check(Path(path), dedent(source))


@pytest.mark.parametrize("example", AsyncMockCallWithoutAwaitAssertion.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


@pytest.mark.parametrize(
    ("imports", "factory"),
    [
        ("from unittest.mock import AsyncMock", "AsyncMock"),
        ("from unittest.mock import AsyncMock as AM", "AM"),
        ("import unittest.mock as mocks", "mocks.AsyncMock"),
        ("import unittest.mock", "unittest.mock.AsyncMock"),
        ("from unittest import mock", "mock.AsyncMock"),
    ],
)
@pytest.mark.parametrize(
    "assertion", ["assert_called()", "assert_called_once()", "assert_called_with(1)", "assert_called_once_with(1)"]
)
def test_reports_imported_async_mock_calls(imports: str, factory: str, assertion: str) -> None:
    source = f"{imports}\nasync def test_delivery():\n    send = {factory}()\n    await deliver(send)\n    send.{assertion}\n"

    findings = _check(source)

    assert [(item.code, item.line, item.col) for item in findings] == [("SARJ456", 5, 5)]


def test_supports_local_imports_and_unmodified_async_children() -> None:
    source = """
        async def test_delivery():
            from unittest.mock import AsyncMock as AM
            service = AM()
            service.send.return_value = 1
            await deliver(service)
            service.send.assert_called_once()
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "assertion",
    [
        "send.assert_awaited()",
        "send.assert_awaited_once()",
        "send.assert_awaited_with(1)",
        "send.assert_awaited_once_with(1)",
        "send.assert_any_await(1)",
        "send.assert_has_awaits([call(1)])",
        "send.assert_has_awaits([call(1)], any_order=True)",
        "assert send.await_count == 1",
        "assert send.await_args.args == (1,)",
        "assert send.await_args_list == [call(1)]",
    ],
)
def test_preserves_existing_await_oracles(assertion: str) -> None:
    source = f"from unittest.mock import AsyncMock\nasync def test_delivery():\n    send = AsyncMock()\n    send.assert_called_once_with(1)\n    {assertion}\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "send = fixture\nsend.assert_called_once()",
        "send = AsyncMock\nsend.assert_called_once()",
        "send = AsyncMock(spec=Service)\nsend.sync_method.assert_called_once()",
        "send = AsyncMock(Service)\nsend.sync_method.assert_called_once()",
        "send = AsyncMock(**options)\nsend.assert_called_once()",
        "send = AsyncMock()\nsend = fixture\nsend.assert_called_once()",
        "send = AsyncMock()\nif flag:\n    send = fixture\nsend.assert_called_once()",
        "send = AsyncMock()\nsend.reset_mock()\nsend.assert_called_once()",
        "send = AsyncMock()\nsend.configure_mock(child=fixture)\nsend.child.assert_called_once()",
        "send = AsyncMock()\nsend.child = fixture\nsend.child.assert_called_once()",
        "send = AsyncMock()\nsetattr(send, 'child', fixture)\nsend.child.assert_called_once()",
        "send = AsyncMock()\nalias = send\nalias.reset_mock()\nsend.assert_called_once()",
        "send = AsyncMock()\nalias = send.child\nalias.reset_mock()\nsend.child.assert_called_once()",
        "send = AsyncMock()\naliases = [send]\naliases[0].reset_mock()\nsend.assert_called_once()",
        "global send\nsend = AsyncMock()\nsend.assert_called_once()",
        "send = AsyncMock()\nif flag:\n    send.assert_called_once()",
        "send = AsyncMock()\nsend.return_value.assert_called_once()",
        "send = AsyncMock()\nsend.assert_not_called()",
        "send = AsyncMock()\nsend.assert_has_calls([])",
        "send = AsyncMock()\ndef helper():\n    send.assert_called_once()",
        "send = AsyncMock()\nsend.assert_called_once = custom_assertion\nsend.assert_called_once()",
        "send = AsyncMock()\nsend.child.reset_mock()\nsend.child.assert_called_once()",
    ],
)
def test_abstains_from_ambiguous_provenance_and_control_flow(body: str) -> None:
    source = "from unittest.mock import AsyncMock\nasync def test_delivery():\n" + "\n".join(
        f"    {line}" for line in body.splitlines()
    )

    assert _check(source) == []


@pytest.mark.parametrize("shadow", ["AsyncMock = custom", "def AsyncMock(): pass"])
def test_ignores_shadowed_constructor(shadow: str) -> None:
    source = f"from unittest.mock import AsyncMock\n{shadow}\nasync def test_delivery():\n    send = AsyncMock()\n    send.assert_called_once()\n"

    assert _check(source) == []


def test_ignores_rebound_module_constructor() -> None:
    source = """
        import unittest.mock as mocks
        mocks.AsyncMock = custom
        async def test_delivery():
            send = mocks.AsyncMock()
            send.assert_called_once()
    """

    assert _check(source) == []


def test_ignores_fixture_even_when_its_name_starts_with_test() -> None:
    source = """
        import pytest
        from unittest.mock import AsyncMock
        @pytest.fixture()
        def test_delivery():
            send = AsyncMock()
            send.assert_called_once()
    """

    assert _check(source) == []


@pytest.mark.parametrize("assertion", ["assert_awaited_once()", "assert_any_await(1)", "assert_has_awaits([call(1)])"])
def test_does_not_treat_another_mock_or_a_conditional_await_assertion_as_coverage(assertion: str) -> None:
    source = f"""
        from unittest.mock import AsyncMock
        async def test_delivery():
            first = AsyncMock()
            second = AsyncMock()
            first.assert_called_once()
            second.{assertion}
            if flag:
                first.{assertion}
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "path", ["tests/helpers.py", "tests/conftest.py", "src/delivery.py", "tests/test_delivery.pyi"]
)
def test_ignores_non_test_modules(path: str) -> None:
    source = "from unittest.mock import AsyncMock\ndef test_delivery():\n    send = AsyncMock()\n    send.assert_called_once()\n"

    assert _check(source, path) == []


def test_ignores_generated_and_malformed_source() -> None:
    assert (
        _check(
            "# @generated\nfrom unittest.mock import AsyncMock\ndef test_delivery():\n    send = AsyncMock()\n    send.assert_called_once()\n"
        )
        == []
    )
    assert _check("def test_delivery(:") == []


def test_reports_one_diagnostic_for_redundant_call_assertions() -> None:
    source = """
        from unittest.mock import AsyncMock
        class TestDelivery:
            async def test_delivery(self):
                send = AsyncMock(spec=Service)
                send.assert_called()
                send.assert_called_once()
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize("suppression", ["", "  # sarj-noqa: SARJ456 — contract checks scheduling before awaiting"])
def test_cli_blocks_missing_await_evidence_and_supports_scheduling_exceptions(
    tmp_path: Path, capsys: CaptureFixture[str], suppression: str
) -> None:
    source = f"from unittest.mock import AsyncMock\ndef test_schedules():\n    send = AsyncMock()\n    schedule(send)\n    send.assert_called_once(){suppression}\n"
    path = tmp_path / "test_delivery.py"
    path.write_text(source)

    assert main(["check", "--rule", "async-mock-call-without-await-assertion", str(path)]) == (0 if suppression else 1)
    output = capsys.readouterr()
    assert output.out.count("SARJ456 ") == (0 if suppression else 1)
    assert not output.err


def test_call_assertion_does_not_prove_an_await() -> None:
    send = AsyncMock()
    pending: Coroutine[object, object, object] = send("item")  # pyright: ignore[reportAny] — AsyncMock's stub returns Any
    try:
        send.assert_called_once_with(
            "item"
        )  # sarj-noqa: SARJ456 — reproduction proves call assertions accept dropped coroutines
        with pytest.raises(AssertionError, match="Awaited 0 times"):
            send.assert_awaited_once_with("item")
    finally:
        pending.close()


def test_await_assertion_does_not_replace_call_count_coverage() -> None:
    send = AsyncMock()
    completed: Coroutine[object, object, object] = send("item")  # pyright: ignore[reportAny] — AsyncMock's stub returns Any
    asyncio.run(completed)
    pending: Coroutine[object, object, object] = send("extra")  # pyright: ignore[reportAny] — AsyncMock's stub returns Any
    try:
        send.assert_awaited_once_with("item")
        with pytest.raises(AssertionError, match="Called 2 times"):
            send.assert_called_once_with("item")
    finally:
        pending.close()


@pytest.mark.parametrize(
    "condition",
    [
        "send.called",
        "send.called is True",
        "send.call_count",
        "send.call_count == 2",
        "2 == send.call_count",
        "send.call_count > 0",
        "1 <= send.call_count",
        "send.call_count != 0",
        "send.called and enabled",
        "send.called or send.call_count > 0",
    ],
)
def test_positive_call_state_requires_await_evidence(condition: str) -> None:
    source = (
        f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    assert {condition}\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "send.call_count == 0",
        "send.call_count >= 0",
        "send.call_count < 2",
        "not send.called",
        "send.called is False",
        "send.called or enabled",
        "send.call_count != -1",
    ],
)
def test_nonpositive_call_state_is_not_a_positive_call_contract(condition: str) -> None:
    source = (
        f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    assert {condition}\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "oracle",
    [
        "assert send.await_count >= 0",
        "assert send.await_count == 0",
        "assert send.await_args is None",
        "assert send.await_args_list == []",
        "assert send.await_count > 0 or enabled",
        "send.assert_has_awaits([])",
    ],
)
def test_nonpositive_await_state_does_not_cover_positive_calls(oracle: str) -> None:
    source = f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    send.assert_called_once()\n    {oracle}\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "send.await_count",
        "send.await_count > 0",
        "1 <= send.await_count",
        "send.await_args is not None",
        "send.await_args_list",
        "send.await_args_list != []",
        "send.await_count > 0 and enabled",
        "send.await_count == 1 or send.await_args is not None",
    ],
)
def test_positive_await_state_covers_call_counts(condition: str) -> None:
    source = f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    assert send.call_count == 1\n    assert {condition}\n"
    assert _check(source) == []


def test_numeric_call_state_preserves_async_child_provenance_and_suppression() -> None:
    source = "from unittest.mock import AsyncMock\nasync def test_send():\n    store = AsyncMock()\n    assert store.upsert.call_count == 2\n"
    assert len(_check(source)) == 1
    assert _check(source.replace("AsyncMock()", "AsyncMock(spec=Store)")) == []
    assert _check(source.replace("== 2", "== 2  # sarj-noqa: SARJ456 -- scheduling before execution")) == []


def test_unawaited_call_satisfies_numeric_call_assertion_and_nonpositive_await_check() -> None:
    send = AsyncMock()
    pending: Coroutine[object, object, object] = send("item")  # pyright: ignore[reportAny] -- runtime AsyncMock reproduction
    try:
        assert send.call_count == 1  # sarj-noqa: SARJ456 -- demonstrate a dropped coroutine
        assert send.await_count >= 0
        assert send.await_count == 0
    finally:
        pending.close()


@pytest.mark.parametrize(
    "oracle",
    [
        "assert not send.await_count == 0",
        "assert not send.await_args is None",
        "send.assert_has_awaits(calls=[call(1)])",
    ],
)
def test_equivalent_positive_await_oracles_remain_valid(oracle: str) -> None:
    source = f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    assert send.call_count == 1\n    {oracle}\n"
    assert _check(source) == []


def test_two_mock_counts_on_one_line_have_distinct_locations() -> None:
    source = "from unittest.mock import AsyncMock\nasync def test_send():\n    first = AsyncMock()\n    second = AsyncMock()\n    assert first.call_count == 1 and second.called\n"
    findings = _check(source)
    assert len(findings) == 2
    assert len({(item.line, item.col) for item in findings}) == 2


@pytest.mark.parametrize("state", ["call_count", "called", "await_count", "await_args", "await_args_list"])
def test_replaced_call_or_await_state_is_not_inferred(state: str) -> None:
    source = f"from unittest.mock import AsyncMock\nasync def test_send():\n    send = AsyncMock()\n    send.{state} = custom\n    assert send.call_count == 1\n"
    assert _check(source) == []
