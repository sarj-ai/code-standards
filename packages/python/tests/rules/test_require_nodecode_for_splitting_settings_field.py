from __future__ import annotations

from pathlib import Path
from textwrap import dedent, indent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_nodecode_for_splitting_settings_field import (
    RequireNoDecodeForSplittingSettingsField,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "settings.py"):
    return RequireNoDecodeForSplittingSettingsField().check(Path(path), dedent(source))


def _settings_with_config(config: str) -> str:
    config_block = indent(dedent(config).strip(), "    ")
    return f"""\
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
DECODING_ENABLED = False
def make_config(**values):
    return values
class Settings(BaseSettings):
    emails: list[str]
{config_block}
    @field_validator("emails", mode="before")
    @classmethod
    def split_emails(cls, value):
        return value.split(",")
"""


_PUBLIC_EXAMPLES = RequireNoDecodeForSplittingSettingsField.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert (
        len(RequireNoDecodeForSplittingSettingsField().check(Path(focus.path), focus.source)) == example.expected_count
    )


@pytest.mark.parametrize(
    "source",
    [
        """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
        """,
        """
        import pydantic as pd
        import pydantic_settings as ps
        class Settings(ps.BaseSettings):
            groups: dict[str, str]
            @pd.field_validator("groups", mode="before")
            @classmethod
            def split_groups(cls, raw):
                return dict(item.split("=", 1) for item in raw.split(","))
        """,
    ],
)
def test_reports_raw_splitter_without_nodecode(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ423"


@pytest.mark.parametrize(
    "source",
    [
        """
        from typing import Annotated
        from pydantic import field_validator
        from pydantic_settings import BaseSettings, NoDecode
        class Settings(BaseSettings):
            emails: Annotated[list[str], NoDecode]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
        """,
        """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            retries: int
            @field_validator("retries", mode="before")
            @classmethod
            def parse_retries(cls, value):
                return int(value)
        """,
        """
        from pydantic import BaseModel, field_validator
        class Payload(BaseModel):
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def split_values(cls, value):
                return value.split(",")
        """,
        """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            values: list[str]
            @field_validator("values", mode="after")
            @classmethod
            def normalize(cls, value):
                return sorted(value)
        """,
    ],
)
def test_ignores_safe_or_unrelated_validators(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "config",
    [
        "model_config = SettingsConfigDict(enable_decoding=False)",
        'model_config = {"enable_decoding": False}',
        "model_config = dict(enable_decoding=False)",
        "class Config:\n    enable_decoding = False",
        "class Config:\n    enable_decoding: bool = False",
    ],
)
def test_ignores_settings_classes_that_statically_disable_decoding(config: str) -> None:
    assert _check(_settings_with_config(config)) == []


@pytest.mark.parametrize(
    "config",
    [
        "model_config = SettingsConfigDict(enable_decoding=True)",
        'model_config = {"enable_decoding": DECODING_ENABLED}',
        "model_config = make_config(enable_decoding=False)",
        "class Config:\n    enable_decoding = DECODING_ENABLED",
    ],
)
def test_does_not_assume_dynamic_or_unrelated_config_disables_decoding(config: str) -> None:
    assert len(_check(_settings_with_config(config))) == 1


def test_ignores_class_with_custom_settings_sources() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            @classmethod
            def settings_customise_sources(cls, settings_cls, **sources):
                return (sources["env_settings"],)
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
    """
    assert _check(source) == []


def test_force_decode_retains_finding_when_class_disables_decoding() -> None:
    source = """
        from typing import Annotated
        from pydantic import field_validator
        from pydantic_settings import BaseSettings, ForceDecode, SettingsConfigDict
        class Settings(BaseSettings):
            model_config = SettingsConfigDict(enable_decoding=False)
            emails: Annotated[list[str], ForceDecode]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
    """
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ423"


def test_reports_each_affected_field_once() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            groups: tuple[str, ...]
            @field_validator("emails", "groups", mode="before")
            @classmethod
            def split_values(cls, value):
                return value.split(",")
    """
    assert len(_check(source)) == 2
