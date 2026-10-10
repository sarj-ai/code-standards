from __future__ import annotations

from datetime import UTC, datetime
import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from repo_standards.core.models import (
    ComponentId,
    Diagnostic as RepositoryDiagnostic,
    FindingsReport,
    Mode,
    PassedReport,
    PolicyId,
    RatchetClassification,
    RatchetComparison,
    RatchetEntry,
    RelatedLocation as RepositoryRelatedLocation,
    Remediation,
    RepositoryId,
    RuleId,
    SourceLocation,
)
from repo_standards.policy_sarj import SarjPolicy

from sarj_standards import api
from sarj_standards.libs.linting import repo_standards


if TYPE_CHECKING:
    from pathlib import Path

    from repo_standards.repository import RepositoryAnalysisRequest


def _makefile_severity() -> str:
    return next(
        rule.default_severity
        for rule in SarjPolicy.rules()
        if str(rule.rule_id) == "repository/artifacts/makefile-growth"
    )


def _commit(repository: Path) -> None:
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Standards Test",
            "-c",
            "user.email=standards-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test: initialize fixture",
        ),
        cwd=repository,
        check=True,
    )


def _adopt(repository: Path) -> Path:
    (repository / ".sarj-standards.toml").write_text(
        f'schema = 4\nbundle = "{api.__version__}"\n[hooks]\nmanager = "none"\n',
        encoding="utf-8",
    )
    manifest = repository / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_text(
        'repository_id = "fixture"\ncomponents = []\n',
        encoding="utf-8",
    )
    return manifest


def test_policy_analysis_composes_repo_standards_in_process(tmp_path: Path) -> None:
    _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 0
    assert [tool.name for tool in report.tools].count("repo-standards") == 1


def test_staged_policy_analysis_reads_repo_manifest_from_index(tmp_path: Path) -> None:
    manifest = _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)
    manifest.write_text("not valid TOML\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze((), staged=True)

    assert report.exit_code == 0
    assert not report.issues


def test_invalid_committed_repo_manifest_is_an_execution_issue(tmp_path: Path) -> None:
    manifest = _adopt(tmp_path)
    manifest.write_text("not valid TOML\n", encoding="utf-8")
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].source == "repo-standards"


def test_staged_manifest_deletion_cannot_be_hidden_by_worktree_recreation(tmp_path: Path) -> None:
    manifest = _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)
    subprocess.run(("git", "rm", str(manifest)), cwd=tmp_path, check=True, capture_output=True)
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(
        'repository_id = "unstaged"\ncomponents = []\n',
        encoding="utf-8",
    )

    report = api.Standards(tmp_path).analyze((), staged=True)

    assert report.exit_code == 2
    assert report.issues[0].kind == "analysis.manifest-absent"


def test_staged_manifest_addition_survives_worktree_deletion_on_first_commit(tmp_path: Path) -> None:
    manifest = _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True)
    manifest.unlink()

    report = api.Standards(tmp_path).analyze((), staged=True)

    assert report.exit_code == 0
    assert [tool.name for tool in report.tools].count("repo-standards") == 1


def test_committed_policy_waits_for_the_first_commit(tmp_path: Path) -> None:
    _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 0
    assert not [tool for tool in report.tools if tool.name == "repo-standards"]


def test_committed_manifest_deletion_fails_closed(tmp_path: Path) -> None:
    manifest = _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)
    manifest.unlink()
    _commit(tmp_path)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].kind == "analysis.manifest-absent"


def test_repository_adapter_failures_become_execution_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _adopt(tmp_path)

    def fail(
        _root: Path,
        *,
        staged: bool,  # ruff: ignore[unused-function-argument] -- adapter callback fixes this keyword.
    ) -> None:
        message = "incompatible dependency contract"
        raise TypeError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- repository adapter interception is the behavior under test.
        repo_standards, "analyze", fail
    )
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].kind == "integration-failure"


@pytest.mark.parametrize(
    ("rule_id", "expected_severity", "baselined_count"),
    [("repository.test", "info", 1), ("repository/artifacts/makefile-growth", "error", 0)],
)
def test_repository_diagnostic_preserves_ranges_and_related_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
    expected_severity: str,
    baselined_count: int,
) -> None:
    diagnostic = RepositoryDiagnostic(
        rule_id=RuleId(rule_id),
        rule_version=1,
        severity="error",
        evidence_level="verified",
        component_id=ComponentId("repository"),
        subject_kind="file",
        observed="old",
        expected="new",
        message="replace the value",
        path="config.toml",
        manifest_anchor="rules.test",
        remediation=Remediation("Update it.", ("Edit it.",), ("Check it.",)),
        location=SourceLocation("config.toml", 2, 3, 2, 8, "/value"),
        related_locations=(RepositoryRelatedLocation(SourceLocation("other.toml", 4, 2), "declared here"),),
        fingerprint="a" * 64,
    )
    report = FindingsReport(
        mode=Mode.RATCHET,
        repository_id=RepositoryId("fixture"),
        policy_id=PolicyId("sarj"),
        policy_version=1,
        scope_digest="0" * 64,
        summary={"diagnostics": 1, "errors": 1, "warnings": 0},
        diagnostics=(diagnostic,),
        ratchet=RatchetComparison((RatchetEntry(diagnostic.fingerprint, RatchetClassification.KNOWN, diagnostic),)),
    )

    def analyze_repository(_request: RepositoryAnalysisRequest) -> FindingsReport:
        return report

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- repository adapter interception is the behavior under test.
        repo_standards, "analyze_repository", analyze_repository
    )
    _adopt(tmp_path)
    baseline = tmp_path / ".repo-standards" / "baseline.json"
    baseline.write_text("{}\n", encoding="utf-8")
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)

    converted_report = repo_standards.analyze(tmp_path, staged=False)

    assert converted_report is not None
    converted = converted_report.diagnostics[0]

    assert converted.location.region is not None
    assert converted.location.region.start.line == 1
    assert converted.location.region.start.character == 2
    assert converted.location.region.end.character == 7
    assert converted.related[0].location.position is not None
    assert converted.related[0].location.position.line == 3
    assert converted.severity.value == expected_severity
    assert converted_report.baselined_count == baselined_count
    assert ("ratchet: known" in converted.notes) == bool(baselined_count)
    assert "manifest pointer: /value" in converted.notes


def test_ratchet_baseline_is_selected_from_the_exact_git_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[RepositoryAnalysisRequest] = []

    def analyze_repository(request: RepositoryAnalysisRequest) -> PassedReport:
        requests.append(request)
        return PassedReport(
            mode=request.mode,
            repository_id=RepositoryId("fixture"),
            policy_id=PolicyId("sarj"),
            policy_version=1,
            scope_digest="0" * 64,
            summary={"diagnostics": 0, "errors": 0, "warnings": 0},
            ratchet=RatchetComparison(()) if request.mode is Mode.RATCHET else None,
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- repository adapter interception is the behavior under test.
        repo_standards, "analyze_repository", analyze_repository
    )
    _adopt(tmp_path)
    baseline = tmp_path / ".repo-standards" / "baseline.json"
    baseline.write_text("{}\n", encoding="utf-8")
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)
    baseline.unlink()

    repo_standards.analyze(tmp_path, staged=False)
    subprocess.run(("git", "rm", str(baseline)), cwd=tmp_path, check=True, capture_output=True)
    baseline.write_text("{}\n", encoding="utf-8")
    repo_standards.analyze(tmp_path, staged=True)

    assert requests[0].mode is Mode.RATCHET
    assert requests[0].baseline_path == ".repo-standards/baseline.json"
    assert requests[1].mode is Mode.STRICT
    assert requests[1].baseline_path is None


@pytest.fixture
def repository_requests(monkeypatch: pytest.MonkeyPatch) -> list[RepositoryAnalysisRequest]:
    requests: list[RepositoryAnalysisRequest] = []

    def analyze_repository(request: RepositoryAnalysisRequest) -> PassedReport:
        requests.append(request)
        return PassedReport(
            mode=request.mode,
            repository_id=RepositoryId("fixture"),
            policy_id=PolicyId("sarj"),
            policy_version=1,
            scope_digest="0" * 64,
            summary={"diagnostics": 0, "errors": 0, "warnings": 0},
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the adapter request is the integration contract under test.
        repo_standards, "analyze_repository", analyze_repository
    )
    monkeypatch.delenv("SARJ_STANDARDS_BASE", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    return requests


def _enable_makefile_policy(repository: Path) -> None:
    manifest = _adopt(repository)
    manifest.write_text(
        'repository_id = "fixture"\ncomponents = []\nenabled_rules = ["repository/artifacts/makefile-growth"]\n',
        encoding="utf-8",
    )
    subprocess.run(("git", "init", "--quiet"), cwd=repository, check=True)
    _commit(repository)


@pytest.mark.parametrize("event", ["pull_request", "merge_group", "push", "new-branch-push"])
def test_committed_repository_comparison_forwards_exact_event_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_requests: list[RepositoryAnalysisRequest],
    event: str,
) -> None:
    _enable_makefile_policy(tmp_path)
    base = "0" * 40 if event == "new-branch-push" else "a" * 40
    payloads = {
        "pull_request": {"pull_request": {"base": {"sha": base}}},
        "merge_group": {"merge_group": {"base_sha": base}},
        "push": {"before": base},
        "new-branch-push": {"before": base},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payloads[event]), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push" if event == "new-branch-push" else event)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    repo_standards.analyze(tmp_path, staged=False)

    assert repository_requests[0].base_revision == base
    assert repository_requests[0].as_of == datetime.now(UTC).date()


def test_committed_repository_comparison_prefers_explicit_base_and_ignores_worktree_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_requests: list[RepositoryAnalysisRequest],
) -> None:
    _enable_makefile_policy(tmp_path)
    monkeypatch.setenv("SARJ_STANDARDS_BASE", "b" * 64)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "missing-event.json"))
    (tmp_path / ".repo-standards" / "repository.toml").write_text("invalid TOML\n", encoding="utf-8")

    repo_standards.analyze(tmp_path, staged=False)

    assert repository_requests[0].base_revision == "b" * 64


def test_staged_repository_comparison_ignores_ci_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_requests: list[RepositoryAnalysisRequest],
) -> None:
    _enable_makefile_policy(tmp_path)
    monkeypatch.setenv("SARJ_STANDARDS_BASE", "main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    repo_standards.analyze(tmp_path, staged=True)

    assert repository_requests[0].base_revision is None
    assert repository_requests[0].as_of == datetime.now(UTC).date()


def test_disabled_repository_comparison_does_not_parse_ci_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_requests: list[RepositoryAnalysisRequest],
) -> None:
    _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)
    monkeypatch.setenv("SARJ_STANDARDS_BASE", "main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    repo_standards.analyze(tmp_path, staged=False)

    assert repository_requests[0].base_revision is None


@pytest.mark.parametrize("input_kind", ["short-ref", "missing-event", "missing-base", "duplicate-key", "large-event"])
def test_invalid_active_repository_comparison_is_an_execution_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    input_kind: str,
) -> None:
    _enable_makefile_policy(tmp_path)
    monkeypatch.delenv("SARJ_STANDARDS_BASE", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    event_path = tmp_path / "event.json"
    payload = '{"before":"' + "a" * 40 + '"}'
    if input_kind == "short-ref":
        monkeypatch.setenv("SARJ_STANDARDS_BASE", "main")
    elif input_kind == "missing-base":
        payload = "{}"
    elif input_kind == "duplicate-key":
        payload = '{"before":"' + "a" * 40 + '","before":"' + "b" * 40 + '"}'
    elif input_kind == "large-event":
        payload = " " * (1024 * 1024 + 1)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    if input_kind != "missing-event":
        event_path.write_text(payload, encoding="utf-8")

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].source == "repo-standards"
    assert report.issues[0].kind == "integration-failure"


def test_corrupt_symbolic_head_cannot_skip_committed_repository_analysis(tmp_path: Path) -> None:
    _adopt(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    branch = subprocess.run(
        ("git", "symbolic-ref", "HEAD"), cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    reference = tmp_path / ".git" / branch
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text("f" * 40 + "\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].source == "repo-standards"


def test_ci_base_detects_growth_from_an_earlier_pr_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_makefile_policy(tmp_path)
    makefile = tmp_path / "Makefile"
    makefile.write_text("check:\n\tuv run pytest\n", encoding="utf-8")
    _commit(tmp_path)
    base = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    makefile.write_text("check:\n\tuv run pytest\n\n", encoding="utf-8")
    _commit(tmp_path)
    (tmp_path / "README.md").write_text("Fixture\n", encoding="utf-8")
    _commit(tmp_path)
    monkeypatch.delenv("SARJ_STANDARDS_BASE", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)

    local = api.Standards(tmp_path).analyze(())
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    compared = api.Standards(tmp_path).analyze(())

    assert local.exit_code == 0
    assert local.diagnostics == ()
    assert compared.exit_code == int(_makefile_severity() == "error")
    assert len(compared.diagnostics) == 1
    assert compared.diagnostics[0].rule_id == "repository/artifacts/makefile-growth"
    assert compared.diagnostics[0].severity.value == _makefile_severity()
    assert any(note.startswith(f"Git comparison: explicit; base {base}/") for note in compared.diagnostics[0].notes)
    assert compared.tools[-1].baselined_count == 0


@pytest.mark.parametrize("staged", [False, True])
def test_selected_adoption_cannot_be_hidden_by_unstaged_marker_deletions(tmp_path: Path, staged: bool) -> None:
    _enable_makefile_policy(tmp_path)
    (tmp_path / "Makefile").write_text("check:\n\tuv run pytest\n", encoding="utf-8")
    if staged:
        subprocess.run(("git", "add", "Makefile"), cwd=tmp_path, check=True)
    else:
        _commit(tmp_path)
    (tmp_path / ".repo-standards" / "repository.toml").unlink()
    (tmp_path / ".sarj-standards.toml").unlink()

    report = api.Standards(tmp_path).analyze((), staged=staged)

    assert report.exit_code == int(_makefile_severity() == "error")
    assert [item.rule_id for item in report.diagnostics] == ["repository/artifacts/makefile-growth"]


@pytest.mark.parametrize("staged", [False, True])
def test_untracked_adoption_markers_do_not_enable_selected_repository_policy(tmp_path: Path, staged: bool) -> None:
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("Fixture\n", encoding="utf-8")
    _commit(tmp_path)
    _adopt(tmp_path)
    (tmp_path / ".repo-standards" / "repository.toml").write_text("invalid TOML\n", encoding="utf-8")

    assert repo_standards.analyze(tmp_path, staged=staged) is None


@pytest.mark.parametrize("staged", [False, True])
def test_selected_adoption_reports_missing_manifest_when_worktree_marker_is_deleted(
    tmp_path: Path, staged: bool
) -> None:
    _enable_makefile_policy(tmp_path)
    subprocess.run(("git", "rm", ".repo-standards/repository.toml"), cwd=tmp_path, check=True, capture_output=True)
    if not staged:
        _commit(tmp_path)
    (tmp_path / ".sarj-standards.toml").unlink()

    report = api.Standards(tmp_path).analyze((), staged=staged)

    assert report.exit_code == 2
    assert report.issues[0].source == "repo-standards"
    assert report.issues[0].kind == "analysis.manifest-absent"
