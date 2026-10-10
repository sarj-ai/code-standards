import pytest

from sarj_standards.libs.rules.contracts import EvaluationCase, ExpectedOutcome, Finding, Language, RuleProblem
from sarj_standards.libs.rules.evaluation import evaluate


def _problem() -> RuleProblem:
    return RuleProblem(
        "public-policy", "Public policy", "Public harm", frozenset({Language.PYTHON}), ("pass\n",), ("return 1\n",)
    )


def test_duplicate_case_ids_cannot_inflate_promotion_evidence() -> None:
    case = EvaluationCase("stable-label", Language.PYTHON, "pass\n", ExpectedOutcome.MATCH)
    with pytest.raises(ValueError, match="duplicate evaluation case ID: stable-label"):
        evaluate(_problem(), "public-policy", [case] * 20, lambda _: [Finding("public-policy", 1, 1, "public finding")])


def test_private_duplicate_ids_are_redacted_before_reporting() -> None:
    case = EvaluationCase("private-label", Language.PYTHON, "pass\n", private=True)
    with pytest.raises(ValueError, match="duplicate evaluation case ID: <private>") as error:
        evaluate(_problem(), "public-policy", [case, case], lambda _: [])
    assert "private-label" not in str(error.value)


def test_equal_source_with_distinct_ids_remains_valid_evidence() -> None:
    cases = [
        EvaluationCase(label, Language.PYTHON, "pass\n", ExpectedOutcome.MATCH)
        for label in ["first-scenario", "second-scenario"]
    ]
    report = evaluate(_problem(), "public-policy", cases, lambda _: [Finding("public-policy", 1, 1, "public finding")])
    assert report.true_positives == len(cases)


def test_case_identity_scope_is_one_rule_evaluation() -> None:
    case = EvaluationCase("stable-label", Language.PYTHON, "return 1\n")
    for selector in ["first-policy", "second-policy"]:
        assert evaluate(_problem(), selector, [case], lambda _: []).true_negatives == 1
