from __future__ import annotations

import subprocess
import sys
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


def test_relative_source_inside_a_package_has_bounded_ownership_resolution(tmp_path: Path) -> None:
    package = tmp_path / "owned"
    package.mkdir()
    (package / "__init__.py").write_text("")
    source = "from pathlib import Path\nfrom sarj_python_lint.rules._project_index import ProjectIndexSet\nproject = ProjectIndexSet.single(Path('module.py'), 'class Consumer: pass')\nunit = project.unit(Path('module.py'))\nassert unit is not None and unit.module == 'owned.module'\n"
    subprocess.run([sys.executable, "-c", source], cwd=package, check=True, capture_output=True, timeout=5)


@pytest.mark.parametrize(
    "replacement",
    ["    def __init__(self, publisher: object): pass\n", "    __init__ = lambda self, publisher: None\n"],
)
def test_overwritten_constructor_cannot_own_the_injected_contract(tmp_path: Path, replacement: str) -> None:
    target = tmp_path / "app.py"
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\nversion = '1.0'\n")
    source = (
        "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n    @abstractmethod\n    def publish(self): ...\nclass FakePublisher:\n    def publish(self): ...\nclass Consumer:\n    def __init__(self, publisher: Publisher): pass\n"
        + replacement
        + "Consumer(FakePublisher())\n"
    )
    target.write_text(source)
    assert analyze(["require-explicit-contract-implementation"], [target]) == []


@pytest.mark.parametrize("customization", ["@structural\n", ""])
def test_consumer_constructor_ownership_must_be_plain(tmp_path: Path, customization: str) -> None:
    target = tmp_path / "app.py"
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\nversion = '1.0'\n")
    replacement = "    def __new__(cls, publisher): return publisher\n" if not customization else ""
    source = (
        "from abc import ABC, abstractmethod\n"
        "class Publisher(ABC):\n    @abstractmethod\n    def publish(self): ...\n"
        "class FakePublisher:\n    def publish(self): ...\n"
        "def structural(owner): return lambda publisher: publisher\n"
        + customization
        + "class Consumer:\n"
        + replacement
        + "    def __init__(self, publisher: Publisher): self.publisher = publisher\n"
        "Consumer(publisher=FakePublisher())\n"
    )
    target.write_text(source)
    assert analyze(["require-explicit-contract-implementation"], [target]) == []


@pytest.mark.parametrize(
    ("fake", "usage", "expected"),
    [
        (
            "class FakePublisher:\n    def publish(self) -> None: ...\n",
            "fake = FakePublisher()\n    Consumer(publisher=fake)\n",
            ["SARJ467"],
        ),
        (
            (
                "class Shared:\n    def publish(self) -> None: ...\n"
                "class Left(Shared): ...\nclass Right(Shared): ...\n"
                "class FakePublisher(Left, Right): ...\n"
            ),
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
        (
            "from app.contracts import Publisher\nclass FakePublisher:\n    def publish(self) -> None: ...\nPublisher.register(FakePublisher)\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from app.contracts import Publisher\n@Publisher.register\nclass FakePublisher:\n    def publish(self) -> None: ...\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from app.contracts import Publisher\nclass FakePublisher:\n    def publish(self) -> None: ...\nalias = Publisher\nalias.register(FakePublisher)\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from app.contracts import Publisher\nclass Real(Publisher):\n    def publish(self) -> None: ...\nclass FakePublisher:\n    def __new__(cls): return Real()\n    def publish(self) -> None: ...\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from app.contracts import Publisher\nclass Real(Publisher):\n    def publish(self) -> None: ...\nclass FakePublisher:\n    def __init__(self): self.__class__ = Real\n    def publish(self) -> None: ...\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from app.contracts import Publisher\nclass Real(Publisher):\n    def publish(self) -> None: ...\nclass Wrapped:\n    def __init_subclass__(cls): cls.__new__ = staticmethod(lambda cls: Real())\nclass FakePublisher(Wrapped):\n    def publish(self) -> None: ...\n",
            "Consumer(publisher=FakePublisher())\n",
            [],
        ),
        (
            "from typing import TypeGuard\nfrom app.contracts import Publisher\nclass Real(Publisher):\n    def publish(self) -> None: ...\nclass FakePublisher:\n    def publish(self) -> None: ...\ndef as_publisher(value: object) -> TypeGuard[Publisher]:\n    value.__class__ = Real\n    return True\n",
            "from app.fake import as_publisher\n    fake = FakePublisher()\n    if as_publisher(fake):\n        Consumer(publisher=fake)\n",
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
        "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\n"
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


@pytest.mark.parametrize(
    "annotation", ["contracts.Publisher", "contracts.Publisher | None", "Union[contracts.Publisher, None]"]
)
def test_qualified_contract_annotation_keeps_its_module(annotation: str, tmp_path: Path) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    contracts = package / "contracts.py"
    consumer = package / "consumer.py"
    fake = package / "fake.py"
    caller = package / "usage.py"
    contracts.write_text(
        "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\n"
    )
    consumer.write_text(
        f"from typing import Union\nimport app.contracts as contracts\nclass Consumer:\n    def __init__(self, publisher: {annotation}) -> None: self.publisher = publisher\n"
    )
    fake.write_text("class FakePublisher:\n    def publish(self) -> None: ...\n")
    caller.write_text(
        "from app.consumer import Consumer\nfrom app.fake import FakePublisher\n"
        "def setup() -> None:\n    Consumer(publisher=FakePublisher())\n"
    )
    sources = {path: path.read_text() for path in (contracts, consumer, fake, caller)}
    rule = RequireExplicitContractImplementation()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(caller, sources[caller])] == ["SARJ467"]


@pytest.mark.parametrize(
    ("derived_body", "expected"),
    [
        ("class Publisher(BasePublisher): ...\n", ["SARJ467"]),
        ("class Publisher(BasePublisher):\n    def publish(self) -> None: ...\n", []),
        (
            (
                "class Left(BasePublisher):\n    def publish(self) -> None: ...\n"
                "class Right(BasePublisher): ...\nclass Publisher(Left, Right): ...\n"
            ),
            [],
        ),
    ],
)
def test_only_still_abstract_abc_subclasses_are_contracts(
    derived_body: str, expected: list[str], tmp_path: Path
) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    contracts = package / "contracts.py"
    consumer = package / "consumer.py"
    fake = package / "fake.py"
    caller = package / "usage.py"
    contracts.write_text(
        "from abc import ABC, abstractmethod\n"
        "class BasePublisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\n" + derived_body
    )
    consumer.write_text(
        "from app.contracts import Publisher\nclass Consumer:\n"
        "    def __init__(self, publisher: Publisher) -> None: self.publisher = publisher\n"
    )
    fake.write_text("class FakePublisher:\n    def publish(self) -> None: ...\n")
    caller.write_text(
        "from app.consumer import Consumer\nfrom app.fake import FakePublisher\n"
        "def setup() -> None:\n    Consumer(publisher=FakePublisher())\n"
    )
    sources = {path: path.read_text() for path in (contracts, consumer, fake, caller)}
    rule = RequireExplicitContractImplementation()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(caller, sources[caller])] == expected


@pytest.mark.parametrize(
    "protocol_import",
    [
        "from typing import Protocol",
        "from typing_extensions import Protocol",
        "from typing import Protocol as StructuralContract",
    ],
)
def test_protocol_implementations_remain_structural(protocol_import: str, tmp_path: Path) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    protocol = "StructuralContract" if " as " in protocol_import else "Protocol"
    contracts = package / "contracts.py"
    consumer = package / "consumer.py"
    fake = package / "fake.py"
    caller = package / "usage.py"
    contracts.write_text(f"{protocol_import}\nclass Publisher({protocol}):\n    def publish(self) -> None: ...\n")
    consumer.write_text(
        "from app.contracts import Publisher\nclass Consumer:\n"
        "    def __init__(self, publisher: Publisher) -> None: self.publisher = publisher\n"
    )
    fake.write_text("class FakePublisher:\n    def publish(self) -> None: ...\n")
    caller.write_text(
        "from app.consumer import Consumer\nfrom app.fake import FakePublisher\n"
        "def setup() -> None:\n    Consumer(publisher=FakePublisher())\n"
    )
    sources = {path: path.read_text() for path in (contracts, consumer, fake, caller)}
    rule = RequireExplicitContractImplementation()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert rule.check(caller, sources[caller]) == []
