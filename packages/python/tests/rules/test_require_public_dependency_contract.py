from pathlib import Path
import textwrap

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_public_dependency_contract import RequirePublicDependencyContract


def test_documented_examples() -> None:
    verify_native_rule(RequirePublicDependencyContract, analyze)


def _check(source: str) -> list[str]:
    return [
        finding.code
        for finding in RequirePublicDependencyContract().check(Path("app/service.py"), textwrap.dedent(source))
    ]


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("_Worker", ["SARJ466"]),
        ("_Worker | None", ["SARJ466"]),
        ("Worker", []),
        ("Callable[[], None]", []),
    ],
)
def test_private_behavioral_contract_is_visible_at_the_constructor(annotation: str, expected: list[str]) -> None:
    source = f"""
from typing import Protocol
class _Worker(Protocol):
    def run(self) -> None: ...
class Worker(Protocol):
    def run(self) -> None: ...
class Service:
    def __init__(self, worker: {annotation}) -> None:
        self.worker = worker
    def run(self) -> None:
        self.worker.run()
"""
    assert _check(source) == expected


def test_reading_data_does_not_establish_a_behavioral_dependency() -> None:
    assert (
        _check("""
class _Record:
    id = "id"
class Service:
    def __init__(self, record: _Record) -> None:
        self.record = record
    def id(self) -> str:
        return self.record.id
""")
        == []
    )


def test_exact_suppression_on_parameter() -> None:
    assert (
        _check("""
class _Worker: ...
class Service:
    def __init__(self, worker: _Worker) -> None:  # sarj-noqa: SARJ466
        self.worker = worker
    def run(self) -> None:
        self.worker.run()
""")
        == []
    )


def test_owned_concrete_dependency_is_rejected_when_source_resolves(tmp_path: Path) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    implementation = package / "implementation.py"
    service = package / "service.py"
    implementation.write_text("class WorkerService:\n    def run(self) -> None: ...\n")
    service.write_text(
        "from app.implementation import WorkerService\n"
        "class Consumer:\n"
        "    def __init__(self, worker: WorkerService) -> None:\n"
        "        self.worker = worker\n"
        "    def run(self) -> None:\n"
        "        self.worker.run()\n"
    )
    sources = {path: path.read_text() for path in (implementation, service)}
    rule = RequirePublicDependencyContract()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    findings = rule.check(service, sources[service])
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ466", 3)]
