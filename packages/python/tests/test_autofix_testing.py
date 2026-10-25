from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


_RULE = "async-mock-call-without-await-assertion"
_PATH = Path("tests/test_delivery.py")
_SOURCE = "from unittest.mock import AsyncMock\nasync def test_delivery():\n    send = AsyncMock()\n    await send()\n    send.assert_called_once()\n"


@pytest.mark.parametrize(
    ("invocation", "assertion", "added"),
    [
        ("send()", "send.assert_called_once()", "send.assert_awaited_once()"),
        ("send('item')", "send.assert_called_once_with('item')", "send.assert_awaited_once_with('item')"),
        (
            "send(3, flag=True)",
            "send.assert_called_once_with(3, flag=True)",
            "send.assert_awaited_once_with(3, flag=True)",
        ),
        (
            "send('é', payload=b'item')",
            "send.assert_called_once_with('é', payload=b'item')",
            "send.assert_awaited_once_with('é', payload=b'item')",
        ),
    ],
)
def test_exact_mock_call_retains_original_and_adds_matching_await_evidence(
    invocation: str, assertion: str, added: str, tmp_path: Path
) -> None:
    source = _SOURCE.replace("send()", invocation).replace("send.assert_called_once()", assertion)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == source + f"    {added}\n"
    assert not REGISTRY[_RULE]().check(_PATH, fixed)
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed
    assert fix_source(_PATH, source, rule_ids=[]) == source
    for candidate in (source, fixed):
        path = tmp_path / "test_delivery.py"
        path.write_text(candidate + "\nimport asyncio\nasyncio.run(test_delivery())\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("send = AsyncMock()", "send = AsyncMock(return_value='done')"),
        _SOURCE.replace("await send()", "await deliver(send)"),
        _SOURCE.replace("await send()", "pending = send()\n    pending.close()"),
        _SOURCE.replace("await send()", "await send('item')"),
        _SOURCE.replace("send.assert_called_once()", "send.assert_called_once_with('other')"),
        _SOURCE.replace("await send()", "await send(*values)"),
        _SOURCE.replace("async def test_delivery():", "async def test_delivery(fixture):"),
        _SOURCE.replace("async def test_delivery():", "async def test_delivery[T]():"),
        _SOURCE.replace("async def test_delivery():", "@decorate\nasync def test_delivery():"),
        _SOURCE.replace("send.assert_called_once()", "send.assert_called_once()  # retain assertion rationale"),
        _SOURCE.replace("await send()", "await send()\n    effect()"),
        "from unittest.mock import AsyncMock\nfrom sys import setprofile\n" + _SOURCE.split("\n", 1)[1],
        "from unittest.mock import AsyncMock, patch\n" + _SOURCE.split("\n", 1)[1],
        "from unittest.mock import AsyncMock\nAsyncMock.assert_awaited_once = fail\n" + _SOURCE.split("\n", 1)[1],
    ],
)
def test_mock_await_autofix_preserves_unproven_test_oracles_and_provider_contracts(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("trailing", [True, False])
def test_mock_await_autofix_preserves_line_endings_and_converges(newline: str, trailing: bool) -> None:
    source = _SOURCE.replace("\n", newline)
    if not trailing:
        source = source.removesuffix(newline)
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == source + ("" if trailing else newline) + "    send.assert_awaited_once()" + newline
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed


def test_mock_await_autofix_respects_native_suppression() -> None:
    source = _SOURCE.replace(
        "send.assert_called_once()", "send.assert_called_once()  # sarj-noqa: SARJ456 -- explicit scheduling contract"
    )
    assert not REGISTRY[_RULE]().check(_PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
