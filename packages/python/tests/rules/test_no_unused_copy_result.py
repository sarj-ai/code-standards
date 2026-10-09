from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_unused_copy_result import NoUnusedCopyResult


_MODEL = "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\n"
_CASES = (
    EvaluationCase(
        "discarded-model-copy",
        Language.PYTHON,
        _MODEL + "def update(record: Record):\n    record.model_copy(update={'name': 'new'})\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "discarded-constructor-copy",
        Language.PYTHON,
        _MODEL + "record = Record(name='old')\nrecord.model_copy(update={'name': 'new'})\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dataclasses-alias",
        Language.PYTHON,
        "from dataclasses import replace as updated\ndef update(record):\n    updated(record, name='new')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "copy-module",
        Language.PYTHON,
        "import copy\ndef update(record):\n    copy.replace(record, name='new')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "consumed-model-copy",
        Language.PYTHON,
        _MODEL + "def update(record: Record):\n    return record.model_copy(update={'name': 'new'})\n",
    ),
    EvaluationCase(
        "consumed-dataclass-copy",
        Language.PYTHON,
        "from dataclasses import replace\ndef update(record):\n    updated = replace(record, name='new')\n    return updated\n",
    ),
    EvaluationCase("unknown-method", Language.PYTHON, "def update(record):\n    record.model_copy()\n"),
    EvaluationCase(
        "shadowed-import",
        Language.PYTHON,
        "from dataclasses import replace\ndef update(record, replace):\n    replace(record, name='new')\n",
    ),
    EvaluationCase(
        "custom-model-copy",
        Language.PYTHON,
        _MODEL
        + "class Custom(Record):\n    def model_copy(self):\n        return unknown()\ndef update(record: Custom):\n    record.model_copy()\n",
    ),
    EvaluationCase(
        "arbitrary-replace-method", Language.PYTHON, "def update(record):\n    record.replace(name='new')\n"
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "def update(:\n"),
    EvaluationCase(
        "expected-copy-exception",
        Language.PYTHON,
        "import pytest as testing\nfrom dataclasses import replace\ndef test_invalid(record):\n    with testing.raises(ValueError):\n        replace(record, name='invalid')\n",
    ),
    EvaluationCase(
        "shadowed-exception-helper",
        Language.PYTHON,
        "import pytest\nfrom dataclasses import replace\ndef update(record, pytest):\n    with pytest.raises(ValueError):\n        replace(record, name='new')\n",
        ExpectedOutcome.MATCH,
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_copy_cases(case: EvaluationCase) -> None:
    findings = NoUnusedCopyResult().check(Path("app/records.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_documented_examples() -> None:
    verify_native_rule(NoUnusedCopyResult, analyze)


def test_module_result_location_and_suppression() -> None:
    source = "from copy import replace\nreplace(record, name='new')\n"
    rule = NoUnusedCopyResult()
    [finding] = rule.check(Path("app/records.py"), source)
    assert (finding.code, finding.line, finding.col) == ("SARJ483", 2, 1)
    assert (
        rule.check(Path("app/records.py"), f"{source.rstrip()}  # sarj-noqa: SARJ483 — exercise a raising copy hook\n")
        == []
    )


def test_generated_sources_are_excluded() -> None:
    assert NoUnusedCopyResult().check(Path("generated/records.py"), _CASES[2].source) == []
