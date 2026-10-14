from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_duplicate_field_validator_body import NoDuplicateFieldValidatorBody


_HEADER = "from pydantic import BaseModel, field_validator\n\nclass Model(BaseModel):\n    a: str\n    b: str\n"


def _validator(name: str, field: str, body: str, *, mode: str = "'before'", parameter: str = "value") -> str:
    return (
        f"    @field_validator('{field}', mode={mode})\n"
        "    @classmethod\n"
        f"    def {name}(cls, {parameter}: str) -> str:\n"
        f"        {body}\n"
    )


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoDuplicateFieldValidatorBody().check(Path("model.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoDuplicateFieldValidatorBody, analyze)


def test_reports_each_later_copy_once() -> None:
    source = (
        _HEADER
        + _validator("one", "a", "return value.strip()")
        + _validator("two", "b", "return value.strip()")
        + _validator("three", "a", "return value.strip()")
    )
    assert _lines(source) == [12, 16]


def test_parameter_names_do_not_hide_a_copy() -> None:
    source = (
        _HEADER
        + _validator("one", "a", "return value.lower()")
        + _validator("two", "b", "return raw.lower()", parameter="raw")
    )
    assert _lines(source) == [12]


def test_leading_docstring_is_ignored() -> None:
    source = (
        _HEADER
        + _validator("one", "a", "'''Normalize.'''\n        return value.lower()")
        + _validator("two", "b", "return value.lower()")
    )
    assert _lines(source) == [13]


def test_reports_aliased_pydantic_import() -> None:
    source = (
        "from pydantic import BaseModel, field_validator as validates\n\nclass Model(BaseModel):\n    a: str\n    b: str\n"
        "    @validates('a')\n    @classmethod\n    def one(cls, value: str) -> str:\n        return value.lower()\n"
        "    @validates('b')\n    @classmethod\n    def two(cls, value: str) -> str:\n        return value.lower()\n"
    )
    assert _lines(source) == [12]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            _HEADER + _validator("one", "a", "return value.strip()") + _validator("two", "b", "return value.lower()"),
            id="different-bodies",
        ),
        pytest.param(
            _HEADER
            + _validator("one", "a", "return value.strip()")
            + _validator("two", "b", "return value.strip()", mode="'after'"),
            id="different-modes",
        ),
        pytest.param(
            "from other import field_validator\n\nclass Model:\n"
            "    @field_validator('a')\n    def one(cls, value): return value.strip()\n"
            "    @field_validator('b')\n    def two(cls, value): return value.strip()\n",
            id="unproven-decorator",
        ),
        pytest.param(
            "from pydantic import BaseModel, field_validator\n\n"
            "class First(BaseModel):\n    a: str\n"
            "    @field_validator('a')\n    @classmethod\n    def one(cls, value: str) -> str:\n        return value.strip()\n"
            "class Second(BaseModel):\n    a: str\n"
            "    @field_validator('a')\n    @classmethod\n    def one(cls, value: str) -> str:\n        return value.strip()\n",
            id="separate-models",
        ),
        pytest.param("from pydantic import field_validator\nclass Model(\n", id="syntax-error"),
    ],
)
def test_allows_distinct_or_unproven_validators(source: str) -> None:
    assert _lines(source) == []
