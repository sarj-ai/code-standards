from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_explicit_contract_implementation import RequireExplicitContractImplementation


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    verify_native_rule(RequireExplicitContractImplementation, analyze)


@pytest.mark.parametrize(
    ("fake", "usage", "expected"),
    [
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "fake = FakePublisher()\n    Consumer(publisher=fake)\n",
            ["SARJ467"],
        ),
        (
            "from app.contracts import Publisher\nclass BaseFake(Publisher):\n    def publish(self) -> None: ...\nclass FakePublisher(BaseFake): ...\n",
            "fake = FakePublisher()\n    Consumer(publisher=fake)\n",
            [],
        ),
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "from typing import Any\n    fake: Any = FakePublisher()\n    Consumer(publisher=fake)\n",
            [],
        ),
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "fake = FakePublisher()\n    if condition:\n        fake = unknown\n    Consumer(publisher=fake)\n",
            [],
        ),
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "fake = FakePublisher()\n    for item in items:\n        fake = item\n    Consumer(publisher=fake)\n",
            [],
        ),
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "fake = FakePublisher()\n    try:\n        fake = unknown\n    except Exception:\n        pass\n    Consumer(publisher=fake)\n",
            [],
        ),
    ],
)
def test_declared_relationship_and_known_origin_are_required(
    tmp_path: Path, fake: str, usage: str, expected: list[str]
) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("# package\n")
    contracts = package / "contracts.py"
    consumer = package / "consumer.py"
    fake_path = package / "fake.py"
    caller = package / "usage.py"
    contracts.write_text(
        "from typing import Protocol\nclass Publisher(Protocol):\n    def publish(self) -> None: ...\n"
    )
    consumer.write_text(
        "from app.contracts import Publisher\nclass Consumer:\n    def __init__(self, publisher: Publisher) -> None: self.publisher = publisher\n"
    )
    fake_path.write_text(fake)
    caller.write_text(
        f"from app.consumer import Consumer\nfrom app.fake import FakePublisher\ndef setup() -> None:\n    {usage}"
    )
    sources = {path: path.read_text() for path in (contracts, consumer, fake_path, caller)}
    rule = RequireExplicitContractImplementation()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(caller, sources[caller])] == expected
