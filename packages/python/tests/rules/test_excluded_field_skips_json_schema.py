from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.excluded_field_skips_json_schema import ExcludedFieldSkipsJsonSchema


_HEADER = (
    "from typing import Annotated\n\nimport pydantic\nfrom pydantic import BaseModel, Field\n"
    "from pydantic.json_schema import SkipJsonSchema\n\n\nclass Task(BaseModel):\n"
)


def _lines(field: str, path: str = "models.py") -> list[int]:
    return [finding.line for finding in ExcludedFieldSkipsJsonSchema().check(Path(path), f"{_HEADER}    {field}\n")]


def test_documented_examples() -> None:
    verify_native_rule(ExcludedFieldSkipsJsonSchema, analyze)


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("owner: str | None = Field(default=None, exclude=True)", id="default-value"),
        pytest.param("owner: str = pydantic.Field(exclude=True)", id="module-attribute"),
        pytest.param("owner: Annotated[str, Field(exclude=True)] = ''", id="annotated-metadata"),
        pytest.param("owner: str = Field(\n        default='',\n        exclude=True,\n    )", id="multiline"),
    ],
)
def test_reports_schema_visible_excluded_field(field: str) -> None:
    assert _lines(field) == [9]


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("owner: SkipJsonSchema[str | None] = Field(default=None, exclude=True)", id="skip-wrapper"),
        pytest.param("owner: Annotated[str, SkipJsonSchema()] = Field(exclude=True)", id="skip-metadata"),
        pytest.param("owner: str = Field(default='', exclude=False)", id="not-excluded"),
        pytest.param("owner: str = Field(default='', exclude=EXCLUDED)", id="dynamic-exclude"),
        pytest.param("owner: str = Field(default='')", id="plain-field"),
        pytest.param("owner = Field(exclude=True)", id="unannotated"),
    ],
)
def test_allows_schema_hidden_or_included_fields(field: str) -> None:
    assert _lines(field) == []


def test_ignores_field_outside_a_class_body() -> None:
    source = "from pydantic import Field\n\nHIDDEN = Field(exclude=True)\n"
    assert ExcludedFieldSkipsJsonSchema().check(Path("models.py"), source) == []


def test_ignores_unrelated_field_helper() -> None:
    source = "from dataclasses import field as Field\n\nclass Task:\n    owner: str = Field(exclude=True)\n"
    assert ExcludedFieldSkipsJsonSchema().check(Path("models.py"), source) == []


def test_skips_test_modules() -> None:
    assert _lines("owner: str = Field(exclude=True)", path="tests/test_models.py") == []
