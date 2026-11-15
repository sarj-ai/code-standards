from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import Severity
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_hidden_settings_input import RequireHiddenSettingsInput


_PATH = Path("app/settings.py")
_HEADER = (
    "from pathlib import Path\n"
    "from typing import Annotated, ClassVar, Optional\n"
    "from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretBytes, SecretStr\n"
    "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
)
_HIDDEN = "    model_config = SettingsConfigDict(hide_input_in_errors=True)\n"
_HIDDEN_MIXIN = "class HiddenInputs(BaseModel):\n    model_config = ConfigDict(hide_input_in_errors=True)\n"
_SHOWN_MIXIN = "class ShownInputs(BaseModel):\n    model_config = ConfigDict(hide_input_in_errors=False)\n"


def _findings(source: str) -> list[tuple[int, str]]:
    return [(finding.line, finding.message) for finding in RequireHiddenSettingsInput().check(_PATH, _HEADER + source)]


def _flagged_lines(source: str) -> list[int]:
    offset = _HEADER.count("\n")
    return [line - offset for line, _ in _findings(source)]


def test_documented_examples() -> None:
    verify_native_rule(RequireHiddenSettingsInput, analyze)


@pytest.mark.parametrize(
    "field",
    [
        "api_token: SecretStr",
        "signing_key: SecretBytes",
        "anything: SecretStr | None = None",
        "anything: Optional[SecretStr] = None",
        "anything: Annotated[SecretStr, Field(min_length=8)]",
        "client_secret: str",
        "webhook_secret: str | None = None",
        "openai_api_key: str = ''",
        "value: str = Field(alias='ZOHO_CLIENT_SECRET')",
        "value: str | None = Field(default=None, validation_alias=AliasChoices('TELEPHONY_API_KEY', 'LEGACY'))",
        "value: Annotated[str, Field(alias='METRICS_BEARER_TOKEN')]",
        "raw_password: bytes",
    ],
)
def test_reports_secret_fields_without_hidden_inputs(field: str) -> None:
    findings = RequireHiddenSettingsInput().check(_PATH, _HEADER + f"class Settings(BaseSettings):\n    {field}\n")
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "Settings" in findings[0].message
    assert "hide_input_in_errors=True" in findings[0].message


@pytest.mark.parametrize(
    "field",
    [
        "google_application_credentials: Path | None = Field(default=None, alias='GOOGLE_APPLICATION_CREDENTIALS')",
        "credentials: dict[str, str] = {}",
        "password_retries: int = 3",
        "token_enabled: bool = False",
        "api_key_id: str",
        "has_secret: bool = False",
        "public_key: str | None = None",
        "region: str = Field(alias='AWS_REGION')",
        "_cached_token: str = ''",
        "default_token: ClassVar[str] = 'x'",
    ],
)
def test_ignores_fields_that_hold_no_secret_text(field: str) -> None:
    assert _findings(f"class Settings(BaseSettings):\n    {field}\n") == []


def test_names_every_exposed_field_in_one_class_diagnostic() -> None:
    findings = _findings(
        "class Settings(BaseSettings):\n    client_secret: str\n    api_token: SecretStr\n    region: str\n"
    )
    assert len(findings) == 1
    assert "(api_token, client_secret)" in findings[0][1]


@pytest.mark.parametrize(
    "config",
    [
        "    model_config = SettingsConfigDict(hide_input_in_errors=True)\n",
        "    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(frozen=True, hide_input_in_errors=True)\n",
        "    model_config = ConfigDict(hide_input_in_errors=True)\n",
        "    model_config = {'hide_input_in_errors': True}\n",
        "    model_config = dict(hide_input_in_errors=True)\n",
        "    model_config = {**SettingsConfigDict(env_prefix='APP_'), 'hide_input_in_errors': True}\n",
    ],
)
def test_accepts_every_literal_configuration_form(config: str) -> None:
    assert _findings(f"class Settings(BaseSettings):\n{config}    api_token: SecretStr\n") == []


def test_accepts_the_flag_as_a_class_keyword() -> None:
    assert _findings("class Settings(BaseSettings, hide_input_in_errors=True):\n    api_token: SecretStr\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "class Settings(BaseSettings):\n    model_config = SettingsConfigDict(hide_input_in_errors=False)\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    model_config = {'hide_input_in_errors': True, 'hide_input_in_errors': False}\n    api_token: SecretStr\n",
        "class Base(BaseSettings):\n" + _HIDDEN + "class Settings(Base):\n"
        "    model_config = SettingsConfigDict(hide_input_in_errors=False)\n    api_token: SecretStr\n",
        "class Base(BaseSettings):\n"
        + _HIDDEN
        + "class Settings(Base, hide_input_in_errors=False):\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n" + _HIDDEN + "    model_config = SettingsConfigDict(env_prefix='APP_')\n"
        "    model_config = SettingsConfigDict(hide_input_in_errors=False)\n    api_token: SecretStr\n",
    ],
)
def test_reports_an_explicit_false_that_overrides_the_flag(source: str) -> None:
    assert len(_findings(source)) == 1


def test_inherits_the_flag_through_multiple_levels() -> None:
    source = (
        "class Root(BaseSettings):\n"
        + _HIDDEN
        + "class Middle(Root):\n    model_config = SettingsConfigDict(env_prefix='APP_')\n"
        + "class Leaf(Middle):\n    client_secret: str\n"
    )
    assert _findings(source) == []


def test_reports_the_leaf_that_adds_a_secret_below_unflagged_levels() -> None:
    source = (
        "class Root(BaseSettings):\n    region: str = 'x'\n"
        "class Middle(Root):\n    model_config = SettingsConfigDict(env_prefix='APP_')\n"
        "class Leaf(Middle):\n    client_secret: str\n"
    )
    assert _flagged_lines(source) == [5]


def test_reports_an_exposure_once_at_the_class_that_declares_it() -> None:
    source = (
        "class Base(BaseSettings):\n    client_secret: str\n"
        "class Inherits(Base):\n    region: str = 'x'\n"
        "class AddsSecret(Base):\n    api_token: SecretStr\n"
    )
    findings = _findings(source)
    offset = _HEADER.count("\n")
    assert [line - offset for line, _ in findings] == [1, 5]
    assert "(api_token)" in findings[1][1]


def test_reports_an_inherited_secret_once_its_owner_is_fixed_but_the_child_reopens_it() -> None:
    source = (
        "class Base(BaseSettings):\n" + _HIDDEN + "    client_secret: str\n"
        "class Child(Base):\n    model_config = SettingsConfigDict(hide_input_in_errors=False)\n"
    )
    assert _flagged_lines(source) == [4]


def test_drops_an_inherited_secret_that_a_child_redeclares_as_non_secret() -> None:
    source = (
        "class Base(BaseSettings):\n" + _HIDDEN + "    client_secret: str\n"
        "class Child(Base):\n    model_config = SettingsConfigDict(hide_input_in_errors=False)\n"
        "    client_secret: Path\n"
    )
    assert _findings(source) == []


@pytest.mark.parametrize(
    "bases",
    ["HiddenInputs, BaseSettings", "BaseSettings, HiddenInputs", "ShownInputs, HiddenInputs, BaseSettings"],
)
def test_accepts_a_mixin_that_supplies_the_flag_last(bases: str) -> None:
    source = _HIDDEN_MIXIN + _SHOWN_MIXIN + f"class Settings({bases}):\n    api_token: SecretStr\n"
    assert _findings(source) == []


def test_reports_when_a_later_mixin_turns_the_flag_off() -> None:
    source = (
        _HIDDEN_MIXIN
        + _SHOWN_MIXIN
        + "class Settings(HiddenInputs, ShownInputs, BaseSettings):\n    api_token: SecretStr\n"
    )
    assert _flagged_lines(source) == [5]


def test_reports_a_secret_declared_on_a_plain_model_mixin() -> None:
    source = "class Credentials(BaseModel):\n    api_token: str\nclass Settings(Credentials, BaseSettings):\n    region: str\n"
    assert _flagged_lines(source) == [3]


@pytest.mark.parametrize(
    "source",
    [
        "class Settings(BaseModel):\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    region: str\n    enabled: bool = False\n",
        "class Settings:\n    api_token: str\n",
    ],
)
def test_ignores_models_and_settings_without_both_conditions(source: str) -> None:
    assert _findings(source) == []


@pytest.mark.parametrize(
    "header",
    [
        "from pydantic_settings import BaseSettings as AppSettings\nfrom pydantic import SecretStr\n",
        "import pydantic_settings as ps\nimport pydantic\n",
        "from pydantic_settings.main import BaseSettings as AppSettings\nfrom pydantic.types import SecretStr\n",
    ],
)
def test_resolves_aliased_provider_imports(header: str) -> None:
    base = "ps.BaseSettings" if "as ps" in header else "AppSettings"
    secret = "pydantic.SecretStr" if "import pydantic\n" in header else "SecretStr"
    source = header + f"class Settings({base}):\n    api_token: {secret}\n"
    assert len(RequireHiddenSettingsInput().check(_PATH, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic.v1 import BaseSettings\nclass Settings(BaseSettings):\n    api_token: str\n",
        "class BaseSettings:\n    pass\nclass Settings(BaseSettings):\n    api_token: str\n",
        "from vendor import SharedSettings\nclass Settings(SharedSettings):\n    api_token: str\n",
        "from pydantic_settings import BaseSettings\nfrom vendor import Mixin\nclass Settings(Mixin, BaseSettings):\n    api_token: str\n",
        "from pydantic_settings import *\nclass Settings(BaseSettings):\n    api_token: str\n",
    ],
)
def test_abstains_without_a_provable_settings_identity(source: str) -> None:
    assert RequireHiddenSettingsInput().check(_PATH, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Settings(BaseSettings):\n    model_config = build_config()\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    model_config = {'hide_input_in_errors': True, **shared}\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    model_config = SettingsConfigDict(hide_input_in_errors=HIDE)\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    model_config = SettingsConfigDict(**shared)\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    model_config = SettingsConfigDict()\n    model_config |= shared\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    class Config:\n        hide_input_in_errors = True\n    api_token: SecretStr\n",
        "class Settings(BaseSettings, metaclass=Meta):\n    api_token: SecretStr\n",
        "class Settings(BaseSettings):\n    api_token: SecretStr\nSettings.model_config['hide_input_in_errors'] = True\n",
        "@decorate\nclass Settings(BaseSettings):\n    api_token: SecretStr\n",
        "class Base(BaseSettings):\n    model_config = build_config()\nclass Settings(Base):\n    api_token: SecretStr\n",
    ],
)
def test_abstains_on_opaque_configuration(source: str) -> None:
    assert _findings(source) == []


def test_terminates_on_cyclic_ancestry() -> None:
    assert _findings("class A(B):\n    api_token: str\nclass B(A):\n    api_token: str\n") == []


@pytest.mark.parametrize(("code", "expected"), [("SARJ575", 0), ("SARJ574", 1)])
def test_respects_only_exact_suppressions(code: str, expected: int) -> None:
    source = f"class Settings(BaseSettings):  # sarj-noqa: {code} -- Local fixture uses dummy values.\n    api_token: SecretStr\n"
    assert len(_findings(source)) == expected


def test_skips_generated_sources() -> None:
    source = _HEADER + "class Settings(BaseSettings):\n    api_token: SecretStr\n"
    assert RequireHiddenSettingsInput().check(Path("generated/settings.py"), source) == []


def _project_findings(tmp_path: Path, base_source: str, source: str) -> int:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    base = tmp_path / "base.py"
    path = tmp_path / "settings.py"
    rule = RequireHiddenSettingsInput()
    rule.prepare(ProjectIndexSet.build([base, path], {base: base_source, path: source}))
    return len(rule.check(path, source))


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("    model_config = SettingsConfigDict(hide_input_in_errors=True)\n", 0),
        ("    model_config = SettingsConfigDict(env_prefix='APP_')\n", 1),
    ],
)
def test_follows_imported_settings_bases(tmp_path: Path, config: str, expected: int) -> None:
    base_source = (
        "from pydantic_settings import BaseSettings, SettingsConfigDict\nclass GroupedSettings(BaseSettings):\n"
        + config
    )
    source = (
        "from pydantic_settings import SettingsConfigDict\nfrom base import GroupedSettings\n"
        "class AgentSettings(GroupedSettings):\n    model_config = SettingsConfigDict(env_prefix='AGENT_')\n"
        "    api_key: str\n"
    )
    assert _project_findings(tmp_path, base_source, source) == expected


def test_abstains_for_a_shadowed_imported_settings_base(tmp_path: Path) -> None:
    base_source = (
        "from pydantic_settings import BaseSettings\nBaseSettings = object\nclass Shared(BaseSettings):\n    pass\n"
    )
    source = "from base import Shared\nclass Settings(Shared):\n    api_key: str\n"
    assert _project_findings(tmp_path, base_source, source) == 0
