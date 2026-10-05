from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_before_validator_input_mutation import NoBeforeValidatorInputMutation


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic

_HEADER = "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
_DECORATOR = "    @model_validator(mode='before')\n    @classmethod\n"
_BAD = {
    "raw-item-write": "    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
    "stable-alias": "    def normalize(cls, data: dict[str, object]):\n        alias = data\n        alias['name'] = 'new'\n        return data\n",
    "typed-pop": "    def normalize(cls, data: dict[str, object]):\n        data.pop('legacy', None)\n        return data\n",
    "narrowed-input": "    def normalize(cls, data: object):\n        if isinstance(data, dict):\n            data.pop('legacy', None)\n        return data\n",
    "unknown-raw-type-write": "    def normalize(cls, data: object):\n        data['name'] = 'new'\n        return data\n",
    "shallow-dict-child": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = dict(data)\n        copied['nested']['name'] = 'new'\n        return copied\n",
}
_GOOD = {
    "copy-before-write": "    def normalize(cls, data: dict[str, object]):\n        data = dict(data)\n        data['name'] = 'new'\n        return data\n",
    "dict-expansion": "    def normalize(cls, data: dict[str, object]):\n        return {**data, 'name': 'new'}\n",
    "copy-before-pop": "    def normalize(cls, data: dict[str, object]):\n        copied = data.copy()\n        copied.pop('legacy', None)\n        return copied\n",
    "unknown-method": "    def normalize(cls, data: object):\n        data.pop('legacy')\n        return data\n",
    "nested-function-shadowing": "    def normalize(cls, data):\n        def helper(data):\n            data['name'] = 'new'\n        return data\n",
}
_GOOD.update(
    {
        "spread-with-fresh-child": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = {**data, 'nested': {}}\n        copied['nested']['name'] = 'new'\n        return copied\n",
        "fresh-child-assignment": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = dict(data)\n        copied['nested'] = {}\n        copied['nested']['name'] = 'new'\n        return copied\n",
    }
)
_BAD.update(
    {
        "spread-shares-nested-values": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = {**data}\n        copied['nested']['name'] = 'new'\n        return copied\n",
        "guard-before-mutator": "    def normalize(cls, data: object):\n        if not isinstance(data, dict):\n            return data\n        data.pop('legacy', None)\n        return data\n",
        "cast-retains-input-identity": "    def normalize(cls, data: object):\n        from typing import cast\n        payload = cast(dict[str, object], data)\n        payload.pop('legacy', None)\n        return payload\n",
    }
)
_CASES = (
    EvaluationCase(
        "fresh-dict-keyword-override",
        Language.PYTHON,
        _HEADER
        + _DECORATOR
        + "    def normalize(cls, data: dict[str, object]):\n        copied = dict(data, nested={})\n        copied['nested']['name'] = 'new'\n        return copied\n",
    ),
    *(
        EvaluationCase(key, Language.PYTHON, _HEADER + _DECORATOR + source, ExpectedOutcome.MATCH)
        for key, source in _BAD.items()
    ),
    *(EvaluationCase(key, Language.PYTHON, _HEADER + _DECORATOR + source) for key, source in _GOOD.items()),
    EvaluationCase(
        "after-validator",
        Language.PYTHON,
        _HEADER
        + "    @model_validator(mode='after')\n    def normalize(self):\n        self.name = 'new'\n        return self\n",
    ),
    EvaluationCase(
        "shadowed-decorator",
        Language.PYTHON,
        "def model_validator(**kwargs): return unknown\n"
        + _HEADER.replace(", model_validator", "")
        + _DECORATOR
        + "    def normalize(cls, data):\n        data['name'] = 'new'\n",
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "def normalize(:\n"),
)


def _check(source: str, path: Path = Path("app/models.py")) -> list[Diagnostic]:
    return NoBeforeValidatorInputMutation().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_validator_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert all(finding.code == "SARJ482" for finding in findings)


def test_documented_examples() -> None:
    verify_native_rule(NoBeforeValidatorInputMutation, analyze)


def test_field_validator_alias() -> None:
    source = (
        "from pydantic import BaseModel, field_validator as validate\n"
        "class Record(BaseModel):\n    tags: list[str]\n"
        "    @validate('tags', mode='before')\n    @classmethod\n"
        "    def normalize(cls, values: list[str]):\n        values.sort()\n        return values\n"
    )
    [finding] = _check(source)
    assert (finding.line, finding.col) == (7, 9)


def test_exact_suppression_and_generated_sources() -> None:
    source = (_HEADER + _DECORATOR + _BAD["raw-item-write"]).replace(
        "data['name'] = 'new'", "data['name'] = 'new'  # sarj-noqa: SARJ482 — explicitly shared normalization"
    )
    assert _check(source) == []
    assert _check(_HEADER + _DECORATOR + _BAD["raw-item-write"], Path("generated/models.py")) == []
