"""Typed contracts for designing and evaluating deterministic lint rules."""

from .catalog import RuleCatalog
from .contracts import (
    AutofixPolicy,
    CatalogRule,
    EvaluationCase,
    ExpectedOutcome,
    Finding,
    Language,
    RuleOrigin,
    RuleProblem,
)
from .evaluation import (
    CaseEvaluation,
    EvaluationEvidence,
    EvaluationReport,
    EvaluationThresholds,
    PromotionDecision,
    RuleEvaluator,
    evaluate,
)


__all__ = [
    "AutofixPolicy",
    "CaseEvaluation",
    "CatalogRule",
    "EvaluationCase",
    "EvaluationEvidence",
    "EvaluationReport",
    "EvaluationThresholds",
    "ExpectedOutcome",
    "Finding",
    "Language",
    "PromotionDecision",
    "RuleCatalog",
    "RuleEvaluator",
    "RuleOrigin",
    "RuleProblem",
    "evaluate",
]
