from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting import security_tools
from sarj_standards.libs.linting.external import analyze_external


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.diagnostics import Diagnostic


def _workflow(path: Path, trigger: str, *, workflow_cache: str = "", job_cache: str = "") -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        f"name: Security fixture\non: {trigger}\npermissions: {{}}\n"
        + (f"cache-mode: {workflow_cache}\n" if workflow_cache else "")
        + "jobs:\n  audit:\n"
        + (f"    cache-mode: {job_cache}\n" if job_cache else "")
        + "    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n",
        encoding="utf-8",
    )


def _analyze(path: Path) -> tuple[Diagnostic, ...]:
    reports = analyze_external(
        [str(path)], root=path.parents[2], trust=TrustMode.SAFE, capabilities=frozenset({"zizmor"})
    )
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].version == security_tools.VERSIONS["zizmor"]
    return reports[0].diagnostics


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        ("issue_comment", True),
        ("[push, issue_comment]", True),
        ("push", False),
        ("pull_request", False),
    ],
)
def test_issue_comment_is_dangerous_but_unprivileged_triggers_are_not(
    tmp_path: Path, trigger: str, expected: bool
) -> None:
    path = tmp_path / ".github/workflows/workflow.yml"
    _workflow(path, trigger)
    findings = [item for item in _analyze(path) if item.rule_id == "dangerous-triggers"]
    assert len(findings) == int(expected)
    if findings:
        assert findings[0].severity is Severity.WARNING
        assert findings[0].location.path == ".github/workflows/workflow.yml"
        assert findings[0].location.position is not None
        assert findings[0].location.position.line == 1


@pytest.mark.parametrize(
    ("trigger", "workflow_cache", "job_cache", "expected"),
    [
        pytest.param("issue_comment", "write", "", 1, id="workflow-write-is-dangerous"),
        pytest.param("issue_comment", "", "write-only", 1, id="job-write-only-is-dangerous"),
        pytest.param("issue_comment", "write", "none", 0, id="job-none-overrides-workflow-write"),
        pytest.param("issue_comment", "none", "write", 1, id="job-write-overrides-workflow-none"),
        pytest.param("issue_comment", "", "read", 0, id="read-only-cache-is-safe"),
        pytest.param("issue_comment", "", "", 0, id="implicit-read-cache-is-safe"),
        pytest.param("push", "write", "", 0, id="trusted-trigger-can-write-cache"),
    ],
)
def test_cache_writes_follow_effective_mode_and_trigger_privileges(
    tmp_path: Path, trigger: str, workflow_cache: str, job_cache: str, expected: int
) -> None:
    path = tmp_path / ".github/workflows/workflow.yml"
    _workflow(path, trigger, workflow_cache=workflow_cache, job_cache=job_cache)
    findings = [item for item in _analyze(path) if item.rule_id == "cache-poisoning"]
    assert len(findings) == expected
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize(
    "trigger",
    [
        "issue_comment # zizmor: ignore[dangerous-triggers]",
        "# zizmor: ignore[dangerous-triggers]\n  issue_comment:",
    ],
    ids=["trigger-line-ignore", "whole-trigger-block-ignore"],
)
def test_trigger_ignore_applies_upstream_while_standards_baseline_remains_canonical(
    tmp_path: Path, trigger: str
) -> None:
    path = tmp_path / ".github/workflows/workflow.yml"
    _workflow(path, trigger)
    upstream = subprocess.run(
        [
            *security_tools.command("zizmor"),
            "--offline",
            "--format=sarif",
            "--no-exit-codes",
            "--strict-collection",
            "--config",
            str(CONFIGS_DIR / "zizmor.strict.yml"),
            "--",
            str(path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    findings = security_tools.parse_zizmor(upstream.stdout, root=tmp_path)
    assert not any(item.rule_id == "dangerous-triggers" for item in findings)
    assert sum(item.rule_id == "dangerous-triggers" for item in _analyze(path)) == 1
