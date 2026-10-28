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
