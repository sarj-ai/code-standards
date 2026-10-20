from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_defaulted_environment_setting import NoDefaultedEnvironmentSetting


_PRELUDE = "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n\nclass Settings(BaseSettings):\n"


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoDefaultedEnvironmentSetting().check(Path("settings.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoDefaultedEnvironmentSetting, analyze)


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("    environment: str = 'local'\n", id="plain-literal"),
        pytest.param("    environment: Env = Env.LOCAL\n", id="enum-member"),
        pytest.param("    environment: str = Field('dev', alias='ENVIRONMENT')\n", id="positional-default"),
        pytest.param("    environment: str = Field(default_factory=pick, alias='ENVIRONMENT')\n", id="factory"),
        pytest.param("    deployment: str = Field(default='dev', alias='ENVIRONMENT')\n", id="alias-only"),
        pytest.param("    ENVIRONMENT: str = Field(default='dev')\n", id="upper-name"),
    ],
)
def test_reports_defaulted_environment(field: str) -> None:
    assert _lines(_PRELUDE + field) == [5]


def test_reports_subclass_of_same_file_settings_class() -> None:
    source = _PRELUDE + "    debug: bool = False\n\nclass Agent(Settings):\n    environment: str = 'local'\n"
    assert _lines(source) == [8]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_PRELUDE + "    environment: str = Field(alias='ENVIRONMENT')\n", id="required-field"),
        pytest.param(_PRELUDE + "    environment: str = Field(..., alias='ENVIRONMENT')\n", id="explicit-ellipsis"),
        pytest.param(_PRELUDE + "    environment: str\n", id="bare-annotation"),
        pytest.param(_PRELUDE + "    region: str = Field(default='me', alias='REGION')\n", id="other-setting"),
        pytest.param(
            "from pydantic import BaseModel\n\nclass Payload(BaseModel):\n    environment: str = 'local'\n",
            id="not-settings",
        ),
        pytest.param(
            "from shared import BaseServiceSettings\n\nclass Settings(BaseServiceSettings):\n    environment: str = 'x'\n",
            id="unproven-base",
        ),
        pytest.param("from pydantic_settings import BaseSettings\nclass Settings(\n", id="syntax-error"),
    ],
)
def test_allows_required_or_unrelated_fields(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("    environment: str | None = None\n", id="optional-none"),
        pytest.param(
            "    environment: Optional[str] = Field(default=None, alias='ENVIRONMENT')\n", id="optional-field-none"
        ),
    ],
)
def test_allows_optional_environment_defaulting_to_none(field: str) -> None:
    assert _lines(f"{_PRELUDE}{field}") == []
