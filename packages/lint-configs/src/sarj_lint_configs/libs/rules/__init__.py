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
from .corpus_runner import (
    CorpusBatchResult,
    CorpusLintError,
    IsolatedCorpusReport,
    run_isolated_corpora,
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
    "CorpusBatchResult",
    "CorpusLintError",
    "EvaluationCase",
    "EvaluationEvidence",
    "EvaluationReport",
    "EvaluationThresholds",
    "ExpectedOutcome",
    "Finding",
    "IsolatedCorpusReport",
    "Language",
    "PromotionDecision",
    "RuleCatalog",
    "RuleEvaluator",
    "RuleOrigin",
    "RuleProblem",
    "evaluate",
    "run_isolated_corpora",
]
