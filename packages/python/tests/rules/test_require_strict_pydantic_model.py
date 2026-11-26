from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.require_strict_pydantic_model import RequireStrictPydanticModel


_IMPORTS = "from pydantic import BaseModel, ConfigDict, RootModel\n"
_MODEL_PATH = Path("app/models.py")


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        pytest.param("class Model(BaseModel):\n    count: int\n", [2], id="default"),
        pytest.param("class Model(BaseModel):\n    model_config = ConfigDict(frozen=True)\n", [2], id="config-dict"),
        pytest.param("class Model(BaseModel):\n    model_config = ConfigDict(strict=False)\n", [2], id="explicit-lax"),
        pytest.param("class Model(BaseModel):\n    model_config = {'strict': None}\n", [2], id="null-uses-lax-default"),
        pytest.param("class Model(BaseModel):\n    model_config = {'frozen': True}\n", [2], id="literal-dict"),
        pytest.param("class Model(BaseModel, frozen=True):\n    pass\n", [2], id="class-option"),
        pytest.param(
            "class Parent(BaseModel):\n    pass\nclass Child(Parent):\n    pass\n", [2, 4], id="inherited-lax"
        ),
        pytest.param("import pydantic as p\nclass Model(p.BaseModel):\n    pass\n", [3], id="module-alias"),
        pytest.param("from pydantic import BaseModel as Base\nclass Model(Base):\n    pass\n", [3], id="base-alias"),
        pytest.param(
            "class Parent(BaseModel):\n    model_config = {'strict': True}\n"
            "class Child(Parent, strict=False):\n    model_config = ConfigDict(strict=True)\n",
            [4],
            id="class-keyword-wins",
        ),
        pytest.param(
            "class Left(BaseModel, strict=True):\n    pass\n"
            "class Right(BaseModel, strict=False):\n    pass\n"
            "class Child(Left, Right):\n    pass\n",
            [4, 6],
            id="rightmost-base-wins",
        ),
        pytest.param(
            "class Left(BaseModel, strict=True):\n    pass\n"
            "class Right(BaseModel, frozen=True):\n    pass\n"
            "class Child(Left, Right):\n    pass\n",
            [4],
            id="unset-rightmost-base-preserves-strict",
        ),
        pytest.param("class Model(BaseModel):\n    model_config = ConfigDict(strict=True)\n", [], id="strict-config"),
        pytest.param("class Model(BaseModel, strict=True):\n    pass\n", [], id="strict-keyword"),
        pytest.param(
            "class Parent(BaseModel, strict=True):\n    pass\n"
            "class Child(Parent):\n    model_config = {'frozen': True}\n",
            [],
            id="inherited-strict",
        ),
        pytest.param("class Model(BaseModel):\n    model_config = {'strict': True}\n", [], id="strict-dict"),
    ],
)
def test_effective_configuration(source: str, lines: list[int]) -> None:
    diagnostics = RequireStrictPydanticModel().check(_MODEL_PATH, _IMPORTS + source)

    assert [(issue.line, issue.col, issue.severity) for issue in diagnostics] == [
        (line, 1, Severity.WARNING) for line in lines
    ]
    assert all(not issue.fixes for issue in diagnostics)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from pydantic_settings import BaseSettings\nclass Model(BaseSettings):\n    pass\n", id="settings"
        ),
        pytest.param("class Model(RootModel[int]):\n    pass\n", id="root-model"),
        pytest.param("from external import Parent\nclass Model(Parent, BaseModel):\n    pass\n", id="imported-base"),
        pytest.param("class Model(UnknownBase, BaseModel):\n    pass\n", id="unresolved-base"),
        pytest.param("class Model(BaseModel):\n    model_config = build_config()\n", id="dynamic-config"),
        pytest.param("class Model(BaseModel):\n    model_config = ConfigDict(**options)\n", id="unpacked-config"),
        pytest.param("class Model(BaseModel):\n    model_config = {'strict': flag}\n", id="dynamic-value"),
        pytest.param(
            "class Parent(BaseModel):\n    model_config = ConfigDict()\n"
            "Parent.model_config.update(strict=True)\nclass Child(Parent):\n    count: int\n",
            id="mutated-inherited-config",
        ),
        pytest.param(
            "import pydantic as p\np.BaseModel.model_config.update(strict=True)\n"
            "class Model(p.BaseModel):\n    count: int\n",
            id="mutated-native-base-config",
        ),
        pytest.param("class Model(BaseModel, **options):\n    pass\n", id="unpacked-class-keywords"),
        pytest.param(
            "class Model(BaseModel):\n    if flag:\n        model_config = {'strict': True}\n", id="conditional-config"
        ),
        pytest.param("from external import BaseModel\nclass Model(BaseModel):\n    pass\n", id="same-base-name"),
        pytest.param(
            "from external import ConfigDict\nclass Model(BaseModel):\n    model_config = ConfigDict()\n",
            id="same-config-name",
        ),
        pytest.param(
            "from pydantic.dataclasses import dataclass\n@dataclass\nclass Data:\n    count: int\n",
            id="pydantic-dataclass",
        ),
        pytest.param("class Model(BaseModel):\n    model_config = {\n", id="malformed"),
    ],
)
def test_unresolved_and_unsupported_models(source: str) -> None:
    assert not RequireStrictPydanticModel().check(_MODEL_PATH, _IMPORTS + source)


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        pytest.param("tests/models.py", "", id="test-directory"),
        pytest.param("app/test_models.py", "", id="test-file"),
        pytest.param("app/generated/models.py", "", id="generated-path"),
        pytest.param("app/models.py", "# @generated\n", id="generated-marker"),
    ],
)
def test_file_exclusions(path: str, prefix: str) -> None:
    source = prefix + _IMPORTS + "class Model(BaseModel):\n    count: int\n"
    assert not RequireStrictPydanticModel().check(Path(path), source)


def test_suppression_covers_only_the_class_statement() -> None:
    rule = RequireStrictPydanticModel()
    source = (
        _IMPORTS + f"class Parent(BaseModel):  # sarj-noqa: {rule.code} -- preserve compatible payload coercion\n"
        "    pass\nclass Child(Parent):\n    count: int\n"
    )

    assert [issue.line for issue in rule.check(_MODEL_PATH, source)] == [4]


def test_documented_examples() -> None:
    verify_native_rule(RequireStrictPydanticModel, analyze)
