from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_public_dependency_contract import RequirePublicDependencyContract


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    verify_native_rule(RequirePublicDependencyContract, analyze)


@pytest.mark.parametrize(
    ("contract", "alternative", "annotation", "operation", "expected"),
    [
        ("abc", "concrete", "HttpPublisher", "publish", ["SARJ466"]),
        ("protocol", "concrete", "HttpPublisher", "publish", ["SARJ466"]),
        ("abc", "concrete", "Publisher", "publish", []),
        ("abc", "none", "HttpPublisher", "publish", []),
        ("abc", "abstract", "HttpPublisher", "publish", []),
        ("abc", "abstract_extra", "HttpPublisher", "publish", []),
        ("concrete_abc", "concrete", "HttpPublisher", "publish", []),
        ("abc", "concrete", "HttpPublisher", "private_extra", []),
        ("abc", "concrete", "HttpPublisher", "constructor_extra", []),
        ("abc", "concrete", "HttpPublisher", "constructor_alias", []),
        ("abc", "concrete", "HttpPublisher", "constructor_nominal", []),
        ("abc", "concrete", "HttpPublisher", "extra", []),
        ("private", "concrete", "HttpPublisher", "publish", []),
        ("plain", "concrete", "HttpPublisher", "publish", []),
        ("abc", "concrete", "HttpPublisher | None", "publish", ["SARJ466"]),
    ],
)
def test_only_existing_substitutable_contracts_are_recommended(
    tmp_path: Path, *, contract: str, alternative: str, annotation: str, operation: str, expected: list[str]
) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    contract_name = "_Publisher" if contract == "private" else "Publisher"
    base = "Protocol" if contract == "protocol" else "ABC" if contract != "plain" else "object"
    abstract = "    @abstractmethod\n" if contract in {"abc", "private"} else ""
    contracts = package / "contracts.py"
    implementations = package / "implementations.py"
    consumer = package / "consumer.py"
    contracts.write_text(
        "from abc import ABC, abstractmethod\nfrom typing import Protocol\n"
        f"class {contract_name}({base}):\n{abstract}    def publish(self) -> None: ...\n"
    )
    implementation_source = (
        f"from app.contracts import {contract_name}\n"
        f"class HttpPublisher({contract_name}):\n"
        "    def publish(self) -> None: ...\n    def extra(self) -> None: ...\n"
    )
    if alternative == "concrete":
        implementation_source += f"class QueuePublisher({contract_name}):\n    def publish(self) -> None: ...\n"
    elif alternative == "abstract_extra":
        implementation_source += (
            "from abc import abstractmethod\n"
            f"class QueuePublisher({contract_name}):\n    def publish(self) -> None: ...\n"
            "    @abstractmethod\n    def other(self) -> None: ...\n"
        )
    elif alternative == "abstract":
        implementation_source += f"class QueuePublisher({contract_name}): ...\n"
    implementations.write_text(implementation_source)
    operation_body = f"    def run(self) -> None: self.publisher.{operation}()\n"
    if operation == "private_extra":
        operation_body = (
            "    def run(self) -> None:\n        self.publisher.publish()\n        self._helper()\n"
            "    def _helper(self) -> None: self.publisher.extra()\n"
        )
    constructor_body = "self.publisher = publisher"
    if operation.startswith("constructor_"):
        operation_body = "    def run(self) -> None: self.publisher.publish()\n"
        additional = {
            "constructor_extra": "publisher.extra()",
            "constructor_alias": "alias = publisher; alias.extra()",
            "constructor_nominal": "assert isinstance(publisher, HttpPublisher)",
        }[operation]
        constructor_body += f"; {additional}"
    consumer.write_text(
        "from app.implementations import HttpPublisher\nfrom app.contracts import " + contract_name + "\n"
        "class Consumer:\n"
        f"    def __init__(self, publisher: {annotation}) -> None: {constructor_body}\n" + operation_body
    )
    sources = {path: path.read_text() for path in (contracts, implementations, consumer)}
    rule = RequirePublicDependencyContract()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(consumer, sources[consumer])] == expected


def test_private_consumer_owned_protocol_does_not_need_public_export(tmp_path: Path) -> None:
    source = (
        "from typing import Protocol\nclass _Worker(Protocol):\n    def run(self) -> None: ...\n"
        "class Service:\n    def __init__(self, worker: _Worker) -> None: self.worker = worker\n"
        "    def run(self) -> None: self.worker.run()\n"
    )
    assert RequirePublicDependencyContract().check(tmp_path / "service.py", source) == []
