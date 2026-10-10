from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.repeated_unimplemented_test_contract import RepeatedUnimplementedTestContract


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PATH = Path("tests/test_store.py")
_CONTRACT = """
from abc import ABC, abstractmethod

class Store(ABC):
    @abstractmethod
    async def read(self, key: str, *, fresh: bool = False) -> str:
        pass

class FirstStore(Store):
    async def read(self, key: str, *, fresh: bool = False) -> str:
        raise NotImplementedError
"""
_SECOND = """
class SecondStore(Store):
    async def read(self, key: str, *, fresh: bool = False) -> str:
        raise NotImplementedError
"""


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    source = textwrap.dedent(source)
    rule = RepeatedUnimplementedTestContract()
    rule.prepare(ProjectIndexSet.single(path, source))
    return rule.check(path, source)


_EXAMPLES = RepeatedUnimplementedTestContract.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(item.example_id for item in _EXAMPLES))
def test_executable_documentation(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_path))) == example.expected_count


def test_reports_one_warning_for_the_duplicate_class() -> None:
    [finding] = _check(_CONTRACT + _SECOND)
    assert finding.code == "SARJ490"
    assert finding.severity is Severity.WARNING
    assert "read" in finding.message
    assert finding.line == len(textwrap.dedent(_CONTRACT).splitlines()) + 2


@pytest.mark.parametrize(
    "second",
    [
        pytest.param(_SECOND.replace("raise NotImplementedError", "return key"), id="configured-behavior"),
        pytest.param(
            _SECOND.replace("raise NotImplementedError", "raise NotImplementedError('offline')"), id="message"
        ),
        pytest.param(
            _SECOND.replace("raise NotImplementedError", "record(key)\n        raise NotImplementedError"),
            id="side-effect",
        ),
        pytest.param(_SECOND.replace("fresh: bool = False", "fresh: bool = True"), id="default-contract"),
        pytest.param(_SECOND.replace("key: str", "key: bytes"), id="parameter-contract"),
        pytest.param(_SECOND.replace("async def", "def"), id="failure-timing"),
        pytest.param(_SECOND.replace("async def", "@custom\n    async def"), id="decorator"),
        pytest.param(_SECOND.replace("class SecondStore", "@dataclass\nclass SecondStore"), id="class-decorator"),
        pytest.param(_SECOND.replace("SecondStore(Store)", "SecondStore(Store, Other)"), id="mro"),
        pytest.param(
            _SECOND.replace("raise NotImplementedError", "super().read(key)\n        raise NotImplementedError"),
            id="super-dispatch",
        ),
        pytest.param(_SECOND + "\ninspect(SecondStore.__dict__)\n", id="reflection"),
        pytest.param(_SECOND + "\nNotImplementedError = custom_error\n", id="shadowed-error"),
        pytest.param(_SECOND + "\nStore = replacement\n", id="rebound-contract"),
        pytest.param(_SECOND + "\nassert FirstStore.read is not SecondStore.read\n", id="method-identity"),
        pytest.param(_SECOND + "\nassert SecondStore.__base__ is Store\n", id="direct-parent-observation"),
        pytest.param(_SECOND + "\ncallback = FirstStore.read\n", id="method-callback"),
        pytest.param(_SECOND + "\nFirstStore.read.marker = 'owned'\n", id="method-metadata"),
        pytest.param(_SECOND + "\nSecondStore = replacement\n", id="rebound-fake"),
        pytest.param(_SECOND + _SECOND, id="repeated-class-binding"),
        pytest.param(
            "from builtins import super as parent\n"
            + _SECOND
            + "\n    def configured(self, key: str):\n        return parent(type(self), self).read(key)\n",
            id="imported-super-alias",
        ),
        pytest.param(
            "import builtins as native\n"
            + _SECOND
            + "\n    def configured(self, key: str):\n        return native.super(type(self), self).read(key)\n",
            id="namespace-super-alias",
        ),
        pytest.param(
            _SECOND
            + "\n    def configured(self, key: str):\n        from builtins import super as parent\n        return parent(type(self), self).read(key)\n",
            id="local-super-import",
        ),
    ],
)
def test_preserves_nonidentical_or_observable_contracts(second: str) -> None:
    assert _check(_CONTRACT + second) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_CONTRACT, id="single-fake"),
        pytest.param((_CONTRACT + _SECOND).replace("@abstractmethod\n", ""), id="concrete-operation"),
        pytest.param((_CONTRACT + _SECOND).replace("Store(ABC)", "Store(Unknown)"), id="unknown-ancestry"),
        pytest.param((_CONTRACT + _SECOND).replace("key: str", "key"), id="untyped-parameter"),
        pytest.param(
            (_CONTRACT + _SECOND).replace("fresh: bool = False", "fresh: bool = setting()"), id="captured-default"
        ),
        pytest.param(
            (_CONTRACT + _SECOND).replace(
                "class Store(ABC):\n",
                "registered = []\nclass Store(ABC):\n    def __init_subclass__(cls):\n        registered.append(cls)\n",
            ),
            id="contract-subclass-registration",
        ),
        pytest.param(
            (_CONTRACT + _SECOND).replace(
                "class Store(ABC):\n", "class Store(ABC):\n    def __init__(self):\n        super().__init__()\n"
            ),
            id="contract-super-dispatch",
        ),
        pytest.param((_CONTRACT + _SECOND).replace("key: str", 'key: list["str"]'), id="nested-string-annotation"),
    ],
)
def test_requires_resolved_typed_abstract_contract(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path", [Path("app/store.py"), Path("tests/generated/test_store.py")], ids=("production", "generated")
)
def test_excludes_production_and_generated_sources(path: Path) -> None:
    assert _check(_CONTRACT + _SECOND, path) == []


@pytest.mark.parametrize(
    ("base", "namespace_write", "expected"),
    [
        pytest.param("Port", "", 1, id="imported-contract-alias"),
        pytest.param("ports.Store", "", 1, id="imported-namespace"),
        pytest.param("ports.Store", "ports.Store = object\n", 0, id="reassigned-namespace-base"),
        pytest.param("ports.Store", "del ports.Store\n", 0, id="deleted-namespace-base"),
    ],
)
def test_resolves_contract_and_type_aliases_across_test_modules(
    tmp_path: Path, base: str, namespace_write: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.1.0"\n')
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("")
    tests = tmp_path / "tests"
    tests.mkdir()
    sources = {
        app
        / "store.py": "from abc import ABC, abstractmethod\nclass Value:\n    pass\nclass Store(ABC):\n    @abstractmethod\n    def read(self, key: Value) -> str:\n        pass\n",
        tests
        / "test_a.py": "from app.store import Store, Value\nclass First(Store):\n    def read(self, key: Value) -> str:\n        raise NotImplementedError\n",
        tests
        / "test_b.py": f"import app.store as ports\nfrom app.store import Store as Port, Value as Key\n{namespace_write}class Second({base}):\n    def read(self, key: Key) -> str:\n        raise NotImplementedError\n",
    }
    for path, source in sources.items():
        path.write_text(source)
    rule = RepeatedUnimplementedTestContract()
    rule.prepare(ProjectIndexSet.build(tuple(sources), sources))
    assert rule.check(tests / "test_a.py", sources[tests / "test_a.py"]) == []
    assert len(rule.check(tests / "test_b.py", sources[tests / "test_b.py"])) == expected


def test_exact_suppression_and_malformed_source() -> None:
    assert (
        _check(
            _CONTRACT
            + _SECOND.replace(
                "SecondStore(Store):", "SecondStore(Store):  # sarj-noqa: SARJ490 -- intentionally independent contract"
            )
        )
        == []
    )
    assert _check("class broken(") == []
