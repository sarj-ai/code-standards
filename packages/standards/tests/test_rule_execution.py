from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import (
    Completion,
    RuleExecution,
    RuleExecutionState,
    ToolReport,
    to_github,
    to_sarif,
    to_text,
)
from sarj_standards.libs.linting.analysis import report_from_tools


if TYPE_CHECKING:
    from pathlib import Path


def test_unknown_prerequisites_cannot_be_reported_as_ran() -> None:
    with pytest.raises(ValueError, match="must declare"):
        RuleExecution("@sarj/probe", RuleExecutionState.RAN, 1, None)


def test_skipped_checks_explain_their_reason() -> None:
    with pytest.raises(ValueError, match="explain"):
        RuleExecution("@sarj/probe", RuleExecutionState.SKIPPED, 1, True)


def test_completed_checks_cannot_claim_missing_prerequisites() -> None:
    with pytest.raises(ValueError, match="unevaluated reason"):
        RuleExecution("@sarj/probe", RuleExecutionState.RAN, 1, True, "missing-type-information")


@pytest.mark.parametrize("state", [RuleExecutionState.DISABLED, RuleExecutionState.UNTRACKED])
def test_missing_types_only_explain_a_skipped_check(state: RuleExecutionState) -> None:
    with pytest.raises(ValueError, match="skipped, explicitly typed"):
        RuleExecution("@sarj/probe", state, 1, True, "missing-type-information")


def test_failed_rule_execution_cannot_be_a_complete_tool() -> None:
    row = RuleExecution("@sarj/probe", RuleExecutionState.FAILED, 1, False, "rule-execution-failed")
    with pytest.raises(ValueError, match="failed rule executions"):
        ToolReport("eslint", Completion.COMPLETE, rule_executions=(row,))


def test_skipped_semantic_checks_are_visible_without_new_source_diagnostics(tmp_path: Path) -> None:
    row = RuleExecution(
        "@sarj/no-known-value-widening", RuleExecutionState.SKIPPED, 1, True, "missing-type-information"
    )
    report = report_from_tools(tmp_path, (ToolReport("eslint", Completion.COMPLETE, rule_executions=(row,)),))
    assert report.exit_code == 0
    assert report.diagnostics == ()
    for rendered in (to_text(report), to_github(report), to_sarif(report)):
        assert "missing-type-information" in rendered
        assert "@sarj/no-known-value-widening skipped on 1 file(s)" in rendered
    assert "0 error(s), 0 warning(s), 0 notice(s), 0 execution issue(s)" in to_text(report)


def test_legacy_unknown_requirements_render_as_one_group(tmp_path: Path) -> None:
    rows = tuple(
        RuleExecution(rule, RuleExecutionState.UNTRACKED, 1, None, "requirements-not-declared")
        for rule in ("@sarj/first", "@sarj/second")
    )
    report = report_from_tools(tmp_path, (ToolReport("eslint", Completion.COMPLETE, rule_executions=rows),))
    rendered = to_text(report)
    assert rendered.count("code-standards execution:") == 1
    assert "2 rule(s) untracked: requirements-not-declared" in rendered
    assert report.exit_code == 0
