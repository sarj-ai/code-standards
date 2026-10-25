from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, ValidationError
import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules.prefer_typed_settings_field import PreferTypedSettingsField


class _RawPositiveInt(BaseModel):
    count: int = Field(default=1, gt=0)


class _DomainPositiveInt(BaseModel):
    count: PositiveInt = 1


class _RawNonNegativeInt(BaseModel):
    count: int = Field(default=0, ge=0)


class _DomainNonNegativeInt(BaseModel):
    count: NonNegativeInt = 0


class _RawPositiveFloat(BaseModel):
    count: float = Field(default=1.0, gt=0)


class _DomainPositiveFloat(BaseModel):
    count: PositiveFloat = 1.0


class _RawNonNegativeFloat(BaseModel):
    count: float = Field(default=0.0, ge=0)


class _DomainNonNegativeFloat(BaseModel):
    count: NonNegativeFloat = 0.0


_CASES = (
    (_RawPositiveInt, _DomainPositiveInt, "int", "gt", (1, 3), 0),
    (_RawNonNegativeInt, _DomainNonNegativeInt, "int", "ge", (0, 3), -1),
    (_RawPositiveFloat, _DomainPositiveFloat, "float", "gt", (1.0, 2.5), 0),
    (_RawNonNegativeFloat, _DomainNonNegativeFloat, "float", "ge", (0.0, 2.5), -1),
)


@pytest.mark.parametrize(("raw", "domain", "carrier", "bound", "accepted", "rejected"), _CASES)
def test_equal_numeric_validation_does_not_authorize_changing_public_annotations(
    *,
    raw: type[BaseModel],
    domain: type[BaseModel],
    carrier: str,
    bound: str,
    accepted: tuple[int | float, ...],
    rejected: float,
) -> None:
    # These real Pydantic models isolate its numeric field/annotation contract.
    # No BaseSettings package or environment-source equivalence is simulated.
    for value in accepted:
        original = raw.model_validate({"count": value})
        narrowed = domain.model_validate({"count": value})
        assert original.model_dump() == narrowed.model_dump()
    with pytest.raises(ValidationError) as original_error:
        raw.model_validate({"count": rejected})
    with pytest.raises(ValidationError) as narrowed_error:
        domain.model_validate({"count": rejected})
    assert original_error.value.errors(include_url=False) == narrowed_error.value.errors(include_url=False)
    assert raw.model_json_schema()["properties"] == domain.model_json_schema()["properties"]
    assert raw.model_fields["count"].annotation is domain.model_fields["count"].annotation

    original_annotations = dict[str, object](get_type_hints(raw, include_extras=True))
    narrowed_annotations = dict[str, object](get_type_hints(domain, include_extras=True))
    original_annotation = original_annotations["count"]
    narrowed_annotation = narrowed_annotations["count"]
    assert original_annotation is (int if carrier == "int" else float)
    assert narrowed_annotation != original_annotation

    # The actual source-only settings detector has the same numeric finding.
    # The writer must preserve that public annotation until its owner reviews it.
    default = "1" if carrier == "int" else "1.0"
    source = (
        "from pydantic import Field\n"
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        f"    count: {carrier} = Field(default={default}, {bound}=0)\n"
    )
    path = Path("app/settings.py")
    assert len(PreferTypedSettingsField().check(path, source)) == 1
    assert fix_source(path, source, rule_ids=["prefer-typed-settings-field"]) == source
