from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.prefer_explicit_value_model_construction import PreferExplicitValueModelConstruction


_PATH = Path("app/models.py")
_DATACLASS = "from dataclasses import dataclass\n@dataclass(frozen=True, slots=True)\nclass Value:\n"
_HOOK = "    def __post_init__(self) -> None:\n        pass\n"


def test_documented_examples() -> None:
    verify_native_rule(PreferExplicitValueModelConstruction, analyze)


@pytest.mark.parametrize(
    "declaration",
    [
        pytest.param(_DATACLASS, id="stdlib-dataclass"),
        pytest.param("from dataclasses import dataclass as value\n@value\nclass Value:\n", id="aliased-decorator"),
        pytest.param("import dataclasses as dc\n@dc.dataclass\nclass Value:\n", id="aliased-module"),
        pytest.param("from pydantic.dataclasses import dataclass\n@dataclass\nclass Value:\n", id="pydantic-dataclass"),
        pytest.param(
            "import pydantic.dataclasses\n@pydantic.dataclasses.dataclass\nclass Value:\n",
            id="qualified-pydantic-dataclass",
        ),
        pytest.param("from pydantic.v1.dataclasses import dataclass\n@dataclass\nclass Value:\n", id="v1-dataclass"),
        pytest.param("from pydantic import BaseModel\nclass Value(BaseModel):\n", id="native-model"),
        pytest.param("from pydantic.main import BaseModel as Model\nclass Value(Model):\n", id="aliased-native-model"),
        pytest.param("import pydantic as pd\nclass Value(pd.BaseModel):\n", id="aliased-model-module"),
        pytest.param("from pydantic.v1 import BaseModel\nclass Value(BaseModel):\n", id="v1-model"),
        pytest.param(
            "from pydantic import BaseModel\nclass Parent(BaseModel):\n    pass\nclass Value(Parent):\n",
            id="inherited-model",
        ),
        pytest.param(
            "from typing import final\n" + _DATACLASS.replace("@dataclass", "@final\n@dataclass"), id="final-dataclass"
        ),
    ],
)
@pytest.mark.parametrize("hook", ["__post_init__", "model_post_init", "__post_init_post_parse__"])
def test_warns_on_named_value_initialization_hooks(declaration: str, hook: str) -> None:
    findings = PreferExplicitValueModelConstruction().check(_PATH, declaration + _HOOK.replace("__post_init__", hook))
    assert len(findings) == 1
    assert findings[0].code == "SARJ572"
    assert findings[0].severity is Severity.WARNING
    assert hook in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("class Value:\n" + _HOOK, id="unrelated-class"),
        pytest.param("class BaseModel:\n    pass\nclass Value(BaseModel):\n" + _HOOK, id="model-spelling"),
        pytest.param("from other import BaseModel\nclass Value(BaseModel):\n" + _HOOK, id="unrelated-import"),
        pytest.param("from other import dataclass\n@dataclass\nclass Value:\n" + _HOOK, id="unrelated-decorator"),
        pytest.param("def __post_init__() -> None:\n    pass\n", id="free-function"),
        pytest.param(
            _DATACLASS.replace("@dataclass", "dataclass = custom\n@dataclass") + _HOOK, id="rebound-decorator"
        ),
        pytest.param(
            "from pydantic import BaseModel\nBaseModel = Custom\nclass Value(BaseModel):\n" + _HOOK, id="rebound-base"
        ),
        pytest.param(
            "import dataclasses as dc\ndc.dataclass = custom\n@dc.dataclass\nclass Value:\n" + _HOOK,
            id="mutated-decorator-module",
        ),
        pytest.param(
            "import pydantic as pd\npd.BaseModel = Custom\nclass Value(pd.BaseModel):\n" + _HOOK,
            id="mutated-model-module",
        ),
        pytest.param(_DATACLASS.replace("@dataclass", "@replacement\n@dataclass") + _HOOK, id="unknown-decorator"),
        pytest.param(
            "from pydantic import BaseModel\nclass Value(BaseModel, metaclass=Custom):\n" + _HOOK, id="class-keyword"
        ),
        pytest.param("from plugin import *\n" + _DATACLASS + _HOOK, id="wildcard-namespace"),
        pytest.param(_DATACLASS + _HOOK + "exec(source)\n", id="dynamic-namespace"),
        pytest.param(
            "def enclosing():\n    from dataclasses import dataclass\n    @dataclass\n    class Value:\n        def __post_init__(self): pass\n",
            id="nested-class-boundary",
        ),
        pytest.param("class Parent(Unknown):\n    pass\nclass Value(Parent):\n" + _HOOK, id="unresolved-ancestry"),
        pytest.param("class A(B): pass\nclass B(A): pass\nclass Value(A):\n" + _HOOK, id="cyclic-ancestry"),
        pytest.param(
            "from pydantic import BaseModel\nclass Value[BaseModel](BaseModel):\n" + _HOOK,
            id="generic-parameter-shadows-native-base",
        ),
        pytest.param("def broken(\n", id="malformed-input"),
    ],
)
def test_preserves_unproven_models_and_explicit_boundaries(source: str) -> None:
    assert PreferExplicitValueModelConstruction().check(_PATH, source) == []


@pytest.mark.parametrize("hook", ["__init__", "__iter__", "__enter__", "__exit__", "__aiter__", "close"])
def test_preserves_ordinary_constructors_and_protocols(hook: str) -> None:
    assert PreferExplicitValueModelConstruction().check(_PATH, _DATACLASS + _HOOK.replace("__post_init__", hook)) == []


def test_preserves_native_validators() -> None:
    source = (
        "from pydantic import BaseModel, field_validator, model_validator\n"
        "class Value(BaseModel):\n"
        "    count: int\n"
        "    @field_validator('count')\n"
        "    @classmethod\n"
        "    def check_count(cls, count: int) -> int:\n"
        "        return count\n"
        "    @model_validator(mode='after')\n"
        "    def check_fields(self):\n"
        "        return self\n"
    )
    assert PreferExplicitValueModelConstruction().check(_PATH, source) == []


def test_reports_each_direct_hook_at_its_declaration() -> None:
    source = _DATACLASS + _HOOK + _HOOK.replace("__post_init__", "model_post_init")
    findings = PreferExplicitValueModelConstruction().check(_PATH, source)
    assert [(finding.line, finding.col) for finding in findings] == [(4, 5), (6, 5)]


@pytest.mark.parametrize(("code", "expected"), [("SARJ572", 0), ("SARJ530", 1)])
def test_respects_only_exact_suppressions(code: str, expected: int) -> None:
    source = _DATACLASS + _HOOK.replace(" -> None:", f" -> None:  # sarj-noqa: {code} -- Required framework contract.")
    assert len(PreferExplicitValueModelConstruction().check(_PATH, source)) == expected


def test_skips_generated_sources() -> None:
    assert PreferExplicitValueModelConstruction().check(Path("generated/models.py"), _DATACLASS + _HOOK) == []


def test_follows_source_visible_imported_pydantic_ancestry(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    parent = tmp_path / "base.py"
    path = tmp_path / "models.py"
    parent_source = "from pydantic import BaseModel\nclass Parent(BaseModel):\n    pass\n"
    source = "from base import Parent\nclass Value(Parent):\n" + _HOOK
    rule = PreferExplicitValueModelConstruction()
    rule.prepare(ProjectIndexSet.build([parent, path], {parent: parent_source, path: source}))
    assert len(rule.check(path, source)) == 1


def test_abstains_for_shadowed_foreign_model_ancestry(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    parent = tmp_path / "base.py"
    path = tmp_path / "models.py"
    parent_source = "from pydantic import BaseModel\nBaseModel = Custom\nclass Parent(BaseModel):\n    pass\n"
    source = "from base import Parent\nclass Value(Parent):\n" + _HOOK
    rule = PreferExplicitValueModelConstruction()
    rule.prepare(ProjectIndexSet.build([parent, path], {parent: parent_source, path: source}))
    assert rule.check(path, source) == []


def test_postinit_observation_is_not_constructor_field_advice() -> None:
    source = (
        "from dataclasses import dataclass, field\n"
        "@dataclass\nclass Context:\n"
        "    cues: list[str] = field(default_factory=list)\n"
        "    def __post_init__(self): self.publish()\n"
        "    def publish(self): remember(tuple(self.cues))\n"
        "def make():\n    value = Context()\n    value.cues = ['new']\n    return value\n"
    )
    findings = PreferExplicitValueModelConstruction().check(Path("app/context.py"), source)
    assert len(findings) == 1
    assert findings[0].line == 5
