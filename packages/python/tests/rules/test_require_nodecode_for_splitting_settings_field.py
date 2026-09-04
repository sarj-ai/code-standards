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
    assert findings[0].code == "SARJ424"
    assert findings[0].severity == "warning"
    assert "split_" in findings[0].message


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
    assert findings[0].code == "SARJ424"


def test_excludes_ambiguous_multi_field_validator() -> None:
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
    assert _check(source) == []


def test_reports_field_only_once_across_multiple_validators() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails_again(cls, value):
                return value.split(";")
    """
    assert len(_check(source)) == 1


def test_class_keyword_can_disable_decoding() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings, enable_decoding=False):
            emails: list[str]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
    """
    assert _check(source) == []


def test_explicit_config_after_unknown_unpack_disables_decoding() -> None:
    config = 'model_config = {**BASE_CONFIG, "enable_decoding": False}'
    assert _check(_settings_with_config(config)) == []


def test_unknown_unpack_after_explicit_config_does_not_prove_decoding_disabled() -> None:
    config = 'model_config = {"enable_decoding": False, **BASE_CONFIG}'
    assert len(_check(_settings_with_config(config))) == 1


def test_nested_force_decode_retains_finding_when_class_disables_decoding() -> None:
    source = """
        from typing import Annotated
        from pydantic import field_validator
        from pydantic_settings import BaseSettings, ForceDecode, SettingsConfigDict
        class Settings(BaseSettings):
            model_config = SettingsConfigDict(enable_decoding=False)
            emails: Annotated[Annotated[list[str], ForceDecode], "documented"]
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):
                return value.split(",")
    """
    assert len(_check(source)) == 1


def test_value_and_info_signature_uses_first_parameter_as_value() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            @field_validator("emails", mode="before")
            @staticmethod
            def split_emails(value, info):
                return value.split(",")
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("method_decorator", "signature", "split_target", "expected"),
    [
        ("classmethod", "kls, value", "value", 1),
        ("staticmethod", "cls, info", "cls", 1),
        ("staticmethod", "self", "self", 1),
        ("staticmethod", "context, value", "value", 0),
    ],
)
def test_value_parameter_follows_method_decorator(
    method_decorator: str,
    signature: str,
    split_target: str,
    expected: int,
) -> None:
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            @field_validator("emails", mode="before")
            @{method_decorator}
            def split_emails({signature}):
                return {split_target}.split(",")
    """
    assert len(_check(source)) == expected


def test_conditional_programmatic_init_splitter_is_excluded() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def accept_init_csv(cls, value):
                if isinstance(value, str) and not value.startswith("["):
                    return value.split(",")
                return value
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "expression",
    [
        'value.split(",") if isinstance(value, str) else value',
        'isinstance(value, str) and value.split(",") or value',
        'next((value.split(",") for _ in ()), value)',
        'False and value.split(",")',
    ],
)
def test_conditional_or_lazy_return_splitter_is_excluded(expression: str) -> None:
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def split_values(cls, value):
                return {expression}
    """
    assert _check(source) == []


def test_all_literal_validator_targets_must_name_one_field() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]
            label: str
            @field_validator("emails", "label", mode="before")
            @classmethod
            def split_values(cls, value):
                return value.split(",")
    """
    assert _check(source) == []


@pytest.mark.parametrize("extra_target", ["OTHER", "*FIELDS"])
def test_dynamic_validator_targets_are_not_assumed_single_field(extra_target: str) -> None:
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        OTHER = "label"
        FIELDS = ("label",)
        class Settings(BaseSettings):
            emails: list[str]
            label: str
            @field_validator("emails", {extra_target}, mode="before")
            @classmethod
            def split_values(cls, value):
                return value.split(",")
    """
    assert _check(source) == []


@pytest.mark.parametrize("attribute", ["value . split"])
def test_split_prefilter_does_not_depend_on_attribute_spacing(attribute: str) -> None:
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def split_values(cls, value):
                return {attribute}(",")
    """
    assert len(_check(source)) == 1


def test_split_prefilter_allows_explicit_line_continuation() -> None:
    source = """
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def split_values(cls, value):
                return value. \\
                    split(",")
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize("config_import", ["from pydantic import ConfigDict", "import pydantic as pd"])
def test_pydantic_config_dict_can_disable_decoding(config_import: str) -> None:
    config_call = "pd.ConfigDict" if " as pd" in config_import else "ConfigDict"
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        {config_import}
        class Settings(BaseSettings):
            model_config = {config_call}(enable_decoding=False)
            values: list[str]
            @field_validator("values", mode="before")
            @classmethod
            def split_values(cls, value):
                return value.split(",")
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    ("field_suffix", "validator_suffix", "expected"),
    [
        ("  # sarj-noqa: SARJ424", "", 0),
        ("", "  # sarj-noqa: SARJ424", 0),
        ("  # sarj-noqa: SARJ999", "", 1),
        ("", "  # sarj-noqa: SARJ999", 1),
    ],
)
def test_exact_suppression(
    field_suffix: str,
    validator_suffix: str,
    expected: int,
) -> None:
    source = f"""
        from pydantic import field_validator
        from pydantic_settings import BaseSettings
        class Settings(BaseSettings):
            emails: list[str]{field_suffix}
            @field_validator("emails", mode="before")
            @classmethod
            def split_emails(cls, value):{validator_suffix}
                return value.split(",")
    """
    assert len(_check(source)) == expected
