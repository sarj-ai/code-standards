from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import Severity

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes
from sarj_python_lint.rules.prefer_typed_settings_field import PreferTypedSettingsField


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("duration_seconds: float", "PositiveFloat"),
        ("samples: int", "PositiveInt"),
        ("duration_seconds: float = Field(default=60, ge=1, le=120)", "PositiveFloat"),
        ("elapsed: float = Field(ge=0)", "NonNegativeFloat"),
        ("voice: str = 'voice_a'", "StrEnum"),
        ("mode: str = Field(default='streaming')", "StrEnum"),
        ("voice: str = Field(default='voice_a', alias='VOICE')", "StrEnum"),
    ],
)
@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
def test_model_fields_declare_numeric_and_string_domains(field: str, expected: str, base: str) -> None:
    source = (
        "from pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Config({base}):\n    {field}\n"
    )
    findings = PreferTypedSettingsField().check(Path("app/models.py"), source)
    assert len(findings) == 1
    assert expected in findings[0].message
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "field",
    [
        "duration: PositiveFloat",
        "count: NonNegativeInt = 0",
        "mode: Mode = Mode.STREAMING",
        "message: str = 'Welcome to this service.'",
        "token: str = ''",
        "delta: Annotated[float, Field(ge=-10, le=10)]",
        "temperature: float = Field(ge=-273.15)",
    ],
)
def test_explicit_domains_and_open_text_remain_valid(field: str) -> None:
    source = (
        "from typing import Annotated\nfrom enum import StrEnum\n"
        "from pydantic import BaseModel, Field, PositiveFloat, NonNegativeInt\n"
        "class Mode(StrEnum):\n    STREAMING = 'streaming'\n"
        "class Config(BaseModel):\n    " + field + "\n"
    )
    assert PreferTypedSettingsField().check(Path("app/models.py"), source) == []


@pytest.mark.parametrize("pattern", ["r'^item-[0-9]+$'", "'[a-z]+'"])
def test_a_single_pattern_validated_identifier_retains_nominal_identity(pattern: str) -> None:
    source = (
        "from pydantic import BaseModel, Field\n"
        "class StreamItem(BaseModel):\n"
        f"    result_id: str = Field(pattern={pattern})\n"
    )
    findings = PreferNominalIdTypes().check(Path("app/models.py"), source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "nominal ID" in findings[0].message


@pytest.mark.parametrize(
    "body",
    [
        "class StreamItem[Field](BaseModel):\n    result_id: str = Field(pattern='[a-z]+')\n",
        "class StreamItem(BaseModel):\n    Field = custom\n    result_id: str = Field(pattern='[a-z]+')\n",
        "class StreamItem[BaseModel](BaseModel):\n    result_id: str = Field(pattern='[a-z]+')\n",
    ],
)
def test_pattern_id_requires_the_actual_pydantic_provider(body: str) -> None:
    source = "from pydantic import BaseModel, Field\n" + body
    assert PreferNominalIdTypes().check(Path("app/models.py"), source) == []


def test_stronger_dependency_owns_its_model_without_hiding_other_outcomes(tmp_path: Path) -> None:
    source = (
        "from typing import Literal, Self\nfrom pydantic import BaseModel, model_validator\n"
        "class Result(BaseModel):\n"
        "    kind: Literal['success', 'error']\n"
        "    value: str | None = None\n"
        "    error: str | None = None\n"
        "    @model_validator(mode='after')\n"
        "    def validate_value(self) -> Self:\n"
        "        if self.kind == 'success' and self.value is None:\n"
        "            raise ValueError('Success requires a value')\n"
        "        return self\n"
    )
    source += "class OtherResult(BaseModel):\n    passed: bool\n    error: str | None = None\n"
    path = tmp_path / "models.py"
    path.write_text(source)
    findings = analyze(["prefer-discriminated-model-union", "prefer-outcome-variants"], [path], root=tmp_path)
    assert [(finding.code, finding.severity) for finding in findings] == [
        ("SARJ510", Severity.ERROR),
        ("SARJ571", Severity.WARNING),
    ]
