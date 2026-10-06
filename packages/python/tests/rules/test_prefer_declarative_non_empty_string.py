from __future__ import annotations

from pathlib import Path, PurePosixPath
from textwrap import dedent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleExample, RuleProblem, Severity

from sarj_python_lint.rules.prefer_declarative_non_empty_string import PreferDeclarativeNonEmptyString


_PROBLEM = RuleProblem(
    key="declarative-non-empty-string",
    summary="String emptiness is manually enforced inside an existing Pydantic validation boundary.",
    harm="The schema still advertises an unconstrained string, while handwritten validators duplicate the contract.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(
        "@validate_call\ndef label(value: str):\n    if not value:\n        raise ValueError('empty')\n    return value",
    ),
    good_examples=("@validate_call\ndef label(value: Annotated[str, Field(min_length=1)]):\n    return value",),
    exclusions=("Ordinary functions are not runtime-validated by annotations alone.",),
)


def _model(guard: str, *, annotation: str = "str", mode: str = "after", extra: str = "") -> str:
    return dedent(f"""\
        from pydantic import BaseModel, Field, field_validator
        class Request(BaseModel):
            name: {annotation}
            @field_validator('name', mode='{mode}')
            @classmethod
            def require_name(cls, value):
                if {guard}:
                    raise ValueError('empty')
                {extra}
                return value
        """)


_CASES = (
    EvaluationCase(
        case_id="model-truthiness", language=Language.PYTHON, source=_model("not value"), expected=ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        case_id="model-empty-equality",
        language=Language.PYTHON,
        source=_model("value == ''"),
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="model-reversed-equality",
        language=Language.PYTHON,
        source=_model("'' == value"),
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="optional-field", language=Language.PYTHON, source=_model("not value", annotation="str | None")
    ),
    EvaluationCase(case_id="raw-before-input", language=Language.PYTHON, source=_model("not value", mode="before")),
    EvaluationCase(
        case_id="async-model-validator",
        language=Language.PYTHON,
        source=_model("not value").replace("def require_name", "async def require_name"),
    ),
    EvaluationCase(case_id="whitespace-semantics", language=Language.PYTHON, source=_model("not value.strip()")),
    EvaluationCase(
        case_id="normalizing-validator",
        language=Language.PYTHON,
        source=_model("not value", extra="value = value.lower()"),
    ),
    EvaluationCase(case_id="arbitrary-validation", language=Language.PYTHON, source=_model("value == 'reserved'")),
    EvaluationCase(
        case_id="unknown-string-alias", language=Language.PYTHON, source=_model("not value", annotation="ExternalText")
    ),
    EvaluationCase(
        case_id="ordinary-function",
        language=Language.PYTHON,
        source="def label(value: str):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="annotation-alone",
        language=Language.PYTHON,
        source="from typing import Annotated\nfrom pydantic import Field\ndef label(value: Annotated[str, Field(min_length=1)]):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="validated-function",
        language=Language.PYTHON,
        source="from pydantic import validate_call\n@validate_call\ndef label(value: str):\n    if not value:\n        raise ValueError('empty')\n    return f'prefix-{value}'\n",
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="validated-constrained-function",
        language=Language.PYTHON,
        source="from typing import Annotated\nfrom pydantic import Field, validate_call\n@validate_call\ndef label(value: Annotated[str, Field(min_length=1)]):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="generated-file",
        language=Language.PYTHON,
        source="# This file is auto-generated. Do not edit.\n" + _model("not value"),
    ),
    EvaluationCase(
        case_id="test-file",
        language=Language.PYTHON,
        source=_model("not value"),
        path=PurePosixPath("tests/test_models.py"),
    ),
    EvaluationCase(case_id="malformed-source", language=Language.PYTHON, source="class Request("),
    EvaluationCase(
        case_id="default-after-mode",
        language=Language.PYTHON,
        source=_model("not value").replace(", mode='after'", ""),
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="settings-boundary",
        language=Language.PYTHON,
        source=_model("not value")
        .replace(
            "from pydantic import BaseModel, Field, field_validator",
            "from pydantic import field_validator\nfrom pydantic_settings import BaseSettings",
        )
        .replace("Request(BaseModel)", "Request(BaseSettings)"),
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="non-model-validator",
        language=Language.PYTHON,
        source=_model("not value").replace("Request(BaseModel)", "Request"),
    ),
    EvaluationCase(
        case_id="existing-length-constraint",
        language=Language.PYTHON,
        source=_model("not value").replace("name: str", "name: str = Field(min_length=1)"),
    ),
    EvaluationCase(
        case_id="mixed-validator-fields",
        language=Language.PYTHON,
        source=_model("not value")
        .replace("name: str", "name: str\n    count: int")
        .replace("field_validator('name'", "field_validator('name', 'count'"),
    ),
    EvaluationCase(
        case_id="rebound-import",
        language=Language.PYTHON,
        source=_model("not value") + "field_validator = custom_validator\n",
    ),
    EvaluationCase(
        case_id="shadowed-builtin-string", language=Language.PYTHON, source="str = CustomString\n" + _model("not value")
    ),
    EvaluationCase(
        case_id="unknown-decorator",
        language=Language.PYTHON,
        source=_model("not value").replace("@classmethod", "@custom\n    @classmethod"),
    ),
    EvaluationCase(
        case_id="else-semantics",
        language=Language.PYTHON,
        source=_model("not value").replace("return value", "else:\n            return value"),
    ),
    EvaluationCase(
        case_id="additional-validation",
        language=Language.PYTHON,
        source=_model("not value", extra="if value == 'reserved': raise ValueError('reserved')"),
    ),
    EvaluationCase(case_id="wrapped-raw-input", language=Language.PYTHON, source=_model("not value", mode="wrap")),
    EvaluationCase(case_id="plain-raw-input", language=Language.PYTHON, source=_model("not value", mode="plain")),
    EvaluationCase(
        case_id="model-import-aliases",
        language=Language.PYTHON,
        source=_model("not value")
        .replace("BaseModel, Field, field_validator", "BaseModel as Model, Field, field_validator as validator")
        .replace("Request(BaseModel)", "Request(Model)")
        .replace("@field_validator", "@validator"),
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="replaced-module-decorator",
        language=Language.PYTHON,
        source="import pydantic as pd\npd.validate_call = custom\n@pd.validate_call\ndef label(value: str):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="nested-validated-function",
        language=Language.PYTHON,
        source="from pydantic import validate_call as validate\ndef build():\n    @validate\n    def label(value: str):\n        if not value:\n            raise ValueError('empty')\n        return value\n    return label\n",
        expected=ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        case_id="preceding-after-transform",
        language=Language.PYTHON,
        source=_model("not value").replace(
            "    @field_validator",
            "    @field_validator('name')\n    @classmethod\n    def trim_name(cls, value):\n        return value.strip()\n    @field_validator",
            1,
        ),
    ),
    EvaluationCase(
        case_id="assigned-validator-proxy",
        language=Language.PYTHON,
        source="def trim(value):\n    return value.strip()\n"
        + _model("not value").replace(
            "    @field_validator",
            "    normalize = field_validator('name')(trim)\n    @field_validator",
            1,
        ),
    ),
    EvaluationCase(
        case_id="additional-model-validator",
        language=Language.PYTHON,
        source=_model("not value")
        .replace("BaseModel, Field, field_validator", "BaseModel, Field, field_validator, model_validator")
        .replace(
            "    @field_validator",
            "    @model_validator(mode='after')\n    def check_model(self):\n        return self\n    @field_validator",
            1,
        ),
    ),
    EvaluationCase(
        case_id="positional-default",
        language=Language.PYTHON,
        source="from pydantic import validate_call\n@validate_call\ndef label(value: str = ''):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="keyword-only-default",
        language=Language.PYTHON,
        source="from pydantic import validate_call\n@validate_call\ndef label(*, value: str = ''):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="runtime-default",
        language=Language.PYTHON,
        source="from pydantic import validate_call\n@validate_call\ndef label(value: str = default_value()):\n    if not value:\n        raise ValueError('empty')\n    return value\n",
    ),
    EvaluationCase(
        case_id="outer-decorator-parameter",
        language=Language.PYTHON,
        source="from pydantic import validate_call\ndef build(validate_call):\n    @validate_call\n    def label(value: str):\n        if not value:\n            raise ValueError('empty')\n        return value\n    return label\n",
    ),
    EvaluationCase(
        case_id="outer-string-parameter",
        language=Language.PYTHON,
        source="from pydantic import validate_call\ndef build(str):\n    @validate_call\n    def label(value: str):\n        if not value:\n            raise ValueError('empty')\n        return value\n    return label\n",
    ),
    EvaluationCase(
        case_id="outer-model-parameter",
        language=Language.PYTHON,
        source="from pydantic import BaseModel, field_validator\ndef build(BaseModel):\n"
        + "\n".join("    " + line for line in _model("not value").splitlines()[1:]),
    ),
    EvaluationCase(
        case_id="local-decorator-import",
        language=Language.PYTHON,
        source="from pydantic import validate_call\ndef build():\n    from other import validate_call\n    @validate_call\n    def label(value: str):\n        if not value:\n            raise ValueError('empty')\n        return value\n    return label\n",
    ),
    EvaluationCase(
        case_id="private-model-attribute", language=Language.PYTHON, source=_model("not value").replace("name", "_name")
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = PreferDeclarativeNonEmptyString().check(Path(case.path), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "example",
    PreferDeclarativeNonEmptyString.public_examples(),
    ids=tuple(example.example_id for example in PreferDeclarativeNonEmptyString.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferDeclarativeNonEmptyString().check(Path(focus.path), focus.source)) == example.expected_count


def test_preserves_explicit_suppression_and_aliases() -> None:
    source = "import pydantic as pd\n@pd.validate_call\ndef label(value: str):\n    if not value:  # sarj-noqa:SARJ484 — intentional custom error contract\n        raise ValueError('empty')\n    return value\n"
    assert PreferDeclarativeNonEmptyString().check(Path("app.py"), source) == []
    findings = PreferDeclarativeNonEmptyString().check(
        Path("app.py"), source.replace("  # sarj-noqa:SARJ484 — intentional custom error contract", "")
    )
    assert len(findings) == 1
    assert findings[0].line == 4


def test_local_names_do_not_impersonate_pydantic_decorators() -> None:
    source = "def validate_call(function):\n    return function\n@validate_call\ndef label(value: str):\n    if not value:\n        raise ValueError('empty')\n    return value\n"
    assert PreferDeclarativeNonEmptyString().check(Path("app.py"), source) == []
