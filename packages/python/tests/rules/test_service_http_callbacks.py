from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._nominal_project import NominalProjectFacts
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_explicit_service_contract import RequireExplicitServiceContract


if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectFixture:
    rule: RequireExplicitServiceContract
    path: "Path"


_PROVIDER = """\
import httpx

class Gateway:
    _transport: httpx.AsyncClient | None = None

    def connection(self) -> httpx.AsyncClient:
        if self._transport is None:
            self._transport = httpx.AsyncClient()
        return self._transport

    async def __aenter__(self):
        self.connection()
        return self

    async def __aexit__(self, *args):
        await self.connection().aclose()
"""
_ADAPTER = """\
from __future__ import annotations
from typing import TYPE_CHECKING
from example_sdk import Gateway

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

class Adapter:
    async def run(self) -> str:
        return await self._send(lambda resource: fetch(resource))

    async def _send(self, call: Callable[[Gateway], Awaitable[str]]) -> str:
        client = Gateway()
        async with client:
            return await call(client)
"""
_CALLBACK_CASES = [
    ("namespace-sdk-callback", _ADAPTER, _PROVIDER, 1),
    ("generated-sdk-source", _ADAPTER, f"# @generated\n{_PROVIDER}", 1),
    ("unavailable-sdk-source", _ADAPTER, "", 0),
    (
        "conditional-resource-construction",
        _ADAPTER.replace("        client = Gateway()", "        if enabled:\n            client = Gateway()"),
        _PROVIDER,
        0,
    ),
    (
        "escaped-decorator-import",
        _ADAPTER,
        _PROVIDER.replace("import httpx", "import httpx\nimport attrs\nconfigure(attrs)").replace(
            "class Gateway:", "@attrs.define\nclass Gateway:"
        ),
        0,
    ),
    ("rewritten-provider-method", _ADAPTER, f"{_PROVIDER}\nGateway.connection = replacement\n", 0),
    (
        "inline-resource-entry",
        _ADAPTER.replace(
            "        client = Gateway()\n        async with client:", "        async with Gateway() as client:"
        ),
        _PROVIDER,
        1,
    ),
    ("unstarted-async-factory", _ADAPTER, _PROVIDER.replace("    def connection", "    async def connection"), 0),
    (
        "awaited-async-factory",
        _ADAPTER,
        _PROVIDER.replace("    def connection", "    async def connection")
        .replace("        self.connection()\n", "        await self.connection()\n")
        .replace("await self.connection().aclose()", "await (await self.connection()).aclose()"),
        1,
    ),
    (
        "escaped-native-import",
        _ADAPTER,
        _PROVIDER.replace(
            "import httpx", "import httpx\ndef configure(api):\n    api.AsyncClient = object\nconfigure(httpx)"
        ),
        0,
    ),
    (
        "escaped-native-constructor",
        _ADAPTER,
        _PROVIDER.replace("import httpx", "import httpx\nconfigure(httpx.AsyncClient)"),
        0,
    ),
    (
        "rewritten-resource-entry",
        _ADAPTER,
        _PROVIDER.replace("    async def __aenter__", "    @rewrite\n    async def __aenter__"),
        0,
    ),
    (
        "short-circuit-factory",
        _ADAPTER,
        _PROVIDER.replace("        self.connection()\n", "        self.value = False and self.connection()\n"),
        0,
    ),
    (
        "lazy-comprehension-factory",
        _ADAPTER,
        _PROVIDER.replace("        self.connection()\n", "        self.value = [self.connection() for _ in []]\n"),
        0,
    ),
    (
        "deferred-factory",
        _ADAPTER,
        _PROVIDER.replace("        self.connection()\n", "        self.value = lambda: self.connection()\n"),
        0,
    ),
    (
        "conditional-expression-factory",
        _ADAPTER,
        _PROVIDER.replace(
            "        self.connection()\n", "        self.value = self.connection() if enabled else None\n"
        ),
        0,
    ),
    (
        "quoted-callback-annotation",
        _ADAPTER.replace("call: Callable[[Gateway], Awaitable[str]]", "call: 'Callable[[Gateway], Awaitable[str]]'"),
        _PROVIDER,
        1,
    ),
    (
        "aliased-sdk-class",
        _ADAPTER.replace("import Gateway", "import Gateway as Transport")
        .replace("[[Gateway]", "[[Transport]")
        .replace("client = Gateway()", "client = Transport()"),
        _PROVIDER,
        1,
    ),
    (
        "aliased-callable",
        _ADAPTER.replace("Awaitable, Callable", "Awaitable, Callable as Sender").replace("Callable[[", "Sender[["),
        _PROVIDER,
        1,
    ),
    (
        "attrs-wrapper",
        _ADAPTER,
        _PROVIDER.replace("import httpx", "import httpx\nfrom attrs import define").replace(
            "class Gateway:", "@define\nclass Gateway:"
        ),
        1,
    ),
    (
        "direct-factory-return",
        _ADAPTER,
        _PROVIDER.replace(
            "        if self._transport is None:\n            self._transport = httpx.AsyncClient()\n        return self._transport",
            "        return httpx.AsyncClient()",
        ),
        1,
    ),
    ("untyped-callback", _ADAPTER.replace("call: Callable[[Gateway], Awaitable[str]]", "call"), _PROVIDER, 0),
    (
        "noncanonical-callable",
        _ADAPTER.replace("from collections.abc import Awaitable, Callable", "from external import Awaitable, Callable"),
        _PROVIDER,
        0,
    ),
    ("value-callback-type", _ADAPTER.replace("[[Gateway]", "[[str]"), _PROVIDER, 0),
    (
        "constructor-shadow",
        _ADAPTER.replace("async def _send(self, call:", "async def _send(self, Gateway, call:"),
        _PROVIDER,
        0,
    ),
    ("unknown-factory", _ADAPTER.replace("client = Gateway()", "client = make_client()"), _PROVIDER, 0),
    (
        "client-reassignment",
        _ADAPTER.replace("async with client:", "client = unknown\n        async with client:"),
        _PROVIDER,
        0,
    ),
    (
        "client-mutation",
        _ADAPTER.replace("async with client:", "client.connection = replacement\n        async with client:"),
        _PROVIDER,
        0,
    ),
    (
        "client-escape",
        _ADAPTER.replace("async with client:", "external(client)\n        async with client:"),
        _PROVIDER,
        0,
    ),
    (
        "callback-reassignment",
        _ADAPTER.replace("client = Gateway()", "call = unknown\n        client = Gateway()"),
        _PROVIDER,
        0,
    ),
    ("construct-only", _ADAPTER.replace("return await call(client)", "return 'local'"), _PROVIDER, 0),
    ("close-only", _ADAPTER.replace("return await call(client)", "return await client.aclose()"), _PROVIDER, 0),
    (
        "no-resource-entry",
        _ADAPTER.replace(
            "        async with client:\n            return await call(client)", "        return await call(client)"
        ),
        _PROVIDER,
        0,
    ),
    ("dormant-http-factory", _ADAPTER, _PROVIDER.replace("        self.connection()\n", ""), 0),
    (
        "factory-after-return",
        _ADAPTER,
        _PROVIDER.replace(
            "        self.connection()\n        return self", "        return self\n        self.connection()"
        ),
        0,
    ),
    (
        "conditional-entry",
        _ADAPTER,
        _PROVIDER.replace("        self.connection()\n", "        if enabled:\n            self.connection()\n"),
        0,
    ),
    (
        "native-factory-rebound",
        _ADAPTER,
        _PROVIDER.replace("import httpx", "import httpx\nhttpx.AsyncClient = replacement"),
        0,
    ),
    (
        "unknown-provider-factory",
        _ADAPTER,
        _PROVIDER.replace("self._transport = httpx.AsyncClient()", "self._transport = make_client()"),
        0,
    ),
    (
        "wrong-return-type",
        _ADAPTER,
        _PROVIDER.replace("def connection(self) -> httpx.AsyncClient:", "def connection(self) -> object:"),
        0,
    ),
    ("wrong-return-value", _ADAPTER, _PROVIDER.replace("return self._transport", "return self._other"), 0),
    ("unknown-provider-decorator", _ADAPTER, _PROVIDER.replace("class Gateway:", "@rewrite\nclass Gateway:"), 0),
    ("unknown-provider-base", _ADAPTER, _PROVIDER.replace("class Gateway:", "class Gateway(Unknown):"), 0),
    (
        "unknown-provider-metaclass",
        _ADAPTER,
        _PROVIDER.replace("class Gateway:", "class Gateway(metaclass=Unknown):"),
        0,
    ),
    (
        "factory-method-decorator",
        _ADAPTER,
        _PROVIDER.replace("    def connection", "    @rewrite\n    def connection"),
        0,
    ),
]


def _project(
    tmp_path: Path,
    source: str,
    provider: str,
    *,
    exports: str = "from .client import Gateway\n",
    dependencies: str = '["example-sdk"]',
) -> ProjectFixture:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="example-workspace"\nversion="0.1.0"\n[tool.uv.workspace]\nmembers=["consumer","sdk"]\n'
    )
    consumer = project / "consumer"
    sdk = project / "sdk"
    consumer.mkdir()
    sdk.mkdir()
    (consumer / "pyproject.toml").write_text(
        f'[project]\nname="example-consumer"\nversion="0.1.0"\ndependencies={dependencies}\n'
    )
    (sdk / "pyproject.toml").write_text('[project]\nname="example-sdk"\nversion="0.1.0"\n')
    path = consumer / "example_app" / "adapter.py"
    files = {
        path: source,
        sdk / "example_sdk" / "client.py": provider,
        sdk / "example_sdk" / "other.py": provider,
        sdk / "example_sdk" / "__init__.py": exports,
    }
    for filename, text in files.items():
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text(text)
    rule = RequireExplicitServiceContract()
    rule.prepare(ProjectIndexSet.build(list(files), files))
    return ProjectFixture(rule, path)


@pytest.mark.parametrize(
    ("case", "source", "provider", "count"), _CALLBACK_CASES, ids=[case[0] for case in _CALLBACK_CASES]
)
def test_source_proven_http_callback_boundaries(
    tmp_path: Path, case: str, source: str, provider: str, count: int
) -> None:
    project = _project(tmp_path, source, provider)
    findings = project.rule.check(project.path, source)
    assert len(findings) == count, case
    assert all(finding.severity is Severity.ERROR for finding in findings)


@pytest.mark.parametrize(
    "export",
    [
        "from .client import Gateway\nGateway = replacement\n",
        "if enabled:\n    from .client import Gateway\n",
        "from .client import Gateway\nfrom .other import Gateway\n",
    ],
)
def test_rebound_or_conditional_sdk_exports_abstain(tmp_path: Path, export: str) -> None:
    project = _project(tmp_path, _ADAPTER, _PROVIDER, exports=export)
    assert project.rule.check(project.path, _ADAPTER) == []


def test_undeclared_sdk_distribution_abstains(tmp_path: Path) -> None:
    project = _project(tmp_path, _ADAPTER, f"# @generated\n{_PROVIDER}", dependencies="[]")
    assert project.rule.check(project.path, _ADAPTER) == []


def test_generated_dependency_ownership_preserves_nominal_source_exclusion(tmp_path: Path) -> None:
    project = _project(tmp_path, _ADAPTER, f"# @generated\n{_PROVIDER}")
    provider = tmp_path / "project/sdk/example_sdk/client.py"
    ownership = NominalProjectFacts()
    first_party = FirstPartyFacts()
    assert ownership.owns_source(project.path, provider, first_party)
    assert "example_sdk.client" not in ownership.sources(project.path, first_party)
    unowned = tmp_path / "unowned.py"
    unowned.write_text(_PROVIDER)
    assert not ownership.owns_source(project.path, unowned, first_party)


def test_same_distribution_generated_resource_is_owned(tmp_path: Path) -> None:
    source = _ADAPTER.replace("from example_sdk import Gateway", "from example_app.generated_client import Gateway")
    project = _project(tmp_path, source, "")
    provider = project.path.with_name("generated_client.py")
    provider.write_text(f"# @generated\n{_PROVIDER}")
    project.rule.prepare(ProjectIndexSet.build([project.path], {project.path: source}))
    assert len(project.rule.check(project.path, source)) == 1
    ownership = NominalProjectFacts()
    first_party = FirstPartyFacts()
    assert ownership.owns_source(project.path, provider, first_party)
    assert "example_app.generated_client" not in ownership.sources(project.path, first_party)


@pytest.mark.parametrize(("operations", "count"), [("run", 0), ("other", 1)])
def test_declared_contract_must_cover_callback_operation(tmp_path: Path, operations: str, count: int) -> None:
    source = _ADAPTER.replace(
        "class Adapter:",
        f"from abc import ABC, abstractmethod\nclass Contract(ABC):\n    @abstractmethod\n    async def {operations}(self) -> str: ...\nclass Adapter(Contract):",
    )
    project = _project(tmp_path, source, _PROVIDER)
    assert len(project.rule.check(project.path, source)) == count


@pytest.mark.parametrize(("operations", "count"), [("run", 1), ("run,second", 0)])
def test_contract_covers_each_public_callback_operation(tmp_path: Path, operations: str, count: int) -> None:
    source = _ADAPTER.replace(
        "    async def _send",
        "    async def second(self) -> str:\n        return await self._send(lambda resource: fetch(resource))\n\n    async def _send",
    )
    methods = "\n".join(
        f"    @abstractmethod\n    async def {operation}(self) -> str: ..." for operation in operations.split(",")
    )
    source = source.replace(
        "class Adapter:",
        f"from abc import ABC, abstractmethod\nclass Contract(ABC):\n{methods}\nclass Adapter(Contract):",
    )
    project = _project(tmp_path, source, _PROVIDER)
    assert len(project.rule.check(project.path, source)) == count
