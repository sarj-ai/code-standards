from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.prefer_injected_service import PreferInjectedService


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_WORKER = """\
class Worker:
    def __init__(self, store):
        self.store = store
    def run(self):
        return self.store.load()
"""
_CONSUMER = """\
class Consumer:
    def __init__(self, store):
        self.store = store
    def run(self):
        return Worker(self.store).run()
"""


def _check(source: str, path: str = "app/consumer.py") -> list[Diagnostic]:
    return PreferInjectedService().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(PreferInjectedService, analyze)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_WORKER + _CONSUMER, id="inline-operation"),
        pytest.param(_WORKER + _CONSUMER.replace("Worker(self.store)", "Worker(store=self.store)"), id="keywords"),
        pytest.param(
            _WORKER
            + _CONSUMER.replace(
                "def run(self):\n        return Worker", "async def run(self):\n        return await Worker"
            ),
            id="async-operation",
        ),
        pytest.param((_WORKER + _CONSUMER).replace("Worker", "Transformer"), id="no-role-suffix"),
        pytest.param(
            (_WORKER + _CONSUMER).replace("def run(self):", "def run(self, /):"), id="positional-only-receiver"
        ),
        pytest.param(
            (_WORKER + _CONSUMER).replace("def __init__(self, store):", "def __init__(self, /, store):"),
            id="positional-only-constructor",
        ),
        pytest.param(
            "from typing import override\n"
            + _WORKER
            + _CONSUMER.replace("    def run(self):", "    @override\n    def run(self):"),
            id="consumer-override",
        ),
        pytest.param(
            _WORKER
            + "class Consumer:\n    def __init__(self, store):\n        self.worker = Worker(store)\n    def run(self):\n        return self.worker.run()\n",
            id="constructor-owned-service",
        ),
        pytest.param(
            _WORKER
            + "class Consumer:\n    def __init__(self, store):\n        self.store = store\n        self.worker = Worker(self.store)\n    def run(self):\n        return self.worker.run()\n",
            id="constructor-retained-input",
        ),
        pytest.param(
            _WORKER.replace("self.store = store", "self.store: Store = store") + _CONSUMER, id="annotated-retention"
        ),
        pytest.param(
            _WORKER.replace(
                "def run(self):\n        return self.store.load()",
                "def run(self):\n        return self._load()\n    def _load(self):\n        return self.store.load()",
            )
            + _CONSUMER,
            id="private-behavior-helper",
        ),
        pytest.param(
            _WORKER.replace("class Worker:", "from typing import final\n@final\nclass Worker:") + _CONSUMER,
            id="identity-preserving-final",
        ),
    ],
)
def test_constructed_collaborator_is_injectable(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ564"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].fixes == ()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_WORKER + _CONSUMER.replace("Worker(self.store)", "self.store"), id="already-injected"),
        pytest.param(_WORKER + "def compose(store):\n    return Worker(store)\n", id="composition-function"),
        pytest.param(
            _WORKER + "class Container:\n    def __init__(self, store):\n        self.worker = Worker(store)\n",
            id="composition-container",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("return Worker(self.store).run()", "return Worker(self.store)"),
            id="returned-factory",
        ),
        pytest.param(
            _WORKER
            + _CONSUMER.replace("def run(self):", "def run(self, request):").replace(
                "Worker(self.store)", "Worker(request)"
            ),
            id="request-specific-construction",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("Worker(self.store)", "Worker(self.store, request=request)"),
            id="mixed-runtime-inputs",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("Worker(self.store)", "Worker(*self.store)"), id="expanded-positional-arguments"
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("Worker(self.store)", "Worker(**self.store)"), id="expanded-keyword-arguments"
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("def run(self):", "def run(self, Worker):"), id="shadowed-constructor"
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("def run(self):", "def run(self):\n        self = other"),
            id="shadowed-receiver",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("def run(self):", "def run(self):\n        self.store = new_store"),
            id="mutated-input",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("self.store = store", "self.store = load_store()"), id="unproven-input-origin"
        ),
        pytest.param(
            _WORKER
            + _CONSUMER.replace(
                "return Worker(self.store).run()",
                "def deferred():\n            return Worker(self.store).run()\n        return deferred",
            ),
            id="nested-function",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("return Worker(self.store).run()", "return lambda: Worker(self.store).run()"),
            id="deferred-lambda",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("return Worker(self.store).run()", "yield Worker(self.store).run()"),
            id="generator-owner",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("    def run(self):", "    @staticmethod\n    def run(self):"),
            id="static-factory",
        ),
        pytest.param(
            _WORKER + _CONSUMER.replace("    def run(self):", "    @classmethod\n    def run(self):"),
            id="class-factory",
        ),
        pytest.param(
            _WORKER.replace("return self.store.load()", "return self.store") + _CONSUMER,
            id="record-without-service-behavior",
        ),
        pytest.param(
            _WORKER.replace("class Worker:", "from pydantic import BaseModel\nclass Worker(BaseModel):") + _CONSUMER,
            id="pydantic-value",
        ),
        pytest.param(
            _WORKER.replace("class Worker:", "from dataclasses import dataclass\n@dataclass\nclass Worker:")
            + _CONSUMER,
            id="dataclass-value",
        ),
        pytest.param(_WORKER.replace("class Worker:", "@unknown\nclass Worker:") + _CONSUMER, id="rewriting-decorator"),
        pytest.param(_WORKER.replace("class Worker:", "class Worker(Unknown):") + _CONSUMER, id="inherited-lifecycle"),
        pytest.param(_WORKER + "    def __enter__(self):\n        return self\n" + _CONSUMER, id="resource-owner"),
        pytest.param(
            _WORKER
            + "    store = property(lambda self: self.__dict__['_store'], lambda self, store: self.__dict__.update(_store=store.session()))\n"
            + _CONSUMER,
            id="descriptor-owned-session",
        ),
        pytest.param(
            "from functools import cache\n"
            + _WORKER.replace("return self.store.load()", "return self.store.load(self._session())")
            + "    @cache\n    def _session(self):\n        return self.store.open_session()\n"
            + _CONSUMER,
            id="decorated-helper-owns-state",
        ),
        pytest.param(
            _WORKER.replace(
                "return self.store.load()", "self.store = self.store.clone()\n        return self.store.load()"
            )
            + _CONSUMER,
            id="stateful-service",
        ),
        pytest.param(
            _WORKER.replace("return self.store.load()", "yield self.store.load()") + _CONSUMER, id="generator-service"
        ),
        pytest.param(
            _WORKER.replace("self.store = store", "self.store = store\n        self.cache = {}") + _CONSUMER,
            id="constructor-owned-state",
        ),
        pytest.param(_CONSUMER, id="unknown-class"),
        pytest.param(
            _WORKER
            + "class Consumer:\n    def __init__(self):\n        self.worker = Worker(self)\n    def run(self):\n        return self.worker.run()\n",
            id="circular-receiver-construction",
        ),
        pytest.param(
            _WORKER + _CONSUMER + "    def __enter__(self):\n        return self\n", id="consumer-owns-resource-scope"
        ),
        pytest.param(_WORKER + _CONSUMER + "\nWorker = unknown\n", id="reassigned-class"),
        pytest.param("from unknown import *\n" + _WORKER + _CONSUMER, id="wildcard-import"),
        pytest.param("not valid Python:\n", id="malformed-input"),
    ],
)
def test_near_misses_preserve_legitimate_ownership(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["tests/test_consumer.py", "app/tests/fakes/consumer.py", "app/generated/consumer.py"])
def test_nonproduction_sources_are_excluded(path: str) -> None:
    assert _check(_WORKER + _CONSUMER, path) == []


@pytest.mark.parametrize("reference", ["Worker", "Alias", "implementation.Worker"])
def test_first_party_imports_and_aliases(tmp_path: Path, reference: str) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    worker = package / "implementation.py"
    consumer = package / "consumer.py"
    worker.write_text(_WORKER)
    consumer.write_text(
        "from app.implementation import Worker, Worker as Alias\nimport app.implementation as implementation\n"
        + _CONSUMER.replace("Worker(self.store)", f"{reference}(self.store)")
    )
    sources = {path: path.read_text() for path in (worker, consumer)}
    rule = PreferInjectedService()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert len(rule.check(consumer, sources[consumer])) == 1


def test_suppression_uses_normal_analysis_policy(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    source = _WORKER + _CONSUMER.replace(
        "return Worker(self.store).run()",
        "return Worker(self.store).run()  # sarj-noqa: SARJ564 -- This consumer owns the collaborator's lifetime.",
    )
    path.write_text(source)
    assert analyze(["prefer-injected-service"], [path]) == []
