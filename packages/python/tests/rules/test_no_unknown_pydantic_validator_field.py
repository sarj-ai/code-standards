from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_unknown_pydantic_validator_field import NoUnknownPydanticValidatorField


_PREFIX = "from pydantic import BaseModel, field_validator, field_serializer, computed_field\n"


@pytest.mark.parametrize("decorator", ["field_validator", "field_serializer"], ids=["validator", "serializer"])
@pytest.mark.parametrize(
    ("arguments", "count"),
    [
        pytest.param('"missing"', 1, id="missing"),
        pytest.param('"value", "missing"', 1, id="mixed"),
        pytest.param('"missing", "other"', 1, id="one-diagnostic"),
        pytest.param('"value"', 0, id="present"),
        pytest.param('"*"', 0, id="wildcard"),
        pytest.param('"missing", check_fields=False', 0, id="deferred"),
        pytest.param('"missing", check_fields=flag', 0, id="unknown-check"),
        pytest.param('"missing", **options', 0, id="unknown-options"),
        pytest.param("*fields", 0, id="unpacked"),
        pytest.param("field_name", 0, id="dynamic"),
    ],
)
def test_field_targets(decorator: str, arguments: str, count: int) -> None:
    source = _PREFIX + (
        "class Model(BaseModel):\n    value: int\n"
        f"    @{decorator}({arguments})\n    @classmethod\n    def check(cls, value: int) -> int:\n        return value\n"
    )
    assert len(NoUnknownPydanticValidatorField().check(Path("app/models.py"), source)) == count


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "class Model(Parent):\n    @field_validator('missing')\n    def check(cls, value): return value",
            id="unknown-parent",
        ),
        pytest.param(
            "@adapt\nclass Model(BaseModel):\n    @field_validator('missing')\n    def check(cls, value): return value",
            id="class-wrapper",
        ),
        pytest.param(
            "class Model(BaseModel):\n    @field_validator('missing')\n    @adapt\n    def check(cls, value): return value",
            id="method-wrapper",
        ),
        pytest.param(
            "class Model(BaseModel):\n    if flag:\n        missing: int\n    @field_validator('missing')\n    def check(cls, value): return value",
            id="conditional-field",
        ),
        pytest.param(
            "class Model(BaseModel):\n    @field_validator('missing')\n    def check(cls, value): return value\n    def check(cls, value): return value",
            id="overwritten-method",
        ),
        pytest.param(
            "class Model(BaseModel):\n    @field_validator('missing')  # sarj-noqa: SARJ492 -- invalid schema fixture\n    def check(cls, value): return value",
            id="suppression",
        ),
        pytest.param(
            "class Model(BaseModel):\n    @field_serializer('doubled')\n    def check(self, value): return value\n    @computed_field\n    @property\n    def doubled(self) -> int: return 2",
            id="computed-field",
        ),
        pytest.param(
            "# @generated\nclass Model(BaseModel):\n    @field_validator('missing')\n    def check(cls, value): return value",
            id="generated",
        ),
        pytest.param(
            "class Model(BaseModel):\n    __annotations__ = {'missing': int}\n    @field_validator('missing')\n    def check(cls, value): return value",
            id="dynamic-annotations",
        ),
        pytest.param(
            "import pydantic as p\np.field_validator = lambda *args, **kwargs: lambda function: function\nclass Model(p.BaseModel):\n    @p.field_validator('missing')\n    def check(cls, value): return value",
            id="mutated-import-attribute",
        ),
    ],
)
def test_uncertain_contracts(body: str) -> None:
    assert not NoUnknownPydanticValidatorField().check(
        Path("app/models.py"),
        ("# @generated\n" + _PREFIX + body.removeprefix("# @generated\n"))
        if body.startswith("# @generated")
        else _PREFIX + body,
    )


def test_documented_examples() -> None:
    verify_native_rule(NoUnknownPydanticValidatorField, analyze)


@pytest.mark.parametrize(
    "decorators",
    [
        pytest.param("@classmethod\n    @field_validator('missing')", id="outer-classmethod"),
        pytest.param("@staticmethod\n    @field_validator('missing')", id="outer-staticmethod"),
        pytest.param("@field_serializer('value')\n    @field_serializer('missing')", id="nested-field-decorators"),
    ],
)
def test_hidden_decorator_proxy(decorators: str) -> None:
    source = (
        _PREFIX
        + f"class Model(BaseModel):\n    value: int\n    {decorators}\n    def check(cls, value): return value\n"
    )
    assert not NoUnknownPydanticValidatorField().check(Path("app/models.py"), source)


@pytest.mark.parametrize("annotation", ["declare_missing()", "'declare_missing()'"], ids=["evaluated", "quoted"])
def test_annotation_effects_are_not_inferred(annotation: str) -> None:
    source = (
        _PREFIX
        + f"class Model(BaseModel):\n    value: int\n    @field_validator('missing')\n    def check(cls, value: {annotation}): return value\n"
    )
    assert not NoUnknownPydanticValidatorField().check(Path("app/models.py"), source)


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("from .helpers import field_validator", id="relative"),
        pytest.param("if flag:\n    from helpers import field_validator", id="conditional"),
        pytest.param("from .helpers import classmethod", id="relative-descriptor"),
        pytest.param(
            "import pydantic as p\nalias = p.field_validator\nalias.__code__ = replacement.__code__",
            id="module-member-escape",
        ),
    ],
)
def test_uncertain_decorator_imports(replacement: str) -> None:
    source = (
        _PREFIX
        + replacement
        + "\nclass Model(BaseModel):\n    value: int\n    @field_validator('missing')\n    def check(cls, value): return value\n"
    )
    assert not NoUnknownPydanticValidatorField().check(Path("app/models.py"), source)
