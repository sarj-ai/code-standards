from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity


if TYPE_CHECKING:
    from pathlib import Path


_NEARBY_RULES = [
    "no-hidden-constructor-fallback",
    "no-nullable-dependency-fallback",
    "require-explicit-contract-implementation",
    "require-precise-factory-signature",
    "no-unused-underscored-keyword-parameter",
    "no-unused-value-marker",
    "unused-test-factory-option",
    "no-injected-module-loader",
    "require-public-dependency-contract",
    "discourage-nullable-constructor-parameters",
    "require-explicit-service-contract",
    "require-port-for-service",
    "prefer-pytest-fixture-injection",
    "repeated-test-composition",
]


_VALID_API_CASES = (
    EvaluationCase(
        "optional-lifecycle-state",
        Language.PYTHON,
        "class Client:\n"
        "    def __init__(self, participant: object | None = None):\n"
        "        self.participant = participant\n"
        "    def connected(self) -> bool:\n"
        "        return self.participant is not None\n"
        "client = Client()\n",
    ),
    EvaluationCase(
        "required-nullable-domain-state",
        Language.PYTHON,
        "from __future__ import annotations\n"
        "class Node:\n"
        "    def __init__(self, parent: Node | None):\n"
        "        self.parent = parent\n"
        "root = Node(None)\n",
    ),
    EvaluationCase(
        "callable-injection-default",
        Language.PYTHON,
        "from collections.abc import Callable\n"
        "from importlib import import_module\n"
        "from types import ModuleType\n"
        "def load_extension(\n"
        "    name: str, importer: Callable[[str], ModuleType] = import_module,\n"
        ") -> ModuleType:\n"
        "    return importer(name)\n",
    ),
    EvaluationCase(
        "precise-ignored-callback-slot",
        Language.PYTHON,
        "from typing import Protocol\n"
        "class Factory(Protocol):\n"
        "    def __call__(self, *, _token: str) -> str: ...\n"
        "def make(*, _token: str = 'unused') -> str:\n"
        "    return 'ready'\n"
        "def construct(factory: Factory = make) -> str:\n"
        "    return factory(_token='configured')\n",
    ),
)


@pytest.mark.parametrize("case", _VALID_API_CASES, ids=tuple(case.case_id for case in _VALID_API_CASES))
def test_valid_apis_remain_valid_in_combined_runner(tmp_path: Path, case: EvaluationCase) -> None:
    path = tmp_path / "service.py"
    path.write_text(case.source)

    findings = analyze(_NEARBY_RULES, [path])
    assert findings == analyze(_NEARBY_RULES[::-1], [path])
    expected = ["SARJ468"] if case.case_id == "optional-lifecycle-state" else []
    assert [finding.code for finding in findings] == expected
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("contract_base", ["Protocol", "ABC"])
def test_structural_and_nominal_contracts_keep_their_semantics(tmp_path: Path, contract_base: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    sources = {
        "__init__.py": "",
        "contract.py": (
            "from abc import ABC, abstractmethod\nfrom typing import Protocol\n"
            f"class Publisher({contract_base}):\n"
            + ("    @abstractmethod\n" if contract_base == "ABC" else "")
            + "    def publish(self) -> None: ...\n"
        ),
        "consumer.py": (
            "from app.contract import Publisher\nclass Consumer:\n"
            "    def __init__(self, publisher: Publisher):\n        self.publisher = publisher\n"
        ),
        "caller.py": (
            "from app.consumer import Consumer\nclass Fake:\n    def publish(self) -> None: ...\n"
            "def setup() -> None:\n    Consumer(publisher=Fake())\n"
        ),
    }
    paths: list[Path] = []
    for name, source in sources.items():
        path = package / name
        path.write_text(source)
        paths.append(path)

    expected = ["SARJ467"] if contract_base == "ABC" else []
    assert [finding.code for finding in analyze(_NEARBY_RULES, paths)] == expected
    assert [finding.code for finding in analyze(_NEARBY_RULES[::-1], paths)] == expected


def test_real_hidden_settings_and_callable_fallbacks_still_warn(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    path = tmp_path / "service.py"
    path.write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n    token: str = 'ambient'\nsettings = Settings()\n"
        "class Client:\n"
        "    def __init__(self, token: str | None = None):\n"
        "        self.token = settings.token if token is None else token\n"
        "client = Client(token='explicit')\n"
        "def construct(factory=None):\n    return (factory or Client)()\n"
    )

    assert sorted(finding.code for finding in analyze(_NEARBY_RULES, [path])) == ["SARJ095", "SARJ469"]


_CALIBRATED_STYLE_CASES = (
    EvaluationCase(
        "closed-local-invariant-option",
        Language.PYTHON,
        "def test_values():\n"
        "    def _make_value(*, size=3):\n        return str(size)\n"
        "    assert _make_value() == '3'\n"
        "    assert _make_value(size=3) == '3'\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("tests/test_value.py"),
    ),
    EvaluationCase(
        "shared-factory-default",
        Language.PYTHON,
        "def _make_value(*, size=3):\n    return str(size)\n"
        "def test_values():\n"
        "    assert _make_value() == '3'\n"
        "    assert _make_value(size=3) == '3'\n",
        path=PurePosixPath("tests/test_value.py"),
    ),
    EvaluationCase(
        "closed-local-callable-default",
        Language.PYTHON,
        "def read() -> str:\n    return 'ready'\n"
        "def test_values():\n"
        "    def _make_value(*, read=read):\n        return str(read())\n"
        "    assert _make_value() == 'ready'\n"
        "    assert _make_value() == 'ready'\n",
        path=PurePosixPath("tests/test_value.py"),
    ),
    EvaluationCase(
        "fixed-module-loader-indirection",
        Language.PYTHON,
        "from importlib import import_module\ndef load(*, importer=import_module):\n    return importer('math')\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("service.py"),
    ),
    EvaluationCase(
        "immediately-rejected-nullable-default",
        Language.PYTHON,
        "class Client:\n"
        "    def __init__(self, participant: object | None = None):\n"
        "        if participant is None:\n"
        "            raise ValueError('participant is required')\n"
        "        self.participant = participant\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("service.py"),
    ),
)


@pytest.mark.parametrize("case", _CALIBRATED_STYLE_CASES, ids=tuple(case.case_id for case in _CALIBRATED_STYLE_CASES))
def test_narrowed_style_rules_preserve_unique_signals(tmp_path: Path, case: EvaluationCase) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source)
    expected = {
        "closed-local-invariant-option": ["SARJ443"],
        "fixed-module-loader-indirection": ["SARJ471"],
        "immediately-rejected-nullable-default": ["SARJ468"],
    }.get(case.case_id, [])

    assert [finding.code for finding in analyze(_NEARBY_RULES, [path])] == expected
    assert [finding.code for finding in analyze(_NEARBY_RULES[::-1], [path])] == expected


@pytest.mark.parametrize("annotation", ["HttpPublisher", "Publisher"])
def test_existing_substitutable_contract_is_reused_without_creating_one(tmp_path: Path, annotation: str) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    (package / "__init__.py").write_text("")
    contract = package / "publisher.py"
    contract.write_text(
        "from abc import ABC, abstractmethod\n"
        "class Publisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\n"
        "class HttpPublisher(Publisher):\n    def publish(self) -> None: ...\n"
        "class QueuePublisher(Publisher):\n    def publish(self) -> None: ...\n"
    )
    consumer = package / "consumer.py"
    consumer.write_text(
        "from typing import Protocol\n"
        "from app.publisher import Publisher, HttpPublisher\n"
        "class _ConsumerPort(Protocol):\n    def run(self) -> None: ...\n"
        "class ConsumerService(_ConsumerPort):\n"
        f"    def __init__(self, publisher: {annotation}) -> None:\n        self.publisher = publisher\n"
        "    def run(self) -> None:\n        self.publisher.publish()\n"
    )

    expected = ["SARJ466"] if annotation == "HttpPublisher" else []
    assert [finding.code for finding in analyze(_NEARBY_RULES, [contract, consumer])] == expected


@pytest.mark.parametrize("dependency", ["RecordStore", "ConnectionPool", "Worker"])
def test_single_operation_service_keeps_proactive_contract_policy(tmp_path: Path, dependency: str) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "class ExampleService:\n"
        f"    def __init__(self, backend: {dependency}) -> None:\n        self.backend = backend\n"
        "    def run(self) -> None:\n        self.backend.run()\n"
    )

    assert [finding.code for finding in analyze(_NEARBY_RULES, [path])] == ["SARJ465"]
    assert [finding.code for finding in analyze(_NEARBY_RULES[::-1], [path])] == ["SARJ465"]


@pytest.mark.parametrize("contract_base", ["ABC", "Protocol"])
@pytest.mark.parametrize("contract_name", ["Runner", "_Runner"])
def test_declared_contract_aliases_satisfy_combined_service_rules(
    tmp_path: Path, contract_base: str, contract_name: str
) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        f"from {'abc' if contract_base == 'ABC' else 'typing'} import {contract_base} as Interface\n"
        "from abc import abstractmethod\n"
        f"class {contract_name}(Interface):\n"
        + ("    @abstractmethod\n" if contract_base == "ABC" else "")
        + "    def run(self) -> None: ...\n"
        f"class ExampleService({contract_name}):\n"
        "    def __init__(self, worker: Worker) -> None:\n        self.worker = worker\n"
        "    def run(self) -> None:\n        self.worker.run()\n"
    )

    assert analyze(_NEARBY_RULES, [path]) == []
    assert analyze(_NEARBY_RULES[::-1], [path]) == []


@pytest.mark.parametrize(
    ("suppression", "expected"),
    [
        ("", ["SARJ465"]),
        ("SARJ465", ["SARJ071"]),
        ("SARJ071", ["SARJ465"]),
        ("SARJ465, SARJ071", []),
    ],
)
def test_contract_precedence_and_suppression_do_not_hide_independent_rules(
    tmp_path: Path, suppression: str, expected: list[str]
) -> None:
    path = tmp_path / "service.py"
    comment = f"  # sarj-noqa: {suppression} -- contract supplied by framework" if suppression else ""
    path.write_text(
        f"class ThingService:{comment}\n"
        "    def __init__(self, store: ThingDAO) -> None:\n        self.store = store\n"
        "    def read(self, key: str) -> str:\n        return self.store.get(key)\n"
        "    def write(self, key: str, value: str) -> None:\n        self.store.put(key, value)\n"
    )

    assert [finding.code for finding in analyze(_NEARBY_RULES, [path])] == expected
    assert [finding.code for finding in analyze(_NEARBY_RULES[::-1], [path])] == expected


@pytest.mark.parametrize("injected", [False, True])
def test_pool_and_repeated_client_setup_have_compatible_fixture_remediation(tmp_path: Path, injected: bool) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    support = tests / "conftest.py"
    support.write_text(
        "from psycopg_pool import AsyncConnectionPool\n"
        + ("import pytest\nimport pytest_asyncio\nfrom httpx import AsyncClient, ASGITransport\n" if injected else "")
        + ("@pytest.fixture\n" if injected else "")
        + "def pool():\n    return AsyncConnectionPool(open=False)\n"
        + (
            "@pytest.fixture\ndef app(pool):\n    return build_app(pool)\n"
            "@pytest_asyncio.fixture\nasync def client(app):\n"
            "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:\n"
            "        yield client\n"
            if injected
            else ""
        )
    )
    path = tests / "test_app.py"
    path.write_text(
        ("" if injected else "from tests.conftest import pool\nfrom httpx import AsyncClient, ASGITransport\n")
        + "\n".join(
            f"async def test_case_{number}(client):\n    assert await client.get('/')\n"
            if injected
            else f"async def test_case_{number}():\n    resource = pool()\n    app = build_app(resource)\n"
            "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:\n"
            "        assert await client.get('/')\n"
            for number in range(3)
        )
    )
    expected = [] if injected else ["SARJ457"] * 3 + ["SARJ476"] * 3

    assert sorted(finding.code for finding in analyze(_NEARBY_RULES, [support, path], root=tmp_path)) == expected
    assert sorted(finding.code for finding in analyze(_NEARBY_RULES[::-1], [support, path], root=tmp_path)) == expected
