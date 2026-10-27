from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator
import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_invalid_pydantic_validator_return import NoInvalidPydanticValidatorReturn
from sarj_python_lint.rules.no_unknown_pydantic_validator_field import NoUnknownPydanticValidatorField


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _source(annotation: str = "str", value: str = "3", *, mode: str | None = "after") -> str:
    option = f", mode={mode!r}" if mode is not None else ""
    return (
        "from typing import Literal, Optional, Union\n"
        "from pydantic import BaseModel, field_validator\n"
        f"class Payload(BaseModel):\n    text: {annotation}\n"
        f"    @field_validator('text'{option})\n    @classmethod\n"
        f"    def replace(cls, value: object) -> object:\n        return {value}\n"
    )


def _check(source: str, path: str = "app/models.py"):
    return NoInvalidPydanticValidatorReturn().check(Path(path), source)


_BAD = _source()
_DOCUMENTATION = NoInvalidPydanticValidatorReturn.documentation
assert _DOCUMENTATION is not None
_PROBLEM = RuleProblem(
    key="terminal-pydantic-validator-output",
    summary="A validator's own return type does not prove compatibility with its targeted model field.",
    harm="A validated model can store an integer in a string field, causing a typed string consumer to fail.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_BAD, _source(mode="plain")),
    good_examples=(_source(value="'ready'"), _source("int", "'3'", mode="before")),
    exclusions=("Unknown, effectful, composed, inherited, escaped, metadata-constrained and wire-only contracts.",),
)


@pytest.mark.parametrize(
    ("annotation", "value", "expected"),
    [
        ("str", "3", 1),
        ("str", "'ready'", 0),
        ("str", "b'ready'", 1),
        ("str", "None", 1),
        ("bytes", "'ready'", 1),
        ("bytes", "b'ready'", 0),
        ("int", "'3'", 1),
        ("int", "3", 0),
        ("int", "True", 0),
        ("int", "-3", 0),
        ("int", "1.5", 1),
        ("float", "3", 0),
        ("float", "True", 0),
        ("float", "-1.5", 0),
        ("float", "'3'", 1),
        ("complex", "3", 0),
        ("complex", "1.5", 0),
        ("complex", "-2j", 0),
        ("complex", "'3'", 1),
        ("bool", "True", 0),
        ("bool", "1", 1),
        ("None", "3", 1),
        ("None", "None", 0),
        ("str | None", "None", 0),
        ("str | None", "3", 1),
        ("str | int", "3", 0),
        ("str | int", "None", 1),
        ("Optional[str]", "None", 0),
        ("Optional[str]", "3", 1),
        ("Union[str, int]", "3", 0),
        ("Union[str, int]", "None", 1),
        ("Literal['queued', 'done']", "'other'", 1),
        ("Literal['queued', 'done']", "'queued'", 0),
        ("Literal['queued', 'done']", "3", 1),
        ("Literal[1, 2]", "'opaque-domain'", 0),
        ("str | Opaque", "3", 0),
        ("Opaque", "3", 0),
        ("list[str]", "3", 0),
        ("str", "['wrong']", 0),
        ("str", "make_value()", 0),
        ("str", "value", 0),
    ],
)
@pytest.mark.parametrize("mode", ["after", "plain", None])
def test_terminal_stored_contracts(annotation: str, value: str, expected: int, mode: str | None) -> None:
    assert len(_check(_source(annotation, value, mode=mode))) == expected


@pytest.mark.parametrize(
    "source",
    [
        _source(mode="before"),
        _source(mode="wrap"),
        _BAD.replace("field_validator('text'", "field_serializer('text'"),
        _BAD.replace("    @classmethod\n", ""),
        _BAD.replace("    @classmethod", "    @staticmethod"),
        _BAD.replace("    @classmethod", "    @decorate"),
        _BAD.replace("mode='after'", "mode=setting"),
        _BAD.replace("mode='after'", "mode='after', check_fields=False"),
        _BAD.replace("'text', mode", "'*', mode"),
        _BAD.replace("'text', mode", "target, mode"),
        _BAD.replace("'text', mode", "*targets, mode"),
        _BAD.replace("'text', mode", "'missing', mode"),
        _BAD.replace("mode='after'", "mode='after', mode='plain'"),
        _BAD.replace("class Payload", "@decorate\nclass Payload"),
        _BAD.replace("BaseModel):", "Parent):"),
        _BAD.replace("from pydantic import", "from custom_framework import"),
        _BAD.replace("text: str", "text: Annotated[str, AfterValidator(repair)]"),
        _BAD.replace("text: str", "text: str = Field(default_factory=repair)"),
        _BAD.replace("text: str", "text: str\n    model_config = ConfigDict(strict=True)"),
        _BAD.replace("class Payload", "class Payload[T]"),
        _BAD.replace("def replace", "async def replace"),
        _BAD.replace("value: object)", "value: object = 1)"),
        _BAD.replace("value: object)", "value: object, info: object)"),
        _BAD.replace("value: object)", "*value: object)"),
        _BAD.replace("return 3", "value = 'ready'\n        return value"),
        _BAD.replace("return 3", "return 3 if condition else 'ready'"),
        _BAD.replace("return 3", "raise ValueError('rejected')"),
        _BAD + "configure(Payload)\n",
        _BAD + "alias = Payload\n",
        _BAD + "Payload.model_fields['text'].annotation = int\nPayload.model_rebuild(force=True)\n",
        _BAD + "setattr(Payload, 'replace', replacement)\n",
        _BAD + "field_validator = custom\n",
        _BAD + "BaseModel = custom\n",
        _BAD + "classmethod = custom\n",
        _BAD + "str = custom\n",
        _BAD + "from pydantic import *\n",
        _BAD + "globals()['Payload'] = replacement\n",
        _BAD.replace("    text: str", "    text: str\n    str: int = 1"),
        _BAD + "class Child(Payload):\n    pass\n",
        "# Code generated by fixturegen. DO NOT EDIT.\n" + _BAD,
        "class Payload(:\n",
    ],
    ids=[
        "before-output-is-revalidated",
        "wrap-handler-owns-validation",
        "serializer-owns-wire-output",
        "missing-classmethod-stack",
        "static-method-contract",
        "custom-method-decorator",
        "computed-validator-mode",
        "explicit-field-check-policy",
        "wildcard-field-target",
        "computed-field-target",
        "unpacked-field-targets",
        "unknown-target-has-existing-owner",
        "repeated-mode-is-invalid-syntax",
        "decorated-model-authority",
        "inherited-model-contract",
        "non-pydantic-import-owner",
        "annotated-validation-chain",
        "effectful-default-factory",
        "configured-model-policy",
        "generic-model-domain",
        "async-validator-contract",
        "defaulted-validator-parameter",
        "extra-validator-info-parameter",
        "variadic-validator-parameter",
        "computed-local-return",
        "conditional-return-domain",
        "rejecting-validator-has-no-stored-output",
        "escaped-model-class",
        "aliased-model-class",
        "mutated-and-rebuilt-model-schema",
        "reflective-model-method-replacement",
        "rebound-validator-import",
        "rebound-base-model-import",
        "rebound-classmethod-builtin",
        "shadowed-primitive-domain",
        "wildcard-import-ambiguity",
        "dynamic-global-model-replacement",
        "class-scope-primitive-shadow",
        "external-subclass-contract",
        "generated-source-ownership",
        "malformed-python-source",
    ],
)
def test_unknown_authority_and_validation_phases_abstain(source: str) -> None:
    assert _check(source) == []


def test_later_validator_can_repair_the_intermediate_contract() -> None:
    repair = (
        "    @field_validator('text', mode='after')\n    @classmethod\n"
        "    def repair(cls, value: object) -> str:\n        return str(value)\n"
    )
    assert _check(_BAD + repair) == []
    assert len(_check(_BAD)) == 1


def test_multiple_target_fields_report_only_contradictory_contracts_once() -> None:
    source = _BAD.replace("text: str", "text: str\n    count: int").replace("'text', mode", "'count', 'text', mode")
    findings = _check(source)
    assert len(findings) == 1
    assert "text" in findings[0].message
    assert "count" not in findings[0].message
    assert _check(source.replace("text: str", "text: int")) == []


def test_missing_field_belongs_to_existing_validator_owner() -> None:
    source = _BAD.replace("'text', mode", "'missing', mode")
    assert _check(source) == []
    findings = NoUnknownPydanticValidatorField().check(Path("app/models.py"), source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ492"


@pytest.mark.parametrize(
    "namespace",
    [
        "native = getattr(repr, '__self__')\n",
        "from builtins import repr as representation\nnative = getattr(representation, '__self__')\n",
        "import builtins\nnative = getattr(builtins.repr, '__self__')\n",
        "configure(repr)\n",
    ],
)
def test_native_namespace_capabilities_preserve_replaced_model_authority(namespace: str) -> None:
    source = namespace + _BAD
    assert _check(source) == []
    assert len(_check("repr('ordinary direct call')\n" + _BAD)) == 1


def test_docstring_keyword_only_boundaries_and_suppression() -> None:
    source = _BAD.replace("return 3", '"""Choose a fixed sentinel."""\n        return 3')
    assert len(_check(source)) == 1
    assert (
        _check(source.replace("return 3", "return 3  # sarj-noqa: SARJ515 -- intentional legacy representation")) == []
    )
    assert len(_check(_BAD, "tests/test_models.py")) == 1
    finding = _check(_BAD)[0]
    assert finding.severity is Severity.ERROR
    assert finding.code == "SARJ515"


def test_large_annotation_graph_abstains_and_following_source_recovers() -> None:
    assert _check(_source(" | ".join("str" for _ in range(150)))) == []
    assert len(_check(_BAD)) == 1


class _InvalidOutput(BaseModel):
    text: str

    @field_validator("text", mode="after")
    @classmethod
    def replace(cls, _value: str) -> int:
        return 3  # sarj-noqa: SARJ515 -- this runtime counterexample deliberately stores an incompatible field value.


class _ValidatedInput(BaseModel):
    count: int

    @field_validator("count", mode="before")
    @classmethod
    def convert(cls, _value: object) -> str:
        return "3"


def test_after_output_is_trusted_but_before_output_is_revalidated() -> None:
    broken = _InvalidOutput(text="input")
    with pytest.raises(AttributeError, match="upper"):
        broken.text.upper()
    validated = _ValidatedInput.model_validate({"count": "input"})
    assert validated.count + 1 == 4


def _example_id(example: RuleExample) -> str:
    return example.example_id


@pytest.mark.parametrize("example", _DOCUMENTATION.examples, ids=_example_id)
def test_executable_documentation(example: RuleExample) -> None:
    focus = next(file for file in example.files if file.path == example.focus_path)
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def _case_id(case: EvaluationCase) -> str:
    return case.case_id


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase("invalid-stored-output", Language.PYTHON, _PROBLEM.bad_examples[0], ExpectedOutcome.MATCH),
        EvaluationCase("invalid-plain-output", Language.PYTHON, _PROBLEM.bad_examples[1], ExpectedOutcome.MATCH),
        EvaluationCase("valid-stored-output", Language.PYTHON, _PROBLEM.good_examples[0]),
        EvaluationCase("revalidated-input", Language.PYTHON, _PROBLEM.good_examples[1]),
    ],
    ids=_case_id,
)
def test_labeled_evaluation_cases(case: EvaluationCase) -> None:
    assert bool(_check(case.source)) is (case.expected is ExpectedOutcome.MATCH)
