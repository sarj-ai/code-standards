from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field, ValidationError
import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_invalid_pydantic_bypass import NoInvalidPydanticBypass


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_PREFIX = "from typing import Literal\nfrom pydantic import BaseModel\nclass Job(BaseModel):\n    kind: Literal['queued', 'done']\n    name: str = 'job'\n"
_BASE = _PREFIX + "job = Job.model_construct(kind='unknown')\n"

_PROBLEM = RuleProblem(
    key="unchecked-pydantic-literal-and-required-state",
    summary="Pydantic validation bypass APIs can store literal values or missing fields contrary to a declared type.",
    harm="A statically typed model can expose an unknown tag, None where a value is required, or a missing attribute.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_BASE, _PREFIX + "job = Job.model_construct()\n"),
    good_examples=(_BASE.replace("kind='unknown'", "kind='queued'"),),
    exclusions=(
        "Trusted valid bypasses, unknown domains, aliases, overrides, dynamic namespaces, tests and generated files.",
    ),
)


def _check(source: str, path: str = "app/models.py"):
    return NoInvalidPydanticBypass().check(Path(path), source)


_CASES = (
    ("invalid-string-tag", _BASE, 1),
    ("valid-tag", _BASE.replace("'unknown'", "'queued'"), 0),
    ("missing-required", _PREFIX + "job = Job.model_construct()\n", 1),
    (
        "required-nullable-field",
        _PREFIX.replace("kind: Literal['queued', 'done']", "kind: str | None") + "job = Job.model_construct()\n",
        1,
    ),
    ("explicit-none-conflict", _BASE.replace("kind='unknown'", "kind=None"), 1),
    ("builtin-none-conflict", _BASE.replace("kind='unknown'", "kind='queued', name=None"), 1),
    (
        "nullable-none",
        _BASE.replace("name: str", "name: str | None").replace("kind='unknown'", "kind='queued', name=None"),
        0,
    ),
    (
        "literal-nullable-none",
        _BASE.replace("Literal['queued', 'done']", "Literal['queued', 'done'] | None").replace(
            "kind='unknown'", "kind=None"
        ),
        0,
    ),
    (
        "optional-literal-none",
        "from typing import Optional\n"
        + _BASE.replace("Literal['queued', 'done']", "Optional[Literal['queued', 'done']]").replace(
            "kind='unknown'", "kind=None"
        ),
        0,
    ),
    ("copy-fresh-invalid", _PREFIX + "job = Job(kind='queued').model_copy(update={'kind': 'unknown'})\n", 1),
    ("copy-fresh-valid", _PREFIX + "job = Job(kind='queued').model_copy(update={'kind': 'done'})\n", 0),
    (
        "copy-local-invalid",
        _PREFIX + "job = Job(kind='queued')\nchanged = job.model_copy(update={'kind': 'unknown'})\n",
        1,
    ),
    (
        "copy-local-valid",
        _PREFIX + "job = Job(kind='queued')\nchanged = job.model_copy(update={'kind': 'done'}, deep=True)\n",
        0,
    ),
    ("copy-none-invalid", _PREFIX + "job = Job(kind='queued').model_copy(update={'name': None})\n", 1),
    ("copy-nonliteral-update", _PREFIX + "job = Job(kind='queued').model_copy(update=updates)\n", 0),
    (
        "copy-duplicate-keys",
        _PREFIX + "job = Job(kind='queued').model_copy(update={'kind': 'unknown', 'kind': 'done'})\n",
        0,
    ),
    (
        "copy-unpacked-update",
        _PREFIX + "job = Job(kind='queued').model_copy(update={'kind': 'unknown', **updates})\n",
        0,
    ),
    ("copy-computed-update", _PREFIX + "job = Job(kind='queued').model_copy(update={key: 'unknown'})\n", 0),
    (
        "copy-external-receiver",
        _PREFIX + "def change(job: Job):\n    return job.model_copy(update={'kind': 'unknown'})\n",
        0,
    ),
    (
        "copy-rebound-receiver",
        _PREFIX + "job = Job(kind='queued')\njob = another\nchanged = job.model_copy(update={'kind': 'unknown'})\n",
        0,
    ),
    (
        "copy-escaped-receiver",
        _PREFIX + "job = Job(kind='queued')\nconfigure(job)\nchanged = job.model_copy(update={'kind': 'unknown'})\n",
        0,
    ),
    (
        "copy-mutated-method",
        _PREFIX
        + "job = Job(kind='queued')\njob.model_copy = replacement\nchanged = job.model_copy(update={'kind': 'unknown'})\n",
        0,
    ),
    (
        "copy-alias-receiver",
        _PREFIX + "job = Job(kind='queued')\nalias = job\nchanged = alias.model_copy(update={'kind': 'unknown'})\n",
        0,
    ),
    (
        "normal-validation",
        _BASE.replace("model_construct", "model_validate").replace("kind='unknown'", "{'kind': 'unknown'}"),
        0,
    ),
    ("constructor-validation", _BASE.replace("Job.model_construct", "Job"), 0),
    ("unknown-value", _BASE.replace("kind='unknown'", "kind=raw_kind"), 0),
    ("unpacked-construction", _BASE.replace("kind='unknown'", "**values"), 0),
    ("mixed-unpacked-construction", _BASE.replace("kind='unknown'", "kind='unknown', **values"), 0),
    ("positional-construction", _BASE.replace("kind='unknown'", "values"), 0),
    (
        "numeric-literal-bool-equality",
        _BASE.replace("Literal['queued', 'done']", "Literal[1, 2]").replace("kind='unknown'", "kind=True"),
        0,
    ),
    (
        "numeric-literal-float-equality",
        _BASE.replace("Literal['queued', 'done']", "Literal[1, 2]").replace("kind='unknown'", "kind=1.0"),
        0,
    ),
    (
        "numeric-literal-invalid-skipped",
        _BASE.replace("Literal['queued', 'done']", "Literal[1, 2]").replace("kind='unknown'", "kind=3"),
        0,
    ),
    ("open-string", _BASE.replace("Literal['queued', 'done']", "str"), 0),
    ("opaque-field-type", _BASE.replace("name: str", "name: Custom"), 0),
    ("opaque-field-alias", _BASE.replace("Literal['queued', 'done']", "Kind"), 0),
    ("inherited-model", _BASE.replace("class Job(BaseModel):", "class Parent(BaseModel): pass\nclass Job(Parent):"), 0),
    ("custom-method", _BASE.replace("    name:", "    def render(self): return self.kind\n    name:"), 0),
    (
        "construct-override",
        _BASE.replace(
            "    name:",
            "    @classmethod\n    def model_construct(cls, **kwargs): return cls(kind='queued')\n    name:",
        ),
        0,
    ),
    ("copy-override", _BASE.replace("    name:", "    def model_copy(self, **kwargs): return self\n    name:"), 0),
    ("custom-new", _BASE.replace("    name:", "    def __new__(cls): return custom\n    name:"), 0),
    ("custom-init", _BASE.replace("    name:", "    def __init__(self, **kwargs): pass\n    name:"), 0),
    (
        "post-init",
        _BASE.replace("    name:", "    def model_post_init(self, context): self.kind = 'queued'\n    name:"),
        0,
    ),
    (
        "before-validator",
        _BASE.replace(
            "    name:",
            "    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, values): return values\n    name:",
        ),
        0,
    ),
    ("decorated-model", _BASE.replace("class Job", "@decorate\nclass Job"), 0),
    ("class-rebound", _BASE.replace("job = Job", "Job = replacement\njob = Job"), 0),
    ("class-argument-shadow", _PREFIX + "def create(Job):\n    return Job.model_construct(kind='unknown')\n", 0),
    (
        "class-local-shadow",
        _PREFIX + "def create():\n    Job = replacement\n    return Job.model_construct(kind='unknown')\n",
        0,
    ),
    (
        "class-global-write",
        _PREFIX
        + "def change():\n    global Job\n    Job = replacement\n"
        + "job = Job.model_construct(kind='unknown')\n",
        0,
    ),
    ("class-mutated", _BASE.replace("job = Job", "Job.model_construct = replacement\njob = Job"), 0),
    ("class-method-escaped", _BASE.replace("job = Job", "factory = Job.model_construct\njob = Job"), 0),
    ("class-escaped", _BASE.replace("job = Job", "configure(Job)\njob = Job"), 0),
    ("class-in-schema-hook", _BASE.replace("job = Job", "type Mutated = Wrapper[Job]\njob = Job"), 0),
    ("model-fields-mutated", _BASE.replace("job = Job", "Job.model_fields['kind'] = custom\njob = Job"), 0),
    ("unknown-framework", _BASE.replace("from pydantic import", "from another_framework import"), 0),
    ("import-rebound", _BASE.replace("class Job", "BaseModel = custom\nclass Job"), 0),
    ("literal-shadowed", _BASE.replace("class Job", "Literal = custom\nclass Job"), 0),
    ("wildcard-import", "from another import *\n" + _BASE, 0),
    ("dynamic-module", _BASE + "globals()['Job'] = custom\n", 0),
    ("generated", "# @generated\n" + _BASE, 0),
    ("malformed", "class Job(:", 0),
    ("comment", "# " + _BASE.replace("\n", "\n# "), 0),
    ("string", repr(_BASE), 0),
    (
        "suppression",
        _BASE.replace("kind='unknown')", "kind='unknown')  # sarj-noqa: SARJ511 -- deliberate invalid state"),
        0,
    ),
    (
        "other-suppression",
        _BASE.replace("kind='unknown')", "kind='unknown')  # sarj-noqa: SARJ510 -- independent concern"),
        1,
    ),
    (
        "import-aliases",
        _BASE.replace("Literal", "Tag")
        .replace("from typing import Tag", "from typing import Literal as Tag")
        .replace("BaseModel", "Model")
        .replace("from pydantic import Model", "from pydantic import BaseModel as Model"),
        1,
    ),
    (
        "module-aliases",
        _BASE.replace("from typing import Literal", "import typing as t")
        .replace("Literal[", "t.Literal[")
        .replace("from pydantic import BaseModel", "import pydantic as p")
        .replace("(BaseModel)", "(p.BaseModel)"),
        1,
    ),
    ("functional-scope", _PREFIX + "def create():\n    return Job.model_construct(kind='unknown')\n", 1),
    (
        "classvar-not-required",
        "from typing import ClassVar\n" + _BASE.replace("    name:", "    version: ClassVar[int] = 1\n    name:"),
        1,
    ),
)


@pytest.mark.parametrize(("label", "source", "count"), _CASES, ids=[case[0] for case in _CASES])
def test_labeled_bypass_cases(label: str, source: str, count: int) -> None:
    case = EvaluationCase(
        label,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if count else ExpectedOutcome.NO_MATCH,
        PurePosixPath("app/models.py"),
    )
    assert len(_check(case.source)) == count


_PUBLIC_EXAMPLES = NoInvalidPydanticBypass.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


@pytest.mark.parametrize("configuration", ["ConfigDict(frozen=True)", "{'strict': True, 'extra': 'forbid'}"])
def test_passive_configuration_preserves_bypass_contract(configuration: str) -> None:
    source = "from pydantic import ConfigDict\n" + _BASE.replace(
        "    kind:", f"    model_config = {configuration}\n    kind:"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "configuration",
    [
        "ConfigDict(populate_by_name=True)",
        "ConfigDict(alias_generator=aliaser)",
        "ConfigDict(ignored_types=(Marker,))",
        "{'extra': policy}",
    ],
)
def test_configuration_that_can_change_input_or_schema_is_not_inferred(configuration: str) -> None:
    source = "from pydantic import ConfigDict\n" + _BASE.replace(
        "    kind:", f"    model_config = {configuration}\n    kind:"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "option", ["alias='wire_kind'", "validation_alias='wire_kind'", "serialization_alias='wire_kind'"]
)
def test_field_aliases_abstain_instead_of_guessing_keyword_mapping(option: str) -> None:
    source = "from pydantic import Field\n" + _BASE.replace(
        "    kind: Literal['queued', 'done']", f"    kind: Literal['queued', 'done'] = Field({option})"
    )
    assert _check(source) == []


@pytest.mark.parametrize("declaration", ["Field(default='queued')", "Field(default_factory=str)", "'queued'"])
def test_defaults_are_not_missing_required_fields(declaration: str) -> None:
    source = (
        "from pydantic import Field\n"
        + _PREFIX.replace("kind: Literal['queued', 'done']", f"kind: Literal['queued', 'done'] = {declaration}")
        + "job = Job.model_construct()\n"
    )
    assert _check(source) == []


def test_annotated_defaults_and_required_metadata() -> None:
    prefix = "from typing import Annotated\nfrom pydantic import Field\n"
    source = (
        prefix
        + _PREFIX.replace(
            "kind: Literal['queued', 'done']", "kind: Annotated[Literal['queued', 'done'], Field(default='queued')]"
        )
        + "job = Job.model_construct()\n"
    )
    assert _check(source) == []
    assert (
        _check(source.replace("Field(default='queued')]", "Field(default='queued')] = Field(description='tag')")) == []
    )
    assert len(_check(source.replace("Field(default='queued')", "Field(description='job tag')"))) == 1


@pytest.mark.parametrize("name", ["model_construct", "model_copy", "__copy__", "__deepcopy__"])
def test_api_shadowing_fields_are_not_inherited_bypass_methods(name: str) -> None:
    source = _BASE.replace("    kind:", f"    {name}: str = 'custom'\n    kind:")
    assert _check(source) == []


@pytest.mark.parametrize(
    ("declaration", "required"),
    [
        ("str = ...", True),
        ("str = Field(...)", True),
        ("str = Field(default=...)", True),
        ("str = Field(default_factory=None)", True),
        ("Annotated[str, Field(...)]", True),
        ("Annotated[str, Field(default=...)]", True),
        ("Annotated[str, Field(default_factory=None)]", True),
        ("Annotated[str, Field(default='queued')] = Field(...)", False),
        ("Annotated[str, Field(default='queued')] = Field(default=...)", False),
        ("Annotated[str, Field(default='queued')] = ...", True),
        ("Annotated[str, Field(default_factory=str)] = ...", False),
        ("Annotated[str, Field(default_factory=str)] = Field(default_factory=None)", True),
        ("Annotated[Annotated[str, Field(default='queued')], Field(description='tag')]", False),
    ],
)
def test_required_markers_follow_pydantic_default_merging(declaration: str, *, required: bool) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\n"
        f"class Job(BaseModel):\n    kind: {declaration}\n"
        "job = Job.model_construct()\n"
    )
    assert len(_check(source)) == int(required)


@pytest.mark.parametrize(
    "mutation",
    [
        "BaseModel.model_construct = replacement",
        "setattr(BaseModel, 'model_construct', replacement)",
        "BaseModel.model_copy = replacement",
    ],
)
def test_pydantic_base_api_monkeypatch_abstains(mutation: str) -> None:
    source = _BASE.replace("class Job", f"{mutation}\nclass Job")
    assert _check(source) == []


def test_multiple_invalid_fields_are_distinct_and_warnings() -> None:
    findings = _check(_BASE.replace("kind='unknown'", "kind='unknown', name=None"))
    assert len(findings) == 2
    assert len({(finding.line, finding.col) for finding in findings}) == 2
    assert all(finding.severity is Severity.WARNING for finding in findings)
    assert _check(_BASE, "tests/test_models.py") == []
    assert _PROBLEM.bad_examples[0] == _BASE


class _Job(BaseModel):
    kind: Literal["queued", "done"]
    name: str


def test_runtime_bypass_reproduces_invalid_literal_and_missing_attribute() -> None:
    assert _Job.model_construct(kind="unknown").kind == "unknown"
    assert _Job(kind="queued", name="job").model_copy(update={"kind": "unknown"}).kind == "unknown"
    with pytest.raises(ValidationError):
        _Job.model_validate({"kind": "unknown", "name": "job"})
    missing = _Job.model_construct(kind="queued")
    with pytest.raises(AttributeError, match="name"):
        missing.name.upper()


class _PositiveDefault(BaseModel):
    quantity: Annotated[int, Field(gt=0)]


def test_numeric_constraints_are_real_bypass_risks_but_not_guessed_by_this_rule() -> None:
    assert _PositiveDefault.model_construct(quantity=-1).quantity == -1
    with pytest.raises(ValidationError):
        _PositiveDefault.model_validate({"quantity": -1})


class _EllipsisRequired(BaseModel):
    value: str = Field(...)


class _NoneFactoryRequired(BaseModel):
    value: str = Field(default_factory=None)  # pyright: ignore[reportArgumentType, reportUnknownVariableType] -- Pydantic accepts None at runtime although its Field overload excludes it.


class _MergedMetadataDefault(BaseModel):
    value: Annotated[str, Field(default="present")] = Field(...)


class _ResetMetadataFactory(BaseModel):
    value: Annotated[str, Field(default_factory=str)] = Field(default_factory=None)  # pyright: ignore[reportArgumentType, reportUnknownVariableType] -- exercise the runtime factory-reset behavior missing from Field's overload.


def test_required_field_and_metadata_merging_assumptions_follow_runtime() -> None:
    assert _EllipsisRequired.model_fields["value"].is_required()
    assert _NoneFactoryRequired.model_fields["value"].is_required()
    assert _ResetMetadataFactory.model_fields["value"].is_required()
    assert not _MergedMetadataDefault.model_fields["value"].is_required()
    assert _MergedMetadataDefault.model_construct().value == "present"


@pytest.mark.parametrize(
    "wrapper", ["{}", "Optional[{}]", "Union[{}, None]", "Annotated[{}, Field(description='value')]"]
)
def test_large_flat_union_field_annotations_abstain_without_recursion_failure(wrapper: str) -> None:
    many = " | ".join(["str"] * 1500 + ["int"])
    source = (
        "from typing import Annotated, Optional, Union\nfrom pydantic import BaseModel, Field\n"
        f"class Model(BaseModel):\n    field: {wrapper.format(many)}\nModel.model_construct()\n"
    )
    assert _check(source) == []


def test_deep_right_grouped_field_annotation_abstains_without_recursion_failure() -> None:
    annotation = "".join(["str | ("] * 100 + ["int"] + [")"] * 100)
    source = (
        f"from pydantic import BaseModel\nclass Model(BaseModel):\n    field: {annotation}\nModel.model_construct()\n"
    )
    assert _check(source) == []
