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
            ["SARJ465"],
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
            ["SARJ465"],
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
    ("base", "expected"),
    [
        (
            "from abc import ABC, abstractmethod\nclass Runner(ABC):\n    @abstractmethod\n    def run(self) -> None: ...\n",
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
