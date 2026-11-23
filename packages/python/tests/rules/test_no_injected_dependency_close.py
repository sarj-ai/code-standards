from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_injected_dependency_close import NoInjectedDependencyClose


if TYPE_CHECKING:
    from pathlib import Path


_INIT = (
    "from contextlib import AsyncExitStack\n\n\n"
    "class Synthesizer:\n"
    "    def __init__(self, *, openai_client: AsyncOpenAI, omni_client: AsyncOpenAI) -> None:\n"
    "        self._openai_client = openai_client\n"
    "        self._omni_client = omni_client\n\n"
)
_STACK = (
    _INIT
    + "    async def aclose(self) -> None:\n"
    + "        async with AsyncExitStack() as cleanup:\n"
    + "            cleanup.push_async_callback(self._openai_client.close)\n"
    + "            cleanup.push_async_callback(self._omni_client.close)\n"
)
_DIRECT = _INIT + "    async def aclose(self) -> None:\n        await self._openai_client.close()\n"


def _findings(tmp_path: Path, source: str, name: str = "synthesizer.py") -> list[tuple[str, int, Severity]]:
    path = tmp_path / "app" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return [
        (finding.code, finding.line, finding.severity) for finding in analyze(["no-injected-dependency-close"], [path])
    ]


def test_documented_examples() -> None:
    verify_native_rule(NoInjectedDependencyClose, analyze)


def test_each_registered_injected_close_is_reported(tmp_path: Path) -> None:
    assert _findings(tmp_path, _STACK) == [("SARJ599", 11, Severity.WARNING), ("SARJ599", 12, Severity.WARNING)]


@pytest.mark.parametrize(
    "source",
    [
        _DIRECT,
        _DIRECT.replace("await self._openai_client.close()", "await self._openai_client.aclose()"),
        _DIRECT.replace("async def aclose", "def close").replace("await ", ""),
        _DIRECT.replace("async def aclose(self) -> None", "async def __aexit__(self, *exc: object) -> None").replace(
            "close()", "__aexit__(*exc)"
        ),
        _DIRECT.replace("def aclose(self) -> None", "def __exit__(self, *exc: object) -> None").replace(
            "await self._openai_client.close()", "self._openai_client.shutdown(wait=True)"
        ),
        _INIT + "    def close(self) -> None:\n        stack.callback(self._openai_client.close)\n",
        _INIT + "    async def __aenter__(self) -> None:\n        self._stack.push_async_exit(self._omni_client)\n",
        _DIRECT.replace("(self, *, openai_client", "(self, openai_client"),
        _DIRECT.replace(
            "        self._openai_client = openai_client\n",
            "        self._openai_client: AsyncOpenAI = openai_client\n",
        ),
        _DIRECT.replace("(self, *", "(this, *")
        .replace("self._openai_client = ", "this._openai_client = ")
        .replace("self._omni_client = ", "this._omni_client = "),
        _DIRECT.replace(
            "        await self._openai_client.close()\n",
            "        if self._openai_client:\n            await self._openai_client.close()\n",
        ),
    ],
    ids=[
        "direct-close",
        "aclose",
        "sync-close",
        "aexit",
        "exit-shutdown",
        "callback",
        "push-async-exit",
        "positional-parameter",
        "annotated-attribute",
        "renamed-receiver",
        "guarded-close",
    ],
)
def test_injected_closes_warn(tmp_path: Path, source: str) -> None:
    assert [(code, severity) for code, _line, severity in _findings(tmp_path, source)] == [
        ("SARJ599", Severity.WARNING)
    ]


@pytest.mark.parametrize(
    "source",
    [
        _INIT.replace("openai_client\n", "AsyncOpenAI()\n")
        + "    async def aclose(self) -> None:\n        await self._openai_client.close()\n",
        _INIT.replace("= openai_client\n", "= openai_client or AsyncOpenAI()\n")
        + "    async def aclose(self) -> None:\n        await self._openai_client.close()\n",
        _DIRECT.replace("async def aclose", "async def stop"),
        _DIRECT.replace("await self._openai_client.close()", "await self._openai_client.flush()"),
        _DIRECT.replace("await self._openai_client.close()", "await self._owned.close()"),
        _DIRECT.replace("await self._openai_client.close()", "await self.close_session()"),
        _DIRECT + "\n    def rebind(self, client: AsyncOpenAI) -> None:\n        self._openai_client = client\n",
        _DIRECT
        + "\n    @classmethod\n    def create(cls) -> 'Synthesizer':\n"
        + "        return cls(openai_client=AsyncOpenAI(), omni_client=AsyncOpenAI())\n",
        _INIT
        + "    async def __aenter__(self) -> None:\n        await self._stack.enter_async_context(self._omni_client)\n",
        _INIT + "    async def run(self) -> None:\n        await self._openai_client.close()\n",
        _INIT.replace(
            "        self._openai_client = openai_client\n",
            "        if openai_client:\n            self._openai_client = openai_client\n",
        )
        + "    async def aclose(self) -> None:\n        await self._openai_client.close()\n",
        _INIT
        + "    async def aclose(self) -> None:\n        client = self._openai_client\n        await client.close()\n",
        _INIT + "    @staticmethod\n    async def aclose(self) -> None:\n        await self._openai_client.close()\n",
        _INIT
        + "    async def aclose(self) -> None:\n        async def later() -> None:\n"
        + "            await self._openai_client.close()\n        await later()\n",
        _DIRECT.replace(
            "await self._openai_client.close()",
            "await self._openai_client.close()  # sarj-noqa: SARJ599 -- ownership transferred by contract",
        ),
    ],
    ids=[
        "constructed",
        "fallback-construction",
        "non-cleanup-method",
        "non-closing-call",
        "other-attribute",
        "helper-method",
        "reassigned",
        "classmethod-factory",
        "entered-context",
        "close-outside-cleanup",
        "conditional-assignment",
        "local-alias",
        "staticmethod",
        "nested-function",
        "suppressed",
    ],
)
def test_owned_or_unproven_resources_pass(tmp_path: Path, source: str) -> None:
    assert _findings(tmp_path, source) == []


@pytest.mark.parametrize("name", ["test_synthesizer.py", "conftest.py"])
def test_tests_are_excluded(tmp_path: Path, name: str) -> None:
    assert _findings(tmp_path, _DIRECT, name) == []


def test_generated_sources_abstain(tmp_path: Path) -> None:
    assert _findings(tmp_path, "# Code generated by tool. DO NOT EDIT.\n" + _DIRECT) == []
