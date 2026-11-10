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


def _literal_source(annotation: str, value: str, *, copy: bool = False) -> str:
    operation = f"Payload.model_construct(value={value})"
    if copy:
        operation = f"Payload(value='ready').model_copy(update={{'value': {value}}})"
    return (
        "from typing import Annotated, Literal, Optional, Union\n"
        "from pydantic import BaseModel, Field\n"
        f"class Payload(BaseModel):\n    value: {annotation}\n"
        f"payload = {operation}\n"
    )


@pytest.mark.parametrize(
    ("annotation", "value", "expected"),
    [
        ("str", "23", 1),
        ("str", "b'ready'", 1),
        ("str", "'ready'", 0),
        ("bytes", "'ready'", 1),
        ("bytes", "b'ready'", 0),
        ("bool", "1", 1),
        ("bool", "False", 0),
        ("int", "True", 0),
        ("int", "1.0", 1),
        ("int", "'3'", 1),
        ("int", "-3", 0),
        ("float", "3", 0),
        ("float", "True", 0),
        ("float", "3.0", 0),
        ("float", "'3.0'", 1),
        ("complex", "3", 0),
        ("complex", "3.0", 0),
        ("complex", "3j", 0),
        ("complex", "'3j'", 1),
        ("None", "None", 0),
        ("None", "'ready'", 1),
        ("str | int", "True", 0),
        ("str | None", "3", 1),
        ("Union[str, int]", "False", 0),
        ("Optional[str]", "None", 0),
        ("Optional[str]", "3", 1),
        ("Annotated[str, Field()]", "3", 1),
        ("Literal['ready']", "['ready']", 1),
        ("list[str]", "[]", 0),
        ("list[str]", "['ready']", 0),
        ("list[str]", "[3]", 1),
        ("list[str]", "('ready',)", 1),
        ("list[str]", "'ready'", 1),
        ("list", "[3]", 0),
        ("list[list[int]]", "[[1], ['wrong']]", 1),
        ("list[Literal['ready', 'done']]", "['ready', 'other']", 1),
        ("list[Literal[1, 2]]", "['opaque-numeric-literal-domain']", 0),
        ("dict[str, int]", "{'ready': 3}", 0),
        ("dict[str, int]", "{3: 1}", 1),
        ("dict[str, int]", "{'ready': 'wrong'}", 1),
        ("dict[str, int]", "{'ready': 'wrong', 'ready': 1}", 0),
        ("dict[str, int]", "{'ready': 1, 'ready': 'wrong'}", 1),
        ("dict[int, int]", "{False: 'wrong', 0: 1}", 0),
        ("dict[str, int]", "{[]: 3}", 0),
        ("dict[str, int]", "{'ready': 3, **unknown}", 0),
        ("set[str]", "{'ready'}", 0),
        ("set[str]", "{3}", 1),
        ("set[str]", "{[]}", 0),
        ("set[str]", "set()", 0),
        ("frozenset[str]", "['ready']", 1),
        ("tuple[str, int]", "('ready', 3)", 0),
        ("tuple[str, int]", "('ready', 'wrong')", 1),
        ("tuple[str, int]", "('ready',)", 1),
        ("tuple[str, ...]", "('ready', 'done')", 0),
        ("tuple[str, ...]", "('ready', 3)", 1),
        ("tuple[()]", "()", 0),
        ("tuple[()]", "('ready',)", 1),
        ("list[str] | tuple[int, ...]", "(1, 2)", 0),
        ("list[str] | tuple[int, ...]", "('wrong',)", 1),
        ("list[str]", "['ready', *unknown]", 0),
        ("list[str]", "[make_value()]", 0),
        ("list[str]", "unknown", 0),
        ("DomainText", "3", 0),
    ],
)
def test_stored_literal_contracts(annotation: str, value: str, expected: int) -> None:
    assert len(_check(_literal_source(annotation, value))) == expected


@pytest.mark.parametrize("value", ["3", "['wrong']", "{'wrong': 3}"])
def test_copy_literal_contracts(value: str) -> None:
    assert len(_check(_literal_source("str", value, copy=True))) == 1


def test_large_literal_values_abstain_without_recursion() -> None:
    value = "[" + ",".join("3" for _ in range(1500)) + "]"
    assert _check(_literal_source("list[str]", value)) == []


def test_large_textual_literal_domains_abstain_without_expensive_witnesses() -> None:
    large = repr("x" * 100_000)
    assert _check(_literal_source(f"Literal[{large}]", "'wrong'")) == []
    assert _check(_literal_source("int", large)) == []


class _StoredPayload(BaseModel):
    text: str
    count: int
    tags: list[str]


def test_stored_output_differs_from_coercible_validated_input() -> None:
    unchecked = _StoredPayload.model_construct(text=23, count="4", tags=[3])
    with pytest.raises(AttributeError, match="upper"):
        unchecked.text.upper()
    with pytest.raises(TypeError):
        assert unchecked.count + 1 == 5
    with pytest.raises(AttributeError, match="upper"):
        unchecked.tags[0].upper()
    validated = _StoredPayload.model_validate({"text": "ready", "count": "4", "tags": ["tag"]})
    assert validated.count + 1 == 5
    assert validated.text.upper() == "READY"
    trusted = _StoredPayload.model_construct(text="ready", count=True, tags=["tag"])
    assert trusted.count is True
    assert trusted.tags[0].upper() == "TAG"


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
    assert all(finding.severity is Severity.ERROR for finding in findings)
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


_SETTINGS_PREFIX = "from typing import Literal\nfrom pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    environment: Literal['dev', 'prod']\n"


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("Settings.model_construct(environment='other')", 1),
        ("Settings.model_construct()", 1),
        ("Settings.model_construct(environment=None)", 1),
        ("Settings.model_construct(environment='dev')", 0),
        ("Settings.model_construct(environment=value)", 0),
        ("Settings.model_construct(**values)", 0),
        ("Settings(environment='dev')", 0),
        ("Settings.model_validate({'environment': 'other'})", 0),
        ("Settings(environment='dev').model_copy(update={'environment': 'other'})", 1),
        ("Settings(environment='dev').model_copy(update={'environment': 'prod'})", 0),
        ("Settings(environment='dev').model_copy(update=changes)", 0),
    ],
)
def test_direct_settings_validation_and_bypass_contracts(operation: str, expected: int) -> None:
    assert len(_check(_SETTINGS_PREFIX + f"settings = {operation}\n")) == expected


def test_stable_settings_instance_copy_preserves_existing_receiver_proof() -> None:
    source = (
        _SETTINGS_PREFIX
        + "settings = Settings(environment='dev')\nchanged = settings.model_copy(update={'environment': 'other'})\n"
    )
    assert len(_check(source)) == 1
    assert _check(source.replace("changed =", "escape(settings)\nchanged =")) == []
    assert _check(source.replace("changed =", "settings = replacement\nchanged =")) == []


@pytest.mark.parametrize(
    ("imports", "base"),
    [
        ("from pydantic_settings import BaseSettings as Root\n", "Root"),
        ("import pydantic_settings as ps\n", "ps.BaseSettings"),
        ("from pydantic_settings.main import BaseSettings\n", "BaseSettings"),
        ("from pydantic_settings import BaseSettings\ndef unrelated(BaseSettings): pass\n", "BaseSettings"),
    ],
)
def test_settings_base_imports_are_proven_at_module_declarations(imports: str, base: str) -> None:
    source = (
        "from typing import Literal\n"
        + imports
        + f"class Settings({base}):\n    environment: Literal['dev', 'prod']\nSettings.model_construct(environment='other')\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        "class Settings(CustomSettings):",
        "class Parent(BaseSettings): pass\nclass Settings(Parent):",
        "@rewrites_settings\nclass Settings(BaseSettings):",
        "class Settings(BaseSettings, cli_parse_args=True):",
        "BaseSettings = replacement\nclass Settings(BaseSettings):",
    ],
)
def test_unknown_inherited_or_custom_settings_contracts_abstain(replacement: str) -> None:
    source = _SETTINGS_PREFIX.replace("class Settings(BaseSettings):", replacement)
    assert _check(source + "Settings.model_construct(environment='other')\n") == []


@pytest.mark.parametrize(
    "member",
    [
        "    @classmethod\n    def model_construct(cls, **values): return replacement\n",
        "    def model_copy(self, **values): return replacement\n",
        "    @classmethod\n    def settings_customise_sources(cls, settings_cls, **sources): return ()\n",
        "    @field_validator('environment')\n    @classmethod\n    def normalize(cls, value): return 'dev'\n",
        "    model_config = {'env_prefix': 'SERVICE_'}\n",
        "    model_config = SettingsConfigDict(env_prefix='SERVICE_')\n",
        "    model_config = {'populate_by_name': True}\n",
        "    model_config = {'extra': policy}\n",
    ],
)
def test_settings_methods_and_unqualified_configuration_abstain(member: str) -> None:
    source = (
        "from pydantic import field_validator\nfrom pydantic_settings import SettingsConfigDict\n"
        + _SETTINGS_PREFIX.replace("    environment:", f"{member}    environment:")
    )
    assert _check(source + "Settings.model_construct(environment='other')\n") == []


@pytest.mark.parametrize("configuration", ["{'frozen': True}", "{'strict': True, 'extra': 'forbid'}"])
def test_passive_shared_model_options_are_valid_for_settings(configuration: str) -> None:
    source = _SETTINGS_PREFIX.replace("    environment:", f"    model_config = {configuration}\n    environment:")
    assert len(_check(source + "Settings.model_construct(environment='other')\n")) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "ps.BaseSettings.model_construct = replacement",
        "setattr(ps.BaseSettings, 'model_construct', replacement)",
        "ps.BaseSettings = replacement",
        "setattr(ps, 'BaseSettings', replacement)",
        "configure(ps)",
        "configure(BaseSettings)",
    ],
)
def test_all_settings_base_namespace_aliases_remain_guarded(mutation: str) -> None:
    source = "import pydantic_settings as ps\n" + _SETTINGS_PREFIX.replace(
        "class Settings", f"{mutation}\nclass Settings"
    )
    assert _check(source + "Settings.model_construct(environment='other')\n") == []


def test_shadowed_settings_receiver_is_not_the_declared_model() -> None:
    source = _SETTINGS_PREFIX + "def configure(Settings):\n    return Settings.model_construct(environment='other')\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("str = Field(...)", 1),
        ("str = Field(default_factory=None)", 1),
        ("Annotated[str, Field(default_factory=None)]", 1),
        ("Annotated[str, Field(default='dev')] = Field(...)", 0),
        ("Annotated[str, Field(default='dev')] = ...", 1),
        ("Annotated[str, Field(default_factory=str)] = Field(default_factory=None)", 1),
        ("str | None = None", 0),
        ("ClassVar[str] = 'dev'", 0),
    ],
)
def test_settings_required_metadata_uses_existing_pydantic_merging(declaration: str, expected: int) -> None:
    source = (
        "from typing import Annotated, ClassVar\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings(BaseSettings):\n    environment: {declaration}\nSettings.model_construct()\n"
    )
    assert len(_check(source)) == expected


def test_private_settings_fields_are_not_missing_public_inputs() -> None:
    source = "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    _environment: str\nSettings.model_construct()\n"
    assert _check(source) == []


def test_settings_annotation_budget_is_checked_before_recursive_field_analysis() -> None:
    annotation = "str" + " | str" * 1500
    source = f"from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    environment: {annotation}\nSettings.model_construct()\n"
    assert _check(source) == []


@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
@pytest.mark.parametrize(
    "annotation",
    [
        "ClassVar[str]",
        "Annotated[ClassVar[str], Field()]",
        "Annotated[Annotated[ClassVar[str], Field()], Field(description='metadata')]",
        "Annotated[Metadata[str], Field()]",
    ],
)
def test_classvar_metadata_is_not_a_required_model_or_settings_input(base: str, annotation: str) -> None:
    source = (
        "from typing import Annotated, ClassVar\nfrom typing_extensions import ClassVar as Metadata\n"
        "from pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings({base}):\n    environment: {annotation}\nSettings.model_construct()\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
@pytest.mark.parametrize(
    "prefix",
    [
        "from external import ClassVar\n",
        "from typing import ClassVar\nClassVar = external\n",
        "from typing import ClassVar\ndef unrelated(ClassVar): pass\n",
    ],
)
def test_unproven_or_shadowed_classvar_names_do_not_supply_field_contracts(base: str, prefix: str) -> None:
    source = (
        prefix
        + "from typing import Annotated\nfrom pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        + f"class Settings({base}):\n    environment: Annotated[ClassVar[str], Field()]\nSettings.model_construct()\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("str = Ellipsis", 1),
        ("str = Field(Ellipsis)", 1),
        ("str = Field(default=Ellipsis)", 1),
        ("Annotated[str, Field(default=Ellipsis)]", 1),
        ("Annotated[str, Field(default='dev')] = Field(default=Ellipsis)", 0),
        ("Annotated[str, Field(default='dev')] = Ellipsis", 1),
    ],
)
def test_builtin_ellipsis_is_a_required_field_default_only(base: str, declaration: str, expected: int) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        f"class Settings({base}):\n    environment: {declaration}\nSettings.model_construct()\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
@pytest.mark.parametrize(
    "prefix",
    [
        "Ellipsis = 'dev'\n",
        "Ellipsis = ...\n",
        "from external import Ellipsis\n",
        "Ellipsis = 'dev'\nEllipsis = external\n",
    ],
)
def test_shadowed_ellipsis_defaults_remain_opaque(base: str, prefix: str) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        + prefix
        + f"class Settings({base}):\n    environment: Annotated[str, Field(default=Ellipsis)]\nSettings.model_construct()\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("base", ["BaseModel", "BaseSettings"])
def test_unrelated_local_ellipsis_name_does_not_shadow_the_field_default(base: str) -> None:
    source = (
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n"
        "def unrelated(Ellipsis): pass\n"
        f"class Settings({base}):\n    environment: Annotated[str, Field(default=Ellipsis)]\nSettings.model_construct()\n"
    )
    assert len(_check(source)) == 1


class _BuiltinEllipsisRequired(BaseModel):
    value: Annotated[str, Field(default=Ellipsis)]


def test_builtin_ellipsis_required_metadata_matches_pydantic_runtime() -> None:
    assert _BuiltinEllipsisRequired.model_fields["value"].is_required()
