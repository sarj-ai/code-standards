from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

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

from sarj_standards import api
from sarj_standards.libs.linting import repo_standards


if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from repo_standards.repository import RepositoryAnalysisRequest


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
        'schema_version = 6\nrepository_id = "fixture"\ncomponents = []\n',
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
        'schema_version = 6\nrepository_id = "unstaged"\ncomponents = []\n',
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

    def fail(_root: Path, *, staged: bool) -> None:
        del staged
        message = "incompatible dependency contract"
        raise TypeError(message)

    monkeypatch.setattr(repo_standards, "analyze", fail)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    _commit(tmp_path)

    report = api.Standards(tmp_path).analyze(())

    assert report.exit_code == 2
    assert report.issues[0].kind == "integration-failure"


def test_repository_diagnostic_preserves_ranges_and_related_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = RepositoryDiagnostic(
        rule_id=RuleId("repository.test"),
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

    monkeypatch.setattr(repo_standards, "analyze_repository", analyze_repository)
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
    assert converted.severity.value == "info"
    assert converted_report.baselined_count == 1
    assert "ratchet: known" in converted.notes
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

    monkeypatch.setattr(repo_standards, "analyze_repository", analyze_repository)
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
