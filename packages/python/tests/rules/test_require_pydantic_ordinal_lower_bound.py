from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_pydantic_ordinal_lower_bound import (
    RequirePydanticOrdinalLowerBound,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/api.py"):
    return RequirePydanticOrdinalLowerBound().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        "class Detail(BaseModel):\n    attempt: int = Field(default=1, description='1 for the first attempt')\n",
        "class Detail(pydantic.BaseModel):\n    index: int = pydantic.Field(default=0, description='0 for first item')\n",
    ],
)
def test_flags_literal_ordinal_contract_without_bound(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ418"


@pytest.mark.parametrize(
    "source",
    [
        "class Detail(BaseModel):\n    attempt: int = Field(default=1, ge=1, description='1 for the first attempt')\n",
        "class Detail(BaseModel):\n    attempt: PositiveInt = Field(default=1, description='1 for the first attempt')\n",
        "class Detail(BaseModel):\n    attempt: int = Field(default=1, description='Attempt number')\n",
        "class Detail(BaseModel):\n    attempt: int = Field(default=2, description='1 for the first attempt')\n",
        "class Plain:\n    attempt: int = Field(default=1, description='1 for the first attempt')\n",
    ],
)
def test_ignores_enforced_or_ambiguous_contracts(source: str) -> None:
    assert _check(source) == []


def test_field_validator_is_an_explicit_escape() -> None:
    source = """
class Detail(BaseModel):
    attempt: int = Field(default=1, description="1 for the first attempt")

    @field_validator("attempt")
    def validate_attempt(cls, value):
        return value
"""
    assert _check(source) == []


@pytest.mark.parametrize("example", RequirePydanticOrdinalLowerBound.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
