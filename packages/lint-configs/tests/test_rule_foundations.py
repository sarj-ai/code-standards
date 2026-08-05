"""Rule design contracts reject ambiguity and report evidence without source leaks."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.rules import (
    CatalogRule,
    EvaluationCase,
    EvaluationThresholds,
    ExpectedOutcome,
    Finding,
    Language,
    PromotionDecision,
    RuleCatalog,
    RuleOrigin,
    RuleProblem,
    evaluate,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


def _problem() -> RuleProblem:
    return RuleProblem(
        key="no-placeholder-pass",
        summary="Reject placeholder pass statements.",
        harm="A placeholder can silently ship an incomplete branch.",
        languages=frozenset({Language.PYTHON}),
        bad_examples=("def f():\n    pass\n",),
        good_examples=("def f():\n    return None\n",),
        exclusions=("protocol and abstract method bodies",),
    )


def test_problem_requires_positive_and_negative_examples() -> None:
    with pytest.raises(ValueError, match="both bad and good"):
        RuleProblem(
            key="incomplete",
            summary="summary",
            harm="harm",
            languages=frozenset({Language.PYTHON}),
            bad_examples=(),
            good_examples=("ok",),
        )


def test_catalog_filters_existing_rules_without_fuzzy_matching() -> None:
    upstream = CatalogRule(
        "ruff:PIE790",
        "Reject unnecessary pass statements.",
        RuleOrigin.UPSTREAM,
        frozenset({Language.PYTHON}),
        configurable=True,
        documentation="https://docs.astral.sh/ruff/rules/unnecessary-pass/",
    )
    custom = CatalogRule(
        "SARJ001",
        "Example custom rule.",
        RuleOrigin.SARJ,
        frozenset({Language.PYTHON}),
    )
    catalog = RuleCatalog.from_rules((custom, upstream))

    assert catalog.get("ruff:PIE790") is upstream
    assert catalog.get("pie790") is None
    assert catalog.filter(language=Language.PYTHON, origin=RuleOrigin.UPSTREAM) == (upstream,)


def test_evaluation_reports_metrics_and_warning_first_decision() -> None:
    cases = (
        EvaluationCase(
            "bad",
            Language.PYTHON,
            "def f():\n    pass\n",
            ExpectedOutcome.MATCH,
            PurePosixPath("bad.py"),
        ),
        EvaluationCase(
            "good",
            Language.PYTHON,
            "def f():\n    return None\n",
            ExpectedOutcome.NO_MATCH,
            PurePosixPath("good.py"),
        ),
    )

    def checker(case: EvaluationCase) -> Sequence[Finding]:
        return (Finding("TEST001", 2, 5, "placeholder"),) if "pass" in case.source else ()

    report = evaluate(_problem(), "TEST001", cases, checker)

    assert report.true_positives == 1
    assert report.true_negatives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.decision is PromotionDecision.WARN


def test_false_positive_or_duplicate_location_rejects_promotion() -> None:
    case = EvaluationCase("good", Language.PYTHON, "return None", ExpectedOutcome.NO_MATCH)

    def checker(_case: EvaluationCase) -> Sequence[Finding]:
        return (
            Finding("TEST001", 1, 1, "first"),
            Finding("TEST001", 1, 1, "duplicate"),
        )

    report = evaluate(
        _problem(),
        "TEST001",
        (case,),
        checker,
        thresholds=EvaluationThresholds(minimum_cases_for_error=1),
    )

    assert report.false_positives == 1
    assert report.duplicate_locations == (("good", 1, 1),)
    assert report.decision is PromotionDecision.REJECT


def test_clean_one_sided_cases_cannot_promote_to_error() -> None:
    cases = tuple(EvaluationCase(f"negative-{index}", Language.PYTHON, "return None") for index in range(20))

    report = evaluate(_problem(), "TEST001", cases, lambda _case: ())

    assert report.decision is PromotionDecision.WARN


def test_candidate_cannot_claim_another_rules_findings() -> None:
    case = EvaluationCase("bad", Language.PYTHON, "pass", ExpectedOutcome.MATCH)

    with pytest.raises(ValueError, match="returned findings for: OTHER001"):
        evaluate(_problem(), "TEST001", (case,), lambda _case: (Finding("OTHER001", 1, 1, "overlap"),))


def test_private_case_source_and_layout_do_not_enter_report() -> None:
    secret = "private-customer-token"
    case = EvaluationCase(
        "private-case",
        Language.PYTHON,
        secret,
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("customer/internal.py"),
        private=True,
    )

    report = evaluate(
        _problem(),
        "TEST001",
        (case,),
        lambda _case: (Finding("TEST001", 1, 1, f"matched {secret}"),),
    )

    assert secret not in repr(case)
    assert secret not in repr(report)
    assert report.cases[0].path == "<private>"
    assert report.cases[0].case_id.startswith("<private:")
    assert "private-case" not in repr(report)
    assert report.cases[0].findings[0].message == "<private-finding>"
