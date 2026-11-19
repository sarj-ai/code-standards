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


_COLLECTION = PreferExplicitValueModelConstruction.public_examples()[0].focus_file.source


@pytest.mark.parametrize(
    "options",
    [
        "default_factory=list",
        "default_factory=list, repr=False",
        "default_factory=list, repr=True, compare=False, hash=None, kw_only=True, init=True",
        "default_factory=list, hash=False",
    ],
)
def test_literal_field_metadata_keeps_collection_constructor_eligibility(options: str) -> None:
    source = _COLLECTION.replace("default_factory=list, repr=False", options)
    [finding] = PreferExplicitValueModelConstruction().check(_PATH, source)
    assert finding.severity is Severity.WARNING
    assert "list field" in finding.message


@pytest.mark.parametrize(
    "options",
    [
        "default_factory=list, init=False",
        "default_factory=list, repr=enabled",
        "default_factory=list, hash=1",
        "default_factory=list, metadata=external_metadata",
        "default_factory=list, **options",
    ],
)
def test_unknown_field_options_and_nonconstructor_fields_abstain(options: str) -> None:
    source = _COLLECTION.replace("default_factory=list, repr=False", options)
    assert PreferExplicitValueModelConstruction().check(_PATH, source) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("@dataclass", "@dataclass(frozen=True)"),
        ("default_factory=list", "default_factory=list, init=False"),
        ("value = Context()", "value = Context(cues=[])"),
        ("value = Context()", "value = Context()\n    expose(value)"),
        ("['One moment.']", "build_cues()"),
        ("if enabled:", "if effect():"),
        ("cues: list[str]", "cues: object"),
    ],
)
def test_collection_initialization_preserves_effects_defaults_and_constructor_contracts(old: str, new: str) -> None:
    source = _COLLECTION.replace(old, new)
    assert PreferExplicitValueModelConstruction().check(_PATH, source) == []


def test_direct_hook_observation_excludes_the_collection_advice() -> None:
    source = _COLLECTION.replace(
        "def context(", "    def __post_init__(self):\n        observe(self.cues)\ndef context("
    )
    findings = PreferExplicitValueModelConstruction().check(_PATH, source)
    assert len(findings) == 1
    assert "hook" in findings[0].message


def test_collection_advice_has_no_fix_and_uses_its_own_location() -> None:
    [finding] = PreferExplicitValueModelConstruction().check(_PATH, _COLLECTION)
    assert "hook observation timing" in finding.message
    assert finding.fixes == ()
    suppressed = _COLLECTION
    suppressed = suppressed.replace(
        "        value.cues = ['One moment.']",
        "        value.cues = ['One moment.']  # sarj-noqa: SARJ572 -- Preserve initialization order.",
    )
    assert PreferExplicitValueModelConstruction().check(_PATH, suppressed) == []


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
