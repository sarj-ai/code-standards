"""Side-effect-free evaluation of candidate rules against labeled cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from sarj_standards.libs.corpus import CorpusSnapshot

from .contracts import EvaluationCase, ExpectedOutcome, Finding, RuleProblem


if TYPE_CHECKING:
    from collections.abc import Sequence


class RuleEvaluator(Protocol):
    """Adapter implemented by a language-specific candidate checker."""

    def __call__(self, case: EvaluationCase, /) -> Sequence[Finding]: ...


class PromotionDecision(StrEnum):
    """Evidence-based rollout state for a candidate rule."""

    REJECT = "reject"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    """Explicit gates; defaults forbid false positives and false negatives."""

    max_false_positives: int = 0
    max_false_negatives: int = 0
    minimum_cases_for_error: int = 20
    minimum_positives_for_error: int = 1
    minimum_negatives_for_error: int = 1

    def __post_init__(self) -> None:
        if (
            min(
                self.max_false_positives,
                self.max_false_negatives,
                self.minimum_cases_for_error,
                self.minimum_positives_for_error,
                self.minimum_negatives_for_error,
            )
            < 0
        ):
            msg = "evaluation thresholds must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    """Report-safe outcome that deliberately excludes source text."""

    case_id: str
    path: str
    expected: ExpectedOutcome
    findings: tuple[Finding, ...]

    @property
    def matched(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """Reproducibility and performance evidence for an evaluated run."""

    corpora: tuple[CorpusSnapshot, ...]
    sample_method: str
    elapsed: timedelta
    baseline: timedelta
    maximum_slowdown: float = 1.25

    def __post_init__(self) -> None:
        if not self.corpora or not all(corpus.verified for corpus in self.corpora) or not self.sample_method.strip():
            msg = "evaluation evidence requires verified corpora and a sampling method"
            raise ValueError(msg)
        if self.elapsed < timedelta() or self.baseline <= timedelta() or self.maximum_slowdown <= 0:
            msg = "evaluation timings require a positive baseline and slowdown budget"
            raise ValueError(msg)

    @property
    def within_performance_budget(self) -> bool:
        return self.elapsed <= self.baseline * self.maximum_slowdown


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Complete evidence required to decide whether a rule may roll out."""

    problem_key: str
    rule_id: str
    cases: tuple[CaseEvaluation, ...]
    thresholds: EvaluationThresholds
    evidence: EvaluationEvidence | None = None

    @property
    def true_positives(self) -> int:
        return sum(case.expected is ExpectedOutcome.MATCH and case.matched for case in self.cases)

    @property
    def true_negatives(self) -> int:
        return sum(case.expected is ExpectedOutcome.NO_MATCH and not case.matched for case in self.cases)

    @property
    def false_positives(self) -> int:
        return sum(case.expected is ExpectedOutcome.NO_MATCH and case.matched for case in self.cases)

    @property
    def false_negatives(self) -> int:
        return sum(case.expected is ExpectedOutcome.MATCH and not case.matched for case in self.cases)

    @property
    def duplicate_locations(self) -> tuple[tuple[str, int, int], ...]:
        duplicates: list[tuple[str, int, int]] = []
        for case in self.cases:
            seen: set[tuple[int, int]] = set()
            for finding in case.findings:
                location = (finding.line, finding.column)
                if location in seen:
                    duplicates.append((case.case_id, *location))
                seen.add(location)
        return tuple(duplicates)

    @property
    def decision(self) -> PromotionDecision:
        if (
            self.false_positives > self.thresholds.max_false_positives
            or self.false_negatives > self.thresholds.max_false_negatives
            or self.duplicate_locations
            or not self.cases
        ):
            return PromotionDecision.REJECT
        if self.false_positives or self.false_negatives:
            return PromotionDecision.WARN
        positives = self.true_positives + self.false_negatives
        negatives = self.true_negatives + self.false_positives
        if (
            len(self.cases) < self.thresholds.minimum_cases_for_error
            or positives < self.thresholds.minimum_positives_for_error
            or negatives < self.thresholds.minimum_negatives_for_error
            or self.evidence is None
            or not self.evidence.within_performance_budget
        ):
            return PromotionDecision.WARN
        return PromotionDecision.ERROR


def evaluate(
    problem: RuleProblem,
    rule_id: str,
    cases: Sequence[EvaluationCase],
    evaluator: RuleEvaluator,
    *,
    thresholds: EvaluationThresholds | None = None,
    evidence: EvaluationEvidence | None = None,
) -> EvaluationReport:
    """Evaluate cases in declared order and return a source-free report."""
    unsupported = [case.report_id for case in cases if case.language not in problem.languages]
    if unsupported:
        msg = f"cases use languages outside the problem: {', '.join(unsupported)}"
        raise ValueError(msg)
    outcomes: list[CaseEvaluation] = []
    for index, case in enumerate(cases, start=1):
        findings = tuple(evaluator(case))
        wrong = sorted({finding.rule_id for finding in findings if finding.rule_id != rule_id})
        if wrong:
            msg = f"candidate {rule_id} returned findings for: {', '.join(wrong)}"
            raise ValueError(msg)
        outcomes.append(
            CaseEvaluation(
                f"<private:{index}>" if case.private else case.report_id,
                case.report_path,
                case.expected,
                _report_findings(case, findings),
            )
        )
    return EvaluationReport(problem.key, rule_id, tuple(outcomes), thresholds or EvaluationThresholds(), evidence)


def _report_findings(case: EvaluationCase, findings: Sequence[Finding]) -> tuple[Finding, ...]:
    if not case.private:
        return tuple(findings)
    return tuple(Finding(finding.rule_id, finding.line, finding.column, "<private-finding>") for finding in findings)
