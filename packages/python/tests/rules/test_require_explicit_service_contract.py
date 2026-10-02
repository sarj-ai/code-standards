from pathlib import Path
import textwrap

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_explicit_service_contract import RequireExplicitServiceContract


def test_documented_examples() -> None:
    verify_native_rule(RequireExplicitServiceContract, analyze)


def _check(source: str, path: str = "app/service.py") -> list[str]:
    return [finding.code for finding in RequireExplicitServiceContract().check(Path(path), textwrap.dedent(source))]


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
