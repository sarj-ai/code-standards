from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_nested_pydantic_field_validator import NoNestedPydanticFieldValidator


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "models.py"):
    return NoNestedPydanticFieldValidator().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = NoNestedPydanticFieldValidator.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoNestedPydanticFieldValidator().check(Path(focus.path), focus.source)) == example.expected_count


def test_reports_validator_accidentally_owned_by_nested_class() -> None:
    findings = _check(
        """
        from pydantic import BaseModel, field_validator
        class Settings(BaseModel):
            language: str
            class Config:
                extra = "forbid"
                @field_validator("language")
                @classmethod
                def validate_language(cls, value):
                    return value.lower()
        """
    )
    assert len(findings) == 1
    assert findings[0].code == "SARJ424"


@pytest.mark.parametrize(
    "source",
    [
        """
        from pydantic import BaseModel, field_validator
        class Settings(BaseModel):
            language: str
            @field_validator("language")
            @classmethod
            def validate_language(cls, value):
                return value.lower()
            class Config:
                extra = "forbid"
        """,
        """
        from pydantic import BaseModel, field_validator
        class Outer(BaseModel):
            language: str
            class Inner(BaseModel):
                language: str
                @field_validator("language")
                @classmethod
                def validate_language(cls, value):
                    return value.lower()
        """,
        """
        from pydantic import BaseModel
        class Settings(BaseModel):
            language: str
            class Config:
                extra = "forbid"
        """,
    ],
)
def test_ignores_correctly_owned_or_unrelated_nested_classes(source: str) -> None:
    assert _check(source) == []


def test_handles_aliased_imports_and_multiple_outer_fields() -> None:
    findings = _check(
        """
        import pydantic as pd
        class Settings(pd.BaseModel):
            language: str
            timezone: str
            class LegacyConfig:
                @pd.field_validator("language", "timezone", mode="before")
                @classmethod
                def normalize(cls, value):
                    return value.strip()
        """
    )
    assert len(findings) == 1
    assert "language" in findings[0].message
    assert "timezone" in findings[0].message
