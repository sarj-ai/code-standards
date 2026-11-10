from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
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
        pytest.param(
            "    environment: str = Field(default=..., default_factory=pick, alias='ENVIRONMENT')\n",
            id="required-sentinel-with-factory",
        ),
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
        pytest.param(
            _PRELUDE + "    environment: str = Field(default=..., alias='ENVIRONMENT')\n",
            id="keyword-ellipsis",
        ),
        pytest.param(
            _PRELUDE + "    deployment: str = Field(default=..., alias='ENVIRONMENT')\n",
            id="keyword-ellipsis-alias",
        ),
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


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("environment: Annotated[str, Field(default='prod')]", 1),
        ("deployment: Annotated[str, Field(default='prod', alias='ENVIRONMENT')]", 1),
        ("deployment: Annotated[str, Field(default='prod', validation_alias='ENVIRONMENT')]", 1),
        ("deployment: Annotated[str, Field(alias='ENVIRONMENT')] = 'prod'", 1),
        ("environment: Annotated[Annotated[str, Field(default='prod')], Field(description='selector')]", 1),
        ("environment: Annotated[str, Field(default_factory=str)]", 1),
        ("environment: Annotated[str, Field(default='prod')] = Field(...)", 1),
        ("environment: Annotated[str, Field(default='prod')] = Field(default=...)", 1),
        ("environment: Annotated[str, Field(default_factory=str)] = ...", 1),
        ("environment: Annotated[str, Field(default=None)] = 'prod'", 1),
        ("environment: Annotated[str, Field(default='prod')] = ...", 0),
        ("environment: Annotated[str | None, Field(default='prod')] = None", 0),
        ("environment: Annotated[str | None, Field(default=None)]", 0),
        ("environment: Annotated[str, Field(default_factory=None)]", 0),
        ("environment: str = Field(default_factory=None)", 0),
        ("environment: Annotated[str, Field(default_factory=str)] = Field(default_factory=None)", 0),
        ("environment: Annotated[str, Field(alias='ENVIRONMENT')]", 0),
        ("deployment: Annotated[str, Field(alias='ENVIRONMENT', default='prod')] = Field(alias='STAGE')", 0),
        ("deployment: Annotated[str, Field(validation_alias='ENVIRONMENT', default='prod')] = Field(alias='STAGE')", 0),
        ("deployment: Annotated[str, Field(alias='STAGE', default='prod')] = Field(validation_alias='ENVIRONMENT')", 1),
        ("deployment: Annotated[str, Field(alias='ENVIRONMENT', default='prod')] = Field(validation_alias=None)", 1),
        (
            "deployment: Annotated[str, Field(alias='STAGE', validation_alias='ENVIRONMENT', default='prod')] = Field(validation_alias=None)",
            1,
        ),
        (
            "deployment: Annotated[str, Field(validation_alias='ENVIRONMENT', default='prod')] = Field(validation_alias=None)",
            1,
        ),
        (
            "deployment: Annotated[str, Field(alias='ENVIRONMENT', validation_alias='STAGE', default='prod')] = Field(validation_alias=None)",
            0,
        ),
        ("deployment: Annotated[str, Field(alias='ENVIRONMENT', default='prod')] = Field(alias=None)", 0),
        (
            "deployment: Annotated[str, Field(alias='ENVIRONMENT', default='prod')] = Field(alias='STAGE', validation_alias=None)",
            0,
        ),
        ("deployment: str = Field(default='prod', alias='ENVIRONMENT', validation_alias='STAGE')", 0),
        ("environment: ClassVar[str] = 'prod'", 0),
        ("environment: Annotated[ClassVar[str], Field(default='prod')]", 0),
        ("environment: Final[str] = 'prod'", 0),
        ("_environment: Annotated[str, Field(default='prod')]", 0),
        ("model_config: Annotated[str, Field(alias='ENVIRONMENT', default='prod')]", 0),
        ("environment: Annotated[str, opaque_metadata] = 'prod'", 0),
    ],
)
def test_annotated_defaults_aliases_and_rhs_merging(declaration: str, expected: int) -> None:
    source = (
        "from typing import Annotated, ClassVar, Final\n"
        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings(BaseSettings):\n    {declaration}\n"
    )
    assert len(_lines(source)) == expected


@pytest.mark.parametrize(
    ("imports", "base", "annotation"),
    [
        (
            "from typing import Annotated as Configured\nfrom pydantic import Field as Input\nfrom pydantic_settings import BaseSettings as Root\n",
            "Root",
            "Configured[str, Input(default='prod')]",
        ),
        (
            "import typing_extensions as te\nimport pydantic as pd\nimport pydantic_settings as ps\n",
            "ps.BaseSettings",
            "te.Annotated[str, pd.Field(default='prod')]",
        ),
        (
            "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\ndef unrelated(Field, BaseSettings, Annotated): pass\n",
            "BaseSettings",
            "Annotated[str, Field(default='prod')]",
        ),
        (
            "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n",
            "BaseSettings",
            "\"Annotated[str, Field(default='prod')]\"",
        ),
    ],
)
def test_field_providers_use_the_declaration_scope(imports: str, base: str, annotation: str) -> None:
    source = imports + f"class Settings({base}):\n    environment: {annotation}\n"
    assert len(_lines(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    Field = unknown\n    environment: Annotated[str, Field(default='prod')]\n",
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nAnnotated = unknown\nclass Settings(BaseSettings):\n    deployment: Annotated[str, Field(alias='ENVIRONMENT', default='prod')]\n",
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nBaseSettings = unknown\nclass Settings(BaseSettings):\n    environment: Annotated[str, Field(default='prod')]\n",
        "from pydantic_settings import BaseSettings\nclass Root(BaseSettings): pass\nRoot = unknown\nclass Settings(Root):\n    environment: str = 'prod'\n",
    ],
)
def test_shadowed_providers_and_rebound_local_bases_abstain(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "ps.BaseSettings = unknown",
        "ps.BaseSettings.model_construct = unknown",
        "pd.Field = unknown",
        "setattr(pd, 'Field', unknown)",
        "setattr(ps, 'BaseSettings', unknown)",
        "configure(ps)",
    ],
)
def test_settings_and_field_namespace_mutations_or_escape_abstain(mutation: str) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "import pydantic as pd\nimport pydantic_settings as ps\n"
        f"{mutation}\nclass Settings(BaseSettings):\n    environment: Annotated[str, Field(default='prod')]\n"
    )
    assert _lines(source) == []


class _RuntimeAliasOverride(BaseModel):
    deployment: Annotated[str, Field(default="prod", alias="ENVIRONMENT")] = Field(alias="STAGE")


class _RuntimeAliasReset(BaseModel):
    deployment: Annotated[str, Field(default="prod", alias="ENVIRONMENT")] = Field(validation_alias=None)


def test_alias_merge_assumptions_follow_pydantic_runtime() -> None:
    assert _RuntimeAliasOverride.model_fields["deployment"].validation_alias == "STAGE"
    assert _RuntimeAliasOverride.model_validate({}).deployment == "prod"
    assert _RuntimeAliasReset.model_fields["deployment"].validation_alias == "ENVIRONMENT"


def test_metadata_expansion_is_bounded() -> None:
    annotation = "Annotated[" * 24 + "str" + ", Field(description='selector')]" * 24
    source = (
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings(BaseSettings):\n    environment: {annotation} = 'prod'\n"
    )
    assert _lines(source) == []


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("environment: Annotated[str, Field(default=Ellipsis)]", 0),
        ("deployment: Annotated[str, Field(default=Ellipsis, alias='ENVIRONMENT')]", 0),
        ("environment: str = Field(default=Ellipsis)", 0),
        ("environment: str = Field(Ellipsis)", 0),
        ("environment: str = Ellipsis", 0),
        ("environment: Annotated[str, Field(default='prod')] = Field(default=Ellipsis)", 1),
        ("environment: Annotated[str, Field(default='prod')] = Ellipsis", 0),
        ('environment: "Annotated[str, Field(default=Ellipsis)]"', 0),
    ],
)
def test_unshadowed_builtin_ellipsis_has_required_default_semantics(declaration: str, expected: int) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings(BaseSettings):\n    {declaration}\n"
    )
    assert len(_lines(source)) == expected


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("def unrelated(Ellipsis): pass\n", 0),
        ("Ellipsis = 'prod'\n", 1),
        ("Ellipsis = ...\n", 1),
        ("from external import Ellipsis\n", 1),
        ("Ellipsis = 'dev'\nEllipsis = configured\n", 1),
    ],
)
def test_ellipsis_proof_uses_lexical_bindings_not_only_the_name(prefix: str, expected: int) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        + prefix
        + "class Settings(BaseSettings):\n    environment: Annotated[str, Field(default=Ellipsis)]\n"
    )
    assert len(_lines(source)) == expected


def test_class_local_ellipsis_is_an_opaque_default() -> None:
    source = (
        "from typing import Annotated, ClassVar\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n    Ellipsis: ClassVar[str] = 'prod'\n"
        "    environment: Annotated[str, Field(default=Ellipsis)]\n"
    )
    assert len(_lines(source)) == 1


def test_builtin_namespace_mutation_does_not_prove_a_required_sentinel() -> None:
    source = (
        "import builtins\nfrom typing import Annotated\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "builtins.Ellipsis = custom\nclass Settings(BaseSettings):\n"
        "    environment: Annotated[str, Field(default=Ellipsis)]\n"
    )
    assert _lines(source) == []


def test_quoted_metadata_retains_the_class_default_origin() -> None:
    source = (
        "from typing import Annotated, ClassVar\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n    Ellipsis: ClassVar[str] = 'prod'\n"
        '    environment: "Annotated[str, Field(default=Ellipsis)]"\n'
    )
    assert len(_lines(source)) == 1


@pytest.mark.parametrize("annotation", ["EnvironmentInput", '"EnvironmentInput"'])
def test_module_metadata_alias_is_not_reinterpreted_in_the_settings_class(annotation: str) -> None:
    source = (
        "from typing import Annotated, ClassVar, TypeAlias\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "EnvironmentInput: TypeAlias = Annotated[str, Field(default=Ellipsis)]\n"
        "class Settings(BaseSettings):\n    Ellipsis: ClassVar[str] = 'prod'\n"
        f"    environment: {annotation}\n"
    )
    assert _lines(source) == []


def test_module_metadata_default_stays_a_default_despite_a_different_class_binding() -> None:
    source = (
        "from typing import Annotated, ClassVar, TypeAlias\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "Ellipsis = 'prod'\nEnvironmentInput: TypeAlias = Annotated[str, Field(default=Ellipsis)]\n"
        "class Settings(BaseSettings):\n    Ellipsis: ClassVar[str] = 'dev'\n"
        "    environment: EnvironmentInput\n"
    )
    assert len(_lines(source)) == 1


@pytest.mark.parametrize(
    ("declaration", "annotation", "default"),
    [
        ("from external import Environment\n", "Environment", "Environment.LOCAL"),
        ("from external import Environment as Deployment\n", "Deployment", "Deployment.LOCAL"),
        ("import external as domain\n", "domain.Environment", "domain.Environment.LOCAL"),
        (
            "from enum import StrEnum\nclass Environment(StrEnum):\n    LOCAL = 'local'\n",
            "Environment",
            "Environment.LOCAL",
        ),
        (
            "from external import Environment\nfrom typing import TypeAlias\nDeployment: TypeAlias = Environment\n",
            "Deployment",
            "Environment.LOCAL",
        ),
        (
            "from enum import StrEnum\nfrom typing import TypeAlias\nclass Environment(StrEnum):\n    LOCAL = 'local'\nDeployment: TypeAlias = Environment\n",
            "Deployment",
            "Environment.LOCAL",
        ),
    ],
)
def test_enum_defaults_survive_unrelated_native_data_and_validation_uses(
    declaration: str, annotation: str, default: str
) -> None:
    source = (
        "from typing import Annotated, ClassVar\nfrom pydantic import Field, SecretStr, ValidationError\n"
        "from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict\n"
        f"{declaration}\nclass Settings(BaseSettings):\n"
        "    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file='.env.test', frozen=True, extra='ignore', hide_input_in_errors=True)\n"
        f"    environment: {annotation} = Field(default={default}, alias='ENVIRONMENT')\n"
        "    secret: SecretStr | None = None\n"
        "    values: Annotated[list[str], NoDecode]\n"
        "    def normalize(self, value: SecretStr | None):\n"
        "        try:\n            return value if isinstance(value, SecretStr) else SecretStr(value)\n"
        "        except ValidationError:\n            return None\n"
    )
    assert len(_lines(source)) == 1
    assert _lines(source.replace(f"default={default}, ", "")) == []


@pytest.mark.parametrize(
    "capability",
    ["Field", "BaseSettings", "Annotated", "ClassVar", "Final", "TypeAlias", "pd.Field", "ps.BaseSettings"],
)
def test_relevant_provider_escape_still_abstains(capability: str) -> None:
    source = (
        "from typing import Annotated, ClassVar, Final, TypeAlias\n"
        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "import pydantic as pd\nimport pydantic_settings as ps\n"
        f"configure({capability})\nclass Settings(BaseSettings):\n"
        "    environment: str = Field(default='local', alias='ENVIRONMENT')\n"
    )
    assert _lines(source) == []


@pytest.mark.parametrize("namespace", ["pd", "ps", "pd.fields", "pd.__dict__"])
def test_native_module_namespace_escape_still_abstains(namespace: str) -> None:
    source = (
        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        "import pydantic as pd\nimport pydantic_settings as ps\n"
        f"namespace = {namespace}\nconfigure(namespace)\nclass Settings(BaseSettings):\n"
        "    environment: str = Field(default='local', alias='ENVIRONMENT')\n"
    )
    assert _lines(source) == []
