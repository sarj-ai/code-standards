from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

import pytest

from sarj_rule_contracts import (
    DefaultLevel,
    ExampleFile,
    ExpectedOutcome,
    Language,
    RuleCategory,
    RuleDocumentation,
    RuleEngine,
    RuleExample,
    RuleId,
    RuleSpec,
)


def _example(outcome: ExpectedOutcome, *, public: bool = False) -> RuleExample:
    return RuleExample(
        example_id=outcome.value,
        outcome=outcome,
        files=(ExampleFile.python("app.py", "value = 1\n"),),
        focus_path=PurePosixPath("app.py"),
        expected_count=int(outcome is ExpectedOutcome.MATCH),
        title="An executable example",
        public=public,
    )


def _documentation(*examples: RuleExample) -> RuleDocumentation:
    return RuleDocumentation(
        summary="Detect an observable defect.",
        rationale="A concrete defect loses data.",
        remediation="Preserve the value.",
        category=RuleCategory.CORRECTNESS,
        default_level=DefaultLevel.WARNING,
        examples=examples,
    )


@pytest.mark.parametrize("path", ["/absolute.py", "../escape.py", "folder/../escape.py", "folder\\escape.py"])
def test_example_paths_cannot_escape_the_fixture(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative paths"):
        ExampleFile.python(path, "value = 1\n")


def test_private_examples_do_not_require_a_public_pair() -> None:
    documentation = _documentation(_example(ExpectedOutcome.MATCH))

    assert documentation.examples[0].public is False
    assert documentation.examples[0].focus_file.source == "value = 1\n"


def test_public_scenarios_require_both_outcomes() -> None:
    accepted = _example(ExpectedOutcome.NO_MATCH, public=True)
    rejected = _example(ExpectedOutcome.MATCH, public=True)

    with pytest.raises(ValueError, match="both matching and non-matching"):
        _documentation(rejected)
    assert len(_documentation(accepted, rejected).examples) == 2


def test_matching_and_clean_cases_have_consistent_expected_counts() -> None:
    with pytest.raises(ValueError, match="at least one"):
        replace(_example(ExpectedOutcome.MATCH), expected_count=0)
    with pytest.raises(ValueError, match="zero diagnostics"):
        replace(_example(ExpectedOutcome.NO_MATCH), expected_count=1)


def test_catalog_spec_preserves_native_documentation_contract() -> None:
    documentation = _documentation(_example(ExpectedOutcome.MATCH), _example(ExpectedOutcome.NO_MATCH))
    spec = RuleSpec(
        engine=RuleEngine.PYTHON,
        rule_id=RuleId("observable-defect"),
        code="SARJ499",
        languages=frozenset({Language.PYTHON}),
        summary=documentation.summary,
        rationale=documentation.rationale,
        remediation=documentation.remediation,
        category=documentation.category,
        examples=documentation.examples,
        default_level=documentation.default_level,
    )

    assert spec.key == "python:observable-defect"
    assert spec.default_level is DefaultLevel.WARNING
    with pytest.raises(ValueError, match="historical"):
        replace(spec, aliases=("observable-defect",))
    with pytest.raises(ValueError, match="summary"):
        replace(spec, summary="")
