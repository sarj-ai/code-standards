from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.httpx_client_requires_timeout import (
    HttpxClientRequiresTimeout,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


PROD_PATH = "python/webserver/webserver/services/crm_sync.py"


def _check(source: str, path: str = PROD_PATH) -> list[Diagnostic]:
    return HttpxClientRequiresTimeout().check(Path(path), source)


# --------------------------------------------------------------------------- #
# Positive: clients and convenience calls without timeout=.                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "httpx.Client()",
        "httpx.AsyncClient()",
        "httpx.AsyncClient(base_url=url)",
        "httpx.Client(headers={'x': 'y'}, verify=False)",
        "httpx.get(url)",
        "httpx.post(url, json=payload)",
        "httpx.put(url, content=b'x')",
        "httpx.patch(url)",
        "httpx.delete(url)",
        "httpx.request('GET', url)",
    ],
)
def test_flags_missing_timeout(call: str):
    src = f"import httpx\n\nclient = {call}\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ033"
    assert "timeout" in diags[0].message


def test_flags_client_in_async_context_manager():
    src = """
import httpx

async def sync():
    async with httpx.AsyncClient(base_url=url) as client:
        await client.get("/x")
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_message_names_the_callee():
    diags = _check("import httpx\nc = httpx.AsyncClient()\n")
    assert "httpx.AsyncClient" in diags[0].message


# --------------------------------------------------------------------------- #
# Negative: explicit timeout of any shape.                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "httpx.Client(timeout=10)",
        "httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))",
        "httpx.AsyncClient(base_url=url, timeout=TIMEOUT)",
        "httpx.get(url, timeout=30)",
        "httpx.post(url, json=p, timeout=None)",
        "httpx.request('GET', url, timeout=budget)",
    ],
)
def test_allows_explicit_timeout(call: str):
    src = f"import httpx\n\nclient = {call}\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: exempting kwargs — spread, transport, mounts.                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "httpx.AsyncClient(**kwargs)",
        "httpx.Client(base_url=url, **client_options)",
        "httpx.get(url, **request_kwargs)",
        "httpx.AsyncClient(transport=transport)",
        "httpx.Client(transport=httpx.HTTPTransport(retries=3))",
        "httpx.AsyncClient(mounts={'https://': transport})",
    ],
)
def test_allows_exempting_kwargs(call: str):
    src = f"import httpx\n\nclient = {call}\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: receivers that are not the bare httpx module.                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        "client.get(url)",
        "self.client.post(url, json=p)",
        "session.request('GET', url)",
        "requests.get(url)",
        "aiohttp.request('GET', url)",
        "AsyncClient()",
        "Client()",
        "httpx.stream('GET', url)",
        "httpx.head(url)",
        "mod.httpx.get(url)",
    ],
)
def test_allows_other_receivers_and_callees(call: str):
    src = f"import httpx\n\nresult = {call}\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: test files are exempt.                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_crm.py",
        "test_oauth.py",
        "webserver/tests/webserver/test_identity_verifier.py",
        "conftest.py",
        "tests/conftest.py",
        "integration/tests/helpers.py",
    ],
)
def test_skips_test_paths(path: str):
    src = "import httpx\nc = httpx.AsyncClient()\n"
    assert _check(src, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "webserver/main.py",
        "integration/integration/zoho.py",
        "scripts/logto_provision.py",
        "a/contest.py",
    ],
)
def test_fires_in_non_test_paths(path: str):
    src = "import httpx\nc = httpx.AsyncClient()\n"
    assert len(_check(src, path)) == 1


# --------------------------------------------------------------------------- #
# Counts, ordering, edge cases.                                                #
# --------------------------------------------------------------------------- #


def test_multiple_hits_sorted():
    src = """
import httpx

a = httpx.Client()

async def go():
    async with httpx.AsyncClient() as c:
        r = httpx.get(url)
"""
    diags = _check(src)
    assert len(diags) == 3
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []
