from __future__ import annotations

from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_outcome_variants import PreferOutcomeVariants


def test_documented_examples() -> None:
    verify_native_rule(PreferOutcomeVariants, analyze)
