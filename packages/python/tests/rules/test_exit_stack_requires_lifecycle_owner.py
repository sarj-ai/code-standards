from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.exit_stack_requires_lifecycle_owner import ExitStackRequiresLifecycleOwner


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_RULE = ExitStackRequiresLifecycleOwner.id

_PR_SNIPPET = """\
import asyncio
from contextlib import AsyncExitStack


class Service:
    async def _prepare_many(self, renders):
        uploads = []
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(lambda: self._discard(uploads))
            for render in renders:
                uploads.append(await self._prepare(render))
            cleanup.pop_all()
            return uploads
"""

_MATCHES = {
    "service-pop-all": _PR_SNIPPET,
    "plain-function": "from contextlib import ExitStack\ndef run(paths):\n    with ExitStack() as stack:\n        return [stack.enter_context(open(p)) for p in paths]\n",
    "aliased-import": "from contextlib import AsyncExitStack as Stack\nasync def run():\n    async with Stack() as stack:\n        await stack.enter_async_context(client())\n",
    "module-import": "import contextlib\nasync def run():\n    async with contextlib.AsyncExitStack() as stack:\n        await stack.enter_async_context(client())\n",
    "module-alias": "import contextlib as cl\ndef run():\n    stack = cl.ExitStack()\n    stack.close()\n",
    "nested-def-in-lifespan": (
        "from contextlib import AsyncExitStack, asynccontextmanager\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    async def build():\n"
        "        async with AsyncExitStack() as stack:\n"
        "            return await stack.enter_async_context(client())\n"
        "    app.state.client = await build()\n"
        "    yield\n"
    ),
    "init-without-release": (
        "from contextlib import AsyncExitStack\n"
        "class Holder:\n"
        "    def __init__(self):\n"
        "        self._stack = AsyncExitStack()\n"
    ),
    "release-but-other-method": (
        "from contextlib import AsyncExitStack\n"
        "class Holder:\n"
        "    async def open(self):\n"
        "        self._stack = AsyncExitStack()\n"
        "    async def aclose(self):\n"
        "        await self._stack.aclose()\n"
    ),
    "uncalled-function-beside-main": (
        "import asyncio\nfrom contextlib import AsyncExitStack\n"
        "async def helper():\n    async with AsyncExitStack():\n        pass\n"
        "async def main():\n    pass\n"
        "if __name__ == '__main__':\n    asyncio.run(main())\n"
    ),
}

_NO_MATCHES = {
    "asynccontextmanager": (
        "from contextlib import AsyncExitStack, asynccontextmanager\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    async with AsyncExitStack() as stack:\n"
        "        app.state.client = await stack.enter_async_context(client())\n"
        "        yield\n"
    ),
    "yield-dependency": (
        "from contextlib import AsyncExitStack\n"
        "class Router:\n"
        "    async def client_for_request(self, request):\n"
        "        resources = AsyncExitStack()\n"
        "        try:\n"
        "            yield await resources.enter_async_context(client(request))\n"
        "        finally:\n"
        "            await resources.aclose()\n"
    ),
    "main-guard-entry": (
        "from contextlib import ExitStack\n"
        "def main():\n    with ExitStack() as stack:\n        stack.callback(print)\n"
        "if __name__ == '__main__':\n    main()\n"
    ),
    "asyncio-run-entry": (
        "import asyncio\nfrom contextlib import AsyncExitStack\n"
        "async def collect():\n    async with AsyncExitStack():\n        pass\n"
        "def cli():\n    return asyncio.run(collect())\n"
    ),
    "reachable-from-main": (
        "import asyncio\nfrom contextlib import ExitStack\n"
        "async def execute(op):\n    with ExitStack():\n        pass\n"
        "async def main():\n    await execute('test')\n"
        "if __name__ == '__main__':\n    asyncio.run(main())\n"
    ),
    "resource-owner-init": (
        "from contextlib import AsyncExitStack\n"
        "class Room:\n"
        "    def __init__(self):\n"
        "        self._media = AsyncExitStack()\n"
        "    async def aclose(self):\n"
        "        await self._media.aclose()\n"
    ),
    "resource-owner-aenter": (
        "from contextlib import AsyncExitStack\n"
        "class Room:\n"
        "    async def __aenter__(self):\n"
        "        self._stack = AsyncExitStack()\n"
        "        return self\n"
        "    async def __aexit__(self, *exc):\n"
        "        await self._stack.aclose()\n"
    ),
    "module-level": "from contextlib import ExitStack\nSTACK = ExitStack()\n",
    "unproven-stack": "async def run(AsyncExitStack):\n    async with AsyncExitStack():\n        pass\n",
    "other-library": "from mylib import AsyncExitStack\nasync def run():\n    async with AsyncExitStack():\n        pass\n",
    "suppressed": "from contextlib import ExitStack\ndef run():\n    with ExitStack():  # sarj-noqa: SARJ588 -- dynamic plugin set\n        pass\n",
    "wildcard": "from contextlib import *\nfrom contextlib import ExitStack\ndef run():\n    with ExitStack():\n        pass\n",
}


def _analyze(tmp_path: Path, source: str, name: str = "app/service.py") -> list[Diagnostic]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return analyze([_RULE], [path], root=tmp_path)


def test_documented_examples() -> None:
    verify_native_rule(ExitStackRequiresLifecycleOwner, analyze)


@pytest.mark.parametrize("source", list(_MATCHES.values()), ids=list(_MATCHES))
def test_reports_stack_outside_lifecycle_owner(tmp_path: Path, source: str) -> None:
    diagnostics = _analyze(tmp_path, source)

    assert [(item.code, item.severity) for item in diagnostics] == [("SARJ588", Severity.WARNING)]


@pytest.mark.parametrize("source", list(_NO_MATCHES.values()), ids=list(_NO_MATCHES))
def test_accepts_lifecycle_owners_and_unproven_stacks(tmp_path: Path, source: str) -> None:
    assert _analyze(tmp_path, source) == []


def test_pop_all_guard_recommends_returning_a_context_manager(tmp_path: Path) -> None:
    (diagnostic,) = _analyze(tmp_path, _PR_SNIPPET)

    assert diagnostic.line == 8
    assert "`_prepare_many`" in diagnostic.message
    assert "instead of a `pop_all()` guard" in diagnostic.message


def test_plain_stack_message_omits_pop_all_advice(tmp_path: Path) -> None:
    (diagnostic,) = _analyze(tmp_path, _MATCHES["plain-function"])

    assert "pop_all" not in diagnostic.message
    assert "composition root" in diagnostic.message


@pytest.mark.parametrize("name", ["tests/test_service.py", "app/tests/fakes/clients.py", "app/conftest.py"])
def test_skips_tests_and_test_support(tmp_path: Path, name: str) -> None:
    assert _analyze(tmp_path, _PR_SNIPPET, name) == []
