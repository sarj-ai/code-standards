from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_optional_composite import PreferOptionalComposite


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


P = Path("app/models.py")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return PreferOptionalComposite().check(path, source)


def _model(fields: str, imports: str = "") -> str:
    return "from pydantic import BaseModel\n" + imports + "class State(BaseModel):\n" + fields


def test_documented_examples() -> None:
    verify_native_rule(PreferOptionalComposite, analyze)


@pytest.mark.parametrize(
    ("annotation", "imports"),
    [
        ("str | None", ""),
        ("None | str", ""),
        ("Optional[str]", "from typing import Optional\n"),
        ("typing.Optional[str]", "import typing\n"),
        ("Union[str, None]", "from typing import Union\n"),
        ("Annotated[str | None, 'wire']", "from typing import Annotated\n"),
        ("Annotated[Optional[str], 'wire']", "from typing import Annotated, Optional\n"),
        ("'str | None'", ""),
        ("Alias", "type Alias = str | None\n"),
        ("Alias", "from typing import TypeAlias, Optional\nAlias: TypeAlias = Optional[str]\n"),
    ],
)
def test_explicit_outer_nullability(annotation: str, imports: str) -> None:
    fields = f"    version_id: {annotation} = None\n    version_number: {annotation} = None\n"
    findings = _check(_model(fields, imports))
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "version_" in findings[0].message


def test_exact_supplied_pair_survives_unrelated_field_factories_and_methods() -> None:
    source = """import pydantic
from typing import Annotated
Text = Annotated[str, pydantic.BeforeValidator(normalize)]
class CallDetail(pydantic.BaseModel):
    scenario_id: ScenarioId
    scenario_version_id: ScenarioVersionId | None = None
    scenario_version_number: pydantic.PositiveInt | None = None
    scenario_data: dict[str, object] | None = None
    flags: list[Flag] = pydantic.Field(default_factory=list[Flag])
    @pydantic.field_validator('flags')
    @classmethod
    def validate_flags(cls, values):
        return values
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 6
    assert "scenario_version_" in findings[0].message
    assert "scenario_data" not in findings[0].message
    assert "valid partial states" in findings[0].message


@pytest.mark.parametrize(
    ("prefix", "header"),
    [
        ("", "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass State:\n"),
        ("", "from typing import TypedDict\nclass State(TypedDict):\n"),
        ("", "from typing_extensions import TypedDict\nclass State(TypedDict, total=False):\n"),
    ],
)
def test_plain_record_families(prefix: str, header: str) -> None:
    assert len(_check(prefix + header + "    version_id: str | None\n    version_number: int | None\n")) == 1


@pytest.mark.parametrize(
    "fields",
    [
        "    version_id: str\n    version_number: int | None\n",
        "    version_id: list[str | None]\n    version_number: int | None\n",
        "    version_id: str | None\n    version_number: list[int | None]\n",
        "    user_id: str | None\n    version_number: int | None\n",
        "    id: str | None\n    number: int | None\n",
        "    version_id: None\n    version_number: int | None\n",
        "    version_id: Alias\n    version_number: Alias\n",
    ],
)
def test_required_unrelated_and_unknown_annotations(fields: str) -> None:
    assert _check(_model(fields)) == []


@pytest.mark.parametrize(
    "source",
    [
        _model("    version_id: str | None\n    version_id: int\n    version_number: int | None\n"),
        _model(
            "    version_id: ClassVar[str | None]\n    version_number: int | None\n", "from typing import ClassVar\n"
        ),
        "from dataclasses import dataclass, InitVar\n@dataclass\nclass State:\n    version_id: InitVar[str | None]\n    version_number: int | None\n",
        _model("    version_id: Alias\n    version_number: Alias\n", "type Alias = Alias\n"),
        _model("    version_id: Alias\n    version_number: Alias\n", "type Alias = str | None\nAlias = int\n"),
        "class BaseModel: pass\nclass State(BaseModel):\n    version_id: str | None\n    version_number: int | None\n",
        "from pydantic import BaseModel\nclass Parent(BaseModel): pass\nclass State(Parent):\n    version_id: str | None\n    version_number: int | None\n",
        "from pydantic import BaseModel\n@unknown\nclass State(BaseModel):\n    version_id: str | None\n    version_number: int | None\n",
        "from pydantic import BaseModel\nclass State[T](BaseModel):\n    version_id: str | None\n    version_number: int | None\n",
        "from pydantic import BaseModel\nclass State(BaseModel):\n    version_id: str | None\n    version_number: int | None\nState = elsewhere\n",
        "import pydantic\npydantic.BaseModel = Other\nclass State(pydantic.BaseModel):\n    version_id: str | None\n    version_number: int | None\n",
    ],
    ids=[
        "duplicate-field",
        "class-metadata",
        "init-only-metadata",
        "recursive-alias",
        "rebound-alias",
        "shadowed-model-base",
        "inherited-model",
        "unknown-decorator",
        "generic-model",
        "rebound-model",
        "mutated-model-base",
    ],
)
def test_metadata_shadowing_rebinding_and_unknown_models(source: str) -> None:
    assert _check(source) == []


def test_one_maximal_group_not_overlapping_nested_prefixes() -> None:
    source = _model("    in_use_by: str | None\n    in_use_by_name: str | None\n    in_use_since: str | None\n")
    findings = _check(source)
    assert len(findings) == 1
    assert "nullable in_use_ fields" in findings[0].message


def test_independent_groups_emit_distinct_anchors() -> None:
    source = _model(
        "    version_id: str | None\n    version_number: int | None\n    actor_id: str | None\n    actor_name: str | None\n"
    )
    findings = _check(source)
    assert [(finding.line, finding.col) for finding in findings] == [(3, 5), (5, 5)]


@pytest.mark.parametrize(
    "path",
    [Path("tests/models.py"), Path("vendor/models.py"), Path("generated/models.py")],
    ids=["test", "vendor", "generated"],
)
def test_external_ownership(path: Path) -> None:
    assert _check(_model("    version_id: str | None\n    version_number: int | None\n"), path) == []


def test_exact_code_suppression_and_malformed_source() -> None:
    source = _model(
        "    version_id: str | None  # sarj-noqa: SARJ541 -- preserve existing wire schema\n    version_number: int | None\n"
    )
    assert _check(source) == []
    assert check_source([PreferOptionalComposite()], P, source) == []
    assert _check("class State(BaseModel):\n    version_id: (") == []


@pytest.mark.parametrize(
    ("annotation", "imports"),
    [
        ("ClassVar[str]", "from typing import ClassVar\n"),
        ("'ClassVar[str | None]'", "from typing import ClassVar\n"),
        ("Annotated[ClassVar[str], 'meta']", "from typing import Annotated, ClassVar\n"),
        ("Metadata", "from typing import ClassVar, TypeAlias\nMetadata: TypeAlias = ClassVar[str]\n"),
    ],
    ids=["required-classvar", "quoted-classvar", "annotated-classvar", "aliased-classvar"],
)
def test_class_metadata_sibling_does_not_block_instance_group(annotation: str, imports: str) -> None:
    source = _model(
        f"    version_id: str | None\n    version_number: int | None\n    version_label: {annotation} = 'meta'\n",
        imports,
    )
    findings = _check(source)
    assert len(findings) == 1
    assert "version_label" not in findings[0].message


def test_init_only_sibling_does_not_block_dataclass_instance_group() -> None:
    source = (
        "from dataclasses import dataclass, InitVar\n@dataclass()\nclass State:\n"
        "    version_id: str | None\n    version_number: int | None\n    version_label: InitVar[str]\n"
    )
    assert len(_check(source)) == 1
    assert _check(source.replace("InitVar[str]", "str")) == []


@pytest.mark.parametrize(
    "imports",
    [
        "import typing as t\nt.Optional = list\nfrom typing import Optional\n",
        "from typing import Optional\nimport typing as t\nt.Optional = list\n",
        "import typing_extensions as t\nt.Optional = list\nfrom typing_extensions import Optional\n",
    ],
    ids=["mutation-before-alias", "mutation-after-alias", "extensions-owner-mutation"],
)
def test_mutated_nullable_wrapper_owner_abstains(imports: str) -> None:
    fields = "    version_id: Optional[str]\n    version_number: Optional[int]\n"
    assert _check(_model(fields, imports)) == []
    stable = "\n".join(line for line in imports.split("\n") if ".Optional =" not in line)
    assert len(_check(_model(fields, stable))) == 1


def test_quoted_nullable_wrapper_namespace_mutation_abstains() -> None:
    source = _model(
        "    version_id: 't.Optional[str]'\n    version_number: 't.Optional[int]'\n",
        "import typing as t\n",
    )
    assert len(_check(source)) == 1
    assert _check(source.replace("class State", "t.Optional = list\nclass State")) == []


def test_class_value_shadowing_nullable_wrapper_abstains() -> None:
    source = _model(
        "    model_config = {'ignored_types': (type,)}\n    Optional = list\n"
        "    version_id: Optional[str]\n    version_number: Optional[int]\n",
        "from typing import Optional\n",
    )
    assert _check(source) == []
    assert len(_check(source.replace("    Optional = list\n", "    unrelated = list\n"))) == 1


def test_shadowed_or_mutated_metadata_sibling_still_blocks_group() -> None:
    fields = "    version_id: str | None\n    version_number: int | None\n    version_label: ClassVar[str]\n"
    shadowed = _model(
        "    model_config = {'ignored_types': (type,)}\n    ClassVar = list\n" + fields,
        "from typing import ClassVar\n",
    )
    mutated = _model(fields, "import typing as t\nfrom typing import ClassVar\nt.ClassVar = list\n")
    assert _check(shadowed) == []
    assert _check(mutated) == []
    assert _check(_model(fields.replace("ClassVar[str]", "str"))) == []


def test_mutated_record_owner_abstains_without_confusing_instance_writes() -> None:
    source = _model("    version_id: str | None\n    version_number: int | None\n")
    assert _check(source + "State.model_fields = {}\n") == []
    assert len(_check(source + "def clear(state):\n    state.version_id = None\n")) == 1


@pytest.mark.parametrize(
    "header",
    [
        "from dataclasses import dataclass\n@dataclass\nclass State:\n",
        "from dataclasses import dataclass as record\n@record\nclass State:\n",
        "import dataclasses as dc\n@dc.dataclass\nclass State:\n",
    ],
    ids=["bare", "bare-alias", "bare-namespace"],
)
def test_bare_dataclass_decorators(header: str) -> None:
    source = header + "    version_id: str | None\n    version_number: int | None\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "imports",
    [
        "import pydantic as p\np.BaseModel = object\n",
        "def replace():\n    global BaseModel\n    BaseModel = object\nreplace()\n",
        "Alias = BaseModel\nAlias.model_fields = {}\n",
        "configure(BaseModel)\n",
    ],
    ids=["owner-module-write", "global-rebind", "escaped-alias-write", "opaque-owner-callback"],
)
def test_unproven_runtime_model_owner_abstains(imports: str) -> None:
    fields = "    version_id: str | None\n    version_number: int | None\n"
    assert _check(_model(fields, imports)) == []
    assert len(_check(_model(fields))) == 1


@pytest.mark.parametrize(
    "runtime_import",
    ["    from builtins import object as BaseModel\n", "    from elsewhere import Model as BaseModel\n"],
    ids=["plain-class", "unknown-class"],
)
def test_type_checking_model_import_does_not_prove_runtime_base(runtime_import: str) -> None:
    source = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pydantic import BaseModel\nelse:\n"
        + runtime_import
        + "class State(BaseModel):\n    version_id: str | None\n    version_number: int | None\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("local", ["BaseModel", "pydantic"], ids=["direct-owner", "namespace-owner"])
def test_unrelated_local_owner_name_preserves_model(local: str) -> None:
    header = "from pydantic import BaseModel\nclass State(BaseModel):\n"
    if local == "pydantic":
        header = "import pydantic\nclass State(pydantic.BaseModel):\n"
    source = header + "    version_id: str | None\n    version_number: int | None\n"
    assert len(_check(source + f"def helper({local}):\n    return {local}\n")) == 1


def test_captured_independent_import_survives_other_owner_name_rebind() -> None:
    source = (
        "from pydantic import BaseModel\nfrom pydantic import BaseModel as Captured\nBaseModel = object\n"
        "class State(Captured):\n    version_id: str | None\n    version_number: int | None\n"
    )
    assert len(_check(source)) == 1


def test_type_checking_nullable_wrapper_does_not_prove_runtime_nullability() -> None:
    source = _model(
        "    version_id: Optional[str]\n    version_number: Optional[int]\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from typing import Optional\n"
        "else:\n    from builtins import list as Optional\n",
    )
    assert _check(source) == []
    stable = _model(
        "    version_id: Optional[str]\n    version_number: Optional[int]\n", "from typing import Optional\n"
    )
    assert len(_check(stable)) == 1


def test_global_rebinding_nullable_wrapper_abstains() -> None:
    source = _model(
        "    version_id: Optional[str]\n    version_number: Optional[int]\n",
        "from typing import Optional\ndef replace():\n    global Optional\n    Optional = list\nreplace()\n",
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("annotation", "imports"),
    [
        ("Annotated[ClassVar[str], 'meta']", "from typing import Annotated\n"),
        ("Annotated[InitVar[str], 'meta']", "from typing import Annotated\n"),
        ("Metadata", "type Metadata = ClassVar[str]\n"),
        ("Metadata", "type Metadata = InitVar[str]\n"),
        (
            "Metadata",
            "from typing import Annotated, TypeAlias\nMetadata: TypeAlias = Annotated[ClassVar[str], 'meta']\n",
        ),
    ],
    ids=["annotated-classvar", "annotated-initvar", "classvar-alias", "initvar-alias", "legacy-annotated-alias"],
)
def test_dataclass_runtime_metadata_wrappers_remain_instance_siblings(annotation: str, imports: str) -> None:
    source = (
        "from dataclasses import dataclass, InitVar\nfrom typing import ClassVar\n"
        + imports
        + "@dataclass()\nclass State:\n    version_id: str | None\n    version_number: int | None\n"
        f"    version_label: {annotation} = 'meta'\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("metadata", ["ClassVar", "InitVar", "KW_ONLY"], ids=["class", "init-only", "keyword-only"])
def test_dataclass_bare_runtime_metadata_does_not_block_group(metadata: str) -> None:
    source = (
        "from dataclasses import dataclass, InitVar, KW_ONLY\nfrom typing import ClassVar\n"
        "@dataclass()\nclass State:\n    version_id: str | None\n    version_number: int | None\n"
        f"    version_label: {metadata}\n"
    )
    assert len(_check(source)) == 1


def test_pydantic_bare_classvar_is_metadata() -> None:
    source = _model(
        "    version_id: str | None\n    version_number: int | None\n    version_label: ClassVar\n",
        "from typing import ClassVar\n",
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("annotation", "imports"),
    [
        ("Metadata", "from typing import ClassVar\ntype Metadata = ClassVar[str]\n"),
        ("InitVar[str]", "from dataclasses import InitVar\n"),
    ],
    ids=["pep695-classvar-alias", "dataclass-initvar"],
)
def test_pydantic_nonmetadata_sibling_still_blocks_group(annotation: str, imports: str) -> None:
    source = _model(
        "    model_config = {'arbitrary_types_allowed': True}\n"
        "    version_id: str | None\n    version_number: int | None\n"
        f"    version_label: {annotation} = 'meta'\n",
        imports,
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "replacement", ["    __annotations__ = {}\n", "    def __annotate__(format):\n        return {}\n"]
)
def test_replaced_annotation_namespace_abstains(replacement: str) -> None:
    assert _check(_model("    version_id: str | None\n    version_number: int | None\n") + replacement) == []


@pytest.mark.parametrize(
    "aliases",
    [
        "type Alias = Annotated[Alias, 'wire']\n",
        "type Alias = Annotated[Other, 'wire']\ntype Other = Annotated[Alias, 'wire']\n",
        "Alias: TypeAlias = Annotated['Alias', 'wire']\n",
    ],
    ids=["recursive-transparent", "mutual-transparent", "legacy-recursive-transparent"],
)
def test_recursive_metadata_aliases_are_bounded(aliases: str) -> None:
    imports = "from typing import Annotated, TypeAlias\n" + aliases
    assert _check(_model("    version_id: Alias\n    version_number: Alias\n", imports)) == []
    assert (
        _check(
            _model("    version_id: str | None\n    version_number: int | None\n    version_label: Alias\n", imports)
        )
        == []
    )


def test_type_only_model_base_abstains() -> None:
    source = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pydantic import BaseModel\n"
        "class State(BaseModel):\n    version_id: str | None\n    version_number: int | None\n"
    )
    assert _check(source) == []


def test_class_skipping_method_capture_preserves_runtime_owner_uncertainty() -> None:
    source = _model(
        "    version_id: str | None\n    version_number: int | None\n",
        "class Container:\n    BaseModel = object\n    def expose(self):\n        return BaseModel\n"
        "Alias = Container().expose()\nAlias.model_fields = {}\n",
    )
    assert _check(source) == []


def test_class_skipping_lambda_capture_preserves_runtime_owner_uncertainty() -> None:
    source = _model(
        "    version_id: str | None\n    version_number: int | None\n",
        "class Container:\n    BaseModel = object\n    def expose(self):\n        return lambda: BaseModel\n"
        "Alias = Container().expose()()\nAlias.model_fields = {}\n",
    )
    assert _check(source) == []
