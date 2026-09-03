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
    assert findings[0].code == "SARJ425"


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
        from pydantic import BaseModel, field_validator
        class DomainModel(BaseModel):
            language: str
        class Outer(BaseModel):
            language: str
            class Inner(DomainModel):
                @field_validator("language")
                @classmethod
                def validate_language(cls, value):
                    return value.lower()
        """,
        """
        from pydantic import BaseModel, field_validator
        from app.models import ProjectModel
        class Outer(BaseModel):
            language: str
            class Inner(ProjectModel):
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


@pytest.mark.parametrize(
    "source",
    [
        """
        from abc import ABC
        from pydantic import BaseModel, field_validator
        class Settings(BaseModel, ABC):
            language: str
            class Helpers:
                @field_validator("language")
                @classmethod
                def normalize(cls, value):
                    return value.lower()
        """,
        """
        from pydantic import BaseModel, validator
        class Settings(BaseModel):
            language: str
            class Config:
                @validator("language")
                def normalize(cls, value):
                    return value.lower()
        """,
        """
        import pydantic.v1 as pydantic
        class Settings(pydantic.BaseModel):
            language: str
            class Config:
                @pydantic.validator("language")
                def normalize(cls, value):
                    return value.lower()
        """,
        """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            language: str
            class Helpers:
                @field_validator("language")
                @classmethod
                def normalize(cls, value):
                    return value.lower()
        """,
        """
        from pydantic import BaseModel, field_validator
        class Settings(BaseModel):
            language: str
            timezone: str
            class Helpers:
                @field_validator("*")
                @classmethod
                def normalize(cls, value):
                    return value.strip()
        """,
    ],
)
def test_reports_safe_additional_validator_shapes(source: str) -> None:
    assert len(_check(source)) == 1


def test_class_var_is_not_a_pydantic_field() -> None:
    source = """
        from typing import ClassVar
        from pydantic import BaseModel, field_validator
        class Settings(BaseModel):
            marker: ClassVar[str]
            class Helpers:
                @field_validator("marker")
                @classmethod
                def normalize(cls, value):
                    return value.lower()
    """
    assert _check(source) == []


@pytest.mark.parametrize("decorator", ["field_validator", "validator"])
def test_check_fields_false_marks_an_intentional_reusable_validator(decorator: str) -> None:
    source = f"""
        from pydantic import BaseModel, {decorator}
        class Settings(BaseModel):
            language: str
            class ValidatorMixin:
                @{decorator}("language", check_fields=False)
                @classmethod
                def normalize(cls, value):
                    return value.lower()
    """
    assert _check(source) == []


def test_unrelated_function_parameter_does_not_shadow_module_import() -> None:
    source = """
        from pydantic import BaseModel, field_validator
        def unrelated(field_validator):
            return field_validator
        class Settings(BaseModel):
            language: str
            class Helpers:
                @field_validator("language")
                @classmethod
                def normalize(cls, value):
                    return value.lower()
    """
    assert len(_check(source)) == 1


def test_relevant_enclosing_function_shadow_abstains() -> None:
    source = """
        from pydantic import BaseModel, field_validator
        def build(field_validator):
            class Settings(BaseModel):
                language: str
                class Helpers:
                    @field_validator("language")
                    @classmethod
                    def normalize(cls, value):
                        return value.lower()
    """
    assert _check(source) == []
