from pathlib import Path
import textwrap

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_explicit_service_contract import RequireExplicitServiceContract


def test_documented_examples() -> None:
    verify_native_rule(RequireExplicitServiceContract, analyze)


def _check(source: str, path: str = "app/service.py") -> list[str]:
    return [finding.code for finding in RequireExplicitServiceContract().check(Path(path), textwrap.dedent(source))]


_DISPATCHER = """\
import asyncio
from collections.abc import Callable
from concurrent.futures import Executor

class Batcher:
    def __init__(self, transform: Callable[[list[str]], object], executor: Executor) -> None:
        self._transform = transform
        self._executor = executor

    async def run(self, texts: list[str]) -> object:
        return await self._process(texts)

    async def _process(self, texts: list[str]) -> object:
        return await asyncio.get_running_loop().run_in_executor(self._executor, self._transform, texts)
"""

_DISPATCH_CASES = (
    EvaluationCase("retained-callback-dispatch", Language.PYTHON, _DISPATCHER, ExpectedOutcome.MATCH),
    EvaluationCase(
        "named-service-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("class Batcher:", "class BatchService:"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "queue-role-without-service-suffix",
        Language.PYTHON,
        _DISPATCHER.replace("class Batcher:", "class WorkQueue:"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "aliased-asyncio-module",
        Language.PYTHON,
        _DISPATCHER.replace("import asyncio", "import asyncio as tasks").replace("asyncio.", "tasks."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "aliased-loop-factory",
        Language.PYTHON,
        _DISPATCHER.replace("import asyncio", "from asyncio import get_running_loop as current_loop").replace(
            "asyncio.get_running_loop()", "current_loop()"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "event-loop-factory",
        Language.PYTHON,
        _DISPATCHER.replace("get_running_loop", "get_event_loop"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "callback-keyword",
        Language.PYTHON,
        _DISPATCHER.replace("self._executor, self._transform, texts", "executor=self._executor, func=self._transform"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "retained-bound-method",
        Language.PYTHON,
        _DISPATCHER.replace("Callable[[list[str]], object]", "Transformer").replace(
            "self._executor, self._transform, texts", "self._executor, self._transform.encode, texts"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "declared-abc",
        Language.PYTHON,
        _DISPATCHER.replace(
            "class Batcher:",
            "from abc import ABC, abstractmethod\n"
            "class BatchOperations(ABC):\n"
            "    @abstractmethod\n"
            "    async def run(self, texts: list[str]) -> object: ...\n"
            "\nclass Batcher(BatchOperations):",
        ),
    ),
    EvaluationCase(
        "declared-protocol",
        Language.PYTHON,
        _DISPATCHER.replace(
            "class Batcher:",
            "from typing import Protocol as Contract\n"
            "class BatchOperations(Contract):\n"
            "    async def run(self, texts: list[str]) -> object: ...\n"
            "\nclass Batcher(BatchOperations):",
        ),
    ),
    EvaluationCase(
        "custom-loop-factory",
        Language.PYTHON,
        _DISPATCHER.replace("import asyncio", "import custom_runtime as asyncio"),
    ),
    EvaluationCase(
        "shadowed-asyncio-module",
        Language.PYTHON,
        _DISPATCHER.replace("async def _process(self, texts:", "async def _process(self, asyncio, texts:"),
    ),
    EvaluationCase(
        "callback-only-stored",
        Language.PYTHON,
        _DISPATCHER.replace(
            "await asyncio.get_running_loop().run_in_executor(self._executor, self._transform, texts)",
            "self._transform",
        ),
    ),
    EvaluationCase(
        "callback-is-not-executor",
        Language.PYTHON,
        _DISPATCHER.replace("self._executor, self._transform, texts", "self._transform, unrelated, texts"),
    ),
    EvaluationCase(
        "unknown-callback-position",
        Language.PYTHON,
        _DISPATCHER.replace("self._executor, self._transform, texts", "*arguments, self._transform, texts"),
    ),
    EvaluationCase(
        "callback-replaced",
        Language.PYTHON,
        _DISPATCHER.replace(
            "        return await asyncio", "        self._transform = replacement\n        return await asyncio"
        ),
    ),
    EvaluationCase(
        "unreachable-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("        return await asyncio", "        return None\n        return await asyncio"),
    ),
    EvaluationCase(
        "deferred-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("return await asyncio", "return lambda: asyncio"),
    ),
    EvaluationCase(
        "suppressed-boundary",
        Language.PYTHON,
        _DISPATCHER.replace("class Batcher:", "class Batcher:  # sarj-noqa: SARJ465 -- framework supplies contract"),
    ),
    EvaluationCase("generated-boundary", Language.PYTHON, "# @generated\n" + _DISPATCHER),
    EvaluationCase("malformed-boundary", Language.PYTHON, "class Batcher(:"),
    EvaluationCase(
        "local-loop-binding",
        Language.PYTHON,
        _DISPATCHER.replace(
            "        return await asyncio.get_running_loop().run_in_executor",
            "        loop = asyncio.get_running_loop()\n        return await loop.run_in_executor",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "thread-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace(
            "asyncio.get_running_loop().run_in_executor(self._executor, self._transform, texts)",
            "asyncio.to_thread(self._transform, texts)",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "aliased-thread-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("import asyncio", "from asyncio import to_thread as dispatch").replace(
            "asyncio.get_running_loop().run_in_executor(self._executor, self._transform, texts)",
            "dispatch(self._transform, texts)",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "private-only-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("async def run(", "async def _run("),
    ),
    EvaluationCase(
        "dead-conditional-dispatch",
        Language.PYTHON,
        _DISPATCHER.replace("        return await asyncio", "        if False:\n            return await asyncio"),
    ),
    EvaluationCase(
        "opaque-dispatch-wrapper",
        Language.PYTHON,
        _DISPATCHER.replace("asyncio.get_running_loop().run_in_executor", "wrapper"),
    ),
    EvaluationCase(
        "missing-executor-argument",
        Language.PYTHON,
        _DISPATCHER.replace("self._executor, self._transform, texts", "func=self._transform"),
    ),
    EvaluationCase(
        "partial-queue-contract",
        Language.PYTHON,
        _DISPATCHER.replace(
            "class Batcher:",
            "from typing import Protocol\n"
            "class BatchOperations(Protocol):\n"
            "    async def stop(self) -> None: ...\n"
            "\nclass Batcher(BatchOperations):",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "queue-name-without-dispatch",
        Language.PYTHON,
        "class WorkQueue:\n"
        "    def __init__(self, items: list[str]) -> None:\n"
        "        self._items = items\n"
        "    def take(self) -> str:\n"
        "        return self._items.pop()\n",
    ),
)


_HTTP_ADAPTER = """\
import httpx

class RemoteClient:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = base_url
        self._transport = transport

    async def fetch(self) -> object:
        return await self._request()

    async def publish(self) -> object:
        return await self._request()

    async def _request(self) -> object:
        async with httpx.AsyncClient(base_url=self._base_url, transport=self._transport) as client:
            return await client.request("GET", "/items")
"""

_HTTP_CASES = (
    EvaluationCase("http-adapter-private-helper", Language.PYTHON, _HTTP_ADAPTER, ExpectedOutcome.MATCH),
    EvaluationCase(
        "http-adapter-arbitrary-name",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("class RemoteClient:", "class Directory:"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-module-alias",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import httpx as transport_api").replace("httpx.", "transport_api."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-constructor-alias",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import httpx\nfrom httpx import AsyncClient as Connection").replace(
            "httpx.AsyncClient(", "Connection("
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-callable-local-import",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("httpx.AsyncBaseTransport | None", "object")
        .replace("import httpx\n", "")
        .replace("        async with httpx", "        import httpx\n        async with httpx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-no-constructor",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:\n"
            "        self._base_url = base_url\n"
            "        self._transport = transport\n\n",
            "",
        ).replace("base_url=self._base_url, transport=self._transport", ""),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-synchronous-client",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("async def", "def")
        .replace("async with", "with")
        .replace("await ", "")
        .replace("httpx.AsyncClient", "httpx.Client"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-local-client-assignment",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "        async with httpx.AsyncClient(base_url=self._base_url, transport=self._transport) as client:\n"
            '            return await client.request("GET", "/items")',
            "        client = httpx.AsyncClient(base_url=self._base_url, transport=self._transport)\n"
            '        return await client.request("GET", "/items")',
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-convenience-method",
        Language.PYTHON,
        _HTTP_ADAPTER.replace('client.request("GET", "/items")', 'client.get("/items")'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-multiple-context-managers",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import asyncio\nimport httpx").replace(
            "async with httpx.AsyncClient", "async with asyncio.timeout(10), httpx.AsyncClient"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-abc-contract",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "class RemoteClient:",
            "from abc import ABC, abstractmethod\n"
            "class Operations(ABC):\n"
            "    @abstractmethod\n"
            "    async def fetch(self) -> object: ...\n"
            "    @abstractmethod\n"
            "    async def publish(self) -> object: ...\n"
            "\nclass RemoteClient(Operations):",
        ),
    ),
    EvaluationCase(
        "http-protocol-contract",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "class RemoteClient:",
            "from typing import Protocol\n"
            "class Operations(Protocol):\n"
            "    async def fetch(self) -> object: ...\n"
            "    async def publish(self) -> object: ...\n"
            "\nclass RemoteClient(Operations):",
        ),
    ),
    EvaluationCase(
        "http-incomplete-contract",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "class RemoteClient:",
            "from typing import Protocol\n"
            "class Operations(Protocol):\n"
            "    async def fetch(self) -> object: ...\n"
            "\nclass RemoteClient(Operations):",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "http-unresolved-ancestry",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("class RemoteClient:", "class RemoteClient(FrameworkClient):"),
    ),
    EvaluationCase(
        "http-generated-adapter",
        Language.PYTHON,
        "# @generated\n" + _HTTP_ADAPTER,
    ),
    EvaluationCase(
        "http-adapter-suppression",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "class RemoteClient:", "class RemoteClient:  # sarj-noqa: SARJ465 -- framework supplies contract"
        ),
    ),
    EvaluationCase(
        "http-custom-module",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import custom_transport as httpx"),
    ),
    EvaluationCase(
        "http-shadowed-module",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("async def _request(self)", "async def _request(self, httpx)"),
    ),
    EvaluationCase(
        "http-replaced-module",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import httpx\nhttpx = custom_transport"),
    ),
    EvaluationCase(
        "http-replaced-client",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "            return await client", "            client = custom_client\n            return await client"
        ),
    ),
    EvaluationCase(
        "http-mutated-client-method",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "            return await client",
            "            client.request = custom_request\n            return await client",
        ),
    ),
    EvaluationCase(
        "http-client-escapes",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "            return await client", "            adapt(client)\n            return await client"
        ),
    ),
    EvaluationCase(
        "http-created-without-request",
        Language.PYTHON,
        _HTTP_ADAPTER.replace('return await client.request("GET", "/items")', "return None"),
    ),
    EvaluationCase(
        "http-cleanup-only",
        Language.PYTHON,
        _HTTP_ADAPTER.replace('client.request("GET", "/items")', "client.aclose()"),
    ),
    EvaluationCase(
        "http-unreachable-request",
        Language.PYTHON,
        _HTTP_ADAPTER.replace(
            "            return await client", "            return None\n            return await client"
        ),
    ),
    EvaluationCase(
        "http-deferred-request",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("return await client.request", "return lambda: client.request"),
    ),
    EvaluationCase(
        "http-private-operations-only",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("async def fetch(", "async def _fetch(").replace(
            "async def publish(", "async def _publish("
        ),
    ),
    EvaluationCase(
        "http-unknown-method-decorator",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("    async def _request", "    @framework_callback\n    async def _request"),
    ),
    EvaluationCase(
        "http-unknown-class-decorator",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("class RemoteClient:", "@framework_adapter\nclass RemoteClient:"),
    ),
    EvaluationCase(
        "http-mutated-native-constructor",
        Language.PYTHON,
        _HTTP_ADAPTER.replace("import httpx", "import httpx\nhttpx.AsyncClient = custom_client"),
    ),
)


@pytest.mark.parametrize("case", _HTTP_CASES, ids=tuple(case.case_id for case in _HTTP_CASES))
def test_native_http_operations_establish_a_service_boundary(case: EvaluationCase) -> None:
    expected = ["SARJ465"] if case.expected == ExpectedOutcome.MATCH else []
    assert _check(case.source, "app/remote.py") == expected


@pytest.mark.parametrize("case", _DISPATCH_CASES, ids=tuple(case.case_id for case in _DISPATCH_CASES))
def test_retained_executor_callback_establishes_a_service_boundary(case: EvaluationCase) -> None:
    expected = ["SARJ465"] if case.expected == ExpectedOutcome.MATCH else []
    assert _check(case.source, "app/batching.py") == expected


@pytest.mark.parametrize("path", ["tests/test_batching.py", "tests/fakes/batching.py", "scripts/batching.py"])
def test_executor_dispatch_preserves_non_production_exclusions(path: str) -> None:
    assert _check(_DISPATCHER, path) == []


def test_untyped_lifecycle_factory_does_not_establish_a_service_contract() -> None:
    assert (
        _check(
            "class Runner:\n"
            "    def __init__(self, *, loop_factory=None):\n"
            "        self._loop_factory = loop_factory\n"
            "    def get_loop(self):\n"
            "        return self._loop_factory()\n"
        )
        == []
    )


def test_untyped_callback_still_establishes_a_proven_dispatch_boundary() -> None:
    assert _check(_DISPATCHER.replace("transform: Callable[[list[str]], object]", "transform")) == ["SARJ465"]


def test_untyped_collaborator_methods_still_establish_a_named_service_boundary() -> None:
    assert _check(
        "class ExampleService:\n"
        "    def __init__(self, worker):\n"
        "        self.worker = worker\n"
        "    def run(self):\n"
        "        return self.worker.run()\n"
    ) == ["SARJ465"]


def test_executor_dispatch_has_one_class_diagnostic_with_nearby_contract_rules(tmp_path: Path) -> None:
    path = tmp_path / "batching.py"
    path.write_text(_DISPATCHER)
    rules = [
        "require-port-for-service",
        "require-explicit-service-contract",
        "require-public-dependency-contract",
        "require-explicit-contract-implementation",
    ]
    findings = analyze(rules, [path])
    assert [(finding.code, finding.line, finding.col) for finding in findings] == [("SARJ465", 5, 1)]
    assert analyze(rules[::-1], [path]) == findings


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
            class Service:
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                async def run(self) -> None:
                    async with self._lock:
                        await self._collaborator.run()
            """,
            ["SARJ465"],
        ),
        (
            """
            class Service:
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                async def run(self) -> None:
                    await self._helper()
                async def _helper(self) -> None:
                    await self._collaborator.run()
            """,
            ["SARJ465"],
        ),
        (
            """
            class Service:
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    if False:
                        self._collaborator.run()
            """,
            [],
        ),
        (
            """
            from typing import Protocol
            class Runner(Protocol):
                def run(self) -> None: ...
            class Service(Runner):
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
            """,
            [],
        ),
        (
            """
            from typing import Protocol
            class _Runner(Protocol):
                def run(self) -> None: ...
            class Service(_Runner):
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
            """,
            [],
        ),
        (
            """
            class Unrelated:
                def nothing(self) -> None: ...
            class Service(Unrelated):
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
            """,
            ["SARJ465"],
        ),
        (
            """
            from abc import ABC, abstractmethod
            class Runner(ABC):
                @abstractmethod
                def run(self) -> None: ...
            class Service(Runner):
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
                def stop(self) -> None:
                    self._collaborator.stop()
            """,
            ["SARJ465"],
        ),
        (
            """
            from abc import ABC, abstractmethod
            class Runner(ABC):
                @abstractmethod
                def run(self) -> None: ...
                def stop(self) -> None: ...
            class Service(Runner):
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
                def stop(self) -> None:
                    self._collaborator.stop()
            """,
            [],
        ),
        (
            """
            from dataclasses import dataclass
            @dataclass
            class Record:
                collaborator: Collaborator
                def run(self) -> None:
                    self.collaborator.run()
            """,
            [],
        ),
        (
            """
            class Service:
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    value = self._collaborator.id
            """,
            [],
        ),
        (
            """
            class Service:  # sarj-noqa: SARJ465 - framework owns this operation
                def __init__(self, collaborator: Collaborator) -> None:
                    self._collaborator = collaborator
                def run(self) -> None:
                    self._collaborator.run()
            """,
            [],
        ),
    ],
)
def test_proven_boundary_requires_a_visible_declared_contract(source: str, expected: list[str]) -> None:
    assert _check(source) == expected


def test_test_support_classes_are_left_for_the_fake_contract_rule() -> None:
    assert (
        _check(
            "class Fake:\n    def __init__(self, collaborator): self.collaborator = collaborator\n    def run(self): self.collaborator.run()\n",
            "tests/fakes/worker.py",
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
            from typing import Protocol
            class Runner(Protocol):
                def run(self) -> None: ...
            class Intermediate(Runner):
                pass
            class ExampleService(Intermediate):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="local-inherited-protocol",
        ),
        pytest.param(
            """
            from abc import ABC, abstractmethod
            class Runner(ABC):
                @abstractmethod
                def run(self) -> None: ...
            class Intermediate(Runner):
                pass
            class ExampleService(Intermediate):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="local-inherited-abc",
        ),
        pytest.param(
            """
            from typing import Protocol, TypeVar
            T = TypeVar("T")
            class Runner(Protocol[T]):
                def run(self) -> T: ...
            class ExampleService(Runner[str]):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> str:
                    return self.worker.run()
            """,
            id="generic-protocol",
        ),
        pytest.param(
            """
            from abc import ABCMeta, abstractmethod
            class Runner(metaclass=ABCMeta):
                @abstractmethod
                def run(self) -> None: ...
            class ExampleService(Runner):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="abcmeta-contract",
        ),
        pytest.param(
            """
            from abc import ABC, abstractmethod
            class ExampleService(ABC):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                @abstractmethod
                def run(self) -> None:
                    self.worker.run()
            """,
            id="abstract-service-declaration",
        ),
        pytest.param(
            """
            @framework_service
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="unknown-class-decorator",
        ),
        pytest.param(
            """
            class ExampleService(metaclass=FrameworkMeta):
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="unknown-metaclass",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                @framework_callback
                def run(self) -> None:
                    self.worker.run()
            """,
            id="unknown-method-decorator",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                @property
                def current(self) -> str:
                    return self.worker.current()
            """,
            id="property-is-not-operation",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                @staticmethod
                def run(self) -> None:
                    self.worker.run()
            """,
            id="static-method-is-not-operation",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self) -> None:
                    worker = Worker()
                    self.worker = worker
                def run(self) -> None:
                    self.worker.run()
            """,
            id="local-construction-is-not-retained-parameter",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    return
                    self.worker.run()
            """,
            id="call-after-return",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    raise RuntimeError()
                    self.worker.run()
            """,
            id="call-after-raise",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    while False:
                        self.worker.run()
            """,
            id="dead-while-body",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self, enabled: bool) -> None:
                    if enabled:
                        return
                    else:
                        raise RuntimeError()
                    self.worker.run()
            """,
            id="call-after-two-terminating-branches",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    callback = lambda: self.worker.run()
            """,
            id="callback-only-created",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    pending = (self.worker.run() for _ in range(3))
            """,
            id="generator-body-not-executed",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, currency: str) -> None:
                    self.currency = currency
                def run(self) -> str:
                    return self.currency.upper()
            """,
            id="retained-value-only",
        ),
        pytest.param(
            """
            from logging import Logger
            class ExampleService:
                def __init__(self, logger: Logger) -> None:
                    self.logger = logger
                def run(self) -> None:
                    self.logger.info("starting")
            """,
            id="logging-only",
        ),
        pytest.param(
            """
            from dataclasses import dataclass
            @dataclass
            class Settings:
                def validate(self) -> None: ...
            class ExampleService:
                def __init__(self, settings: Settings) -> None:
                    self.settings = settings
                def run(self) -> None:
                    self.settings.validate()
            """,
            id="configuration-value-only",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self.worker = Worker()
                    self.worker.run()
            """,
            id="retained-field-reassigned",
        ),
        pytest.param(
            """
            class ExampleService:
                def __init__(self, worker: Worker) -> None:
                    self.worker = worker
                def run(self) -> None:
                    self = replacement()
                    self.worker.run()
            """,
            id="receiver-reassigned",
        ),
    ],
)
def test_valid_contracts_and_non_service_behavior_are_not_reported(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("dependency", ["Worker", "RecordStore", "ConnectionPool", "Logger", "RequestContext"])
def test_one_operation_boundary_does_not_require_substitution_evidence(dependency: str) -> None:
    assert _check(
        f"class ExampleService:\n"
        f"    def __init__(self, backend: {dependency}) -> None:\n"
        "        self.backend = backend\n"
        "    def run(self) -> None:\n"
        "        self.backend.run()\n"
    ) == ["SARJ465"]


def test_legacy_collaborator_diagnostic_preserves_baseline_message() -> None:
    source = (
        "class ExampleService:\n"
        "    def __init__(self, worker: Worker) -> None:\n"
        "        self.worker = worker\n"
        "    def run(self) -> None:\n"
        "        self.worker.run()\n"
    )
    [finding] = RequireExplicitServiceContract().check(Path("app/service.py"), source)
    # The native baseline uses this message as its diagnostic anchor.
    assert finding.format() == (
        "app/service.py:1:1: SARJ465 `ExampleService` invokes a retained collaborator from run "
        "without a declared ABC or Protocol covering its service operations."
    )


def test_canonical_class_and_method_decorators_preserve_operation_identity() -> None:
    assert _check(
        """
        from typing import final as closed, override as implements
        @closed
        class ExampleService:
            def __init__(self, worker: Worker) -> None:
                self.worker = worker
            @implements
            def run(self) -> None:
                self.worker.run()
        """
    ) == ["SARJ465"]


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (
            "from abc import ABC, abstractmethod\nclass Runner(ABC):\n    @abstractmethod\n    def run(self) -> None: ...\n",
            [],
        ),
        (
            "from typing import Protocol as Interface\nclass Runner(Interface):\n    def run(self) -> None: ...\n",
            [],
        ),
        (
            "from abc import ABCMeta as ContractMeta, abstractmethod\nclass Runner(metaclass=ContractMeta):\n    @abstractmethod\n    def run(self) -> None: ...\n",
            [],
        ),
        (
            "from typing import Protocol\nclass Base(Protocol):\n    def run(self) -> None: ...\nclass Runner(Base):\n    pass\n",
            [],
        ),
        ("class Runner:\n    def run(self) -> None: ...\n", ["SARJ465"]),
        (
            "from abc import ABC, abstractmethod\nclass Runner(ABC):\n    @abstractmethod\n    def other(self) -> None: ...\n",
            ["SARJ465"],
        ),
    ],
)
def test_imported_base_must_supply_the_actual_operation(tmp_path: Path, base: str, expected: list[str]) -> None:
    project = tmp_path / "project"
    package = project / "app"
    package.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    contracts = package / "contracts.py"
    service = package / "service.py"
    contracts.write_text(base)
    service.write_text(
        "from app.contracts import Runner\n"
        "class ExampleService(Runner):\n"
        "    def __init__(self, worker: Worker) -> None:\n"
        "        self.worker = worker\n"
        "    def run(self) -> None:\n"
        "        self.worker.run()\n"
    )
    sources = {path: path.read_text() for path in (contracts, service)}
    rule = RequireExplicitServiceContract()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(service, sources[service])] == expected


@pytest.mark.parametrize(
    "state_mutation",
    [
        "self.worker.state = 3",
        "self.worker.context.value = 3",
        "del self.worker.context.value",
        "self.worker.items[0] = 3",
    ],
)
def test_collaborator_state_mutation_does_not_replace_injected_identity(state_mutation: str) -> None:
    assert _check(
        "class ExampleService:\n"
        "    def __init__(self, worker: Worker) -> None:\n"
        "        self.worker = worker\n"
        "    def run(self) -> None:\n"
        f"        {state_mutation}\n"
        "        self.worker.run()\n"
    ) == ["SARJ465"]


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("False and self.worker.run()", []),
        ("True or self.worker.run()", []),
        ("self.worker.run() if False else None", []),
        ("try:\n            return\n            self.worker.run()\n        finally:\n            pass", []),
        ("True and self.worker.run()", ["SARJ465"]),
        ("False or self.worker.run()", ["SARJ465"]),
        ("self.worker.run() if True else None", ["SARJ465"]),
        ("try:\n            return\n        finally:\n            self.worker.run()", ["SARJ465"]),
    ],
)
def test_literal_branches_and_protected_blocks_require_actual_invocation(operation: str, expected: list[str]) -> None:
    assert (
        _check(
            "class ExampleService:\n"
            "    def __init__(self, worker: Worker) -> None:\n"
            "        self.worker = worker\n"
            "    def run(self) -> None:\n"
            f"        {operation}\n"
        )
        == expected
    )
