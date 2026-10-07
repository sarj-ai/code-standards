from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

import sarj_standards
from sarj_standards.libs.release.ci_artifacts import WorkflowRunId
from sarj_standards.libs.release.process import ProcessFailureError, ProcessResult, run_process
from sarj_standards.libs.release.reviewed_analysis import (
    AnalysisProof,
    CheckKind,
    find_reviewed_run,
    reuse_reviewed_analysis,
    verify_analysis_archive,
)


SHA = "a" * 40
HEAD = "b" * 40
SOURCE = "c" * 40
TREE = "d" * 40
BASE = "e" * 40
NOW = datetime.now(UTC)


def _pulls(*, head_id: int = 3, merged: bool = True, merge: str = SHA, ref: str = "main") -> str:
    return json.dumps(
        [
            {
                "number": 4,
                "merge_commit_sha": merge,
                "merged_at": NOW.isoformat() if merged else None,
                "head": {"sha": HEAD, "ref": "topic", "repo": {"id": head_id, "full_name": "owner/repo"}},
                "base": {"sha": BASE, "ref": ref, "repo": {"id": 3, "full_name": "owner/repo"}},
            }
        ]
    )


def _run(
    *,
    identifier: int = 5,
    conclusion: str | None = "success",
    status: str = "completed",
    event: str = "pull_request",
    path: str = ".github/workflows/ci.yml",
    head: str = HEAD,
    attempt: int = 1,
    updated: datetime = NOW,
    owner: str = "owner/repo",
    wrapper: bool = True,
) -> str:
    value = {
        "id": identifier,
        "run_attempt": attempt,
        "head_sha": head,
        "head_repository": {"id": 3, "full_name": owner},
        "event": event,
        "path": path,
        "status": status,
        "conclusion": conclusion,
        "updated_at": updated.isoformat(),
    }
    return json.dumps({"total_count": 1, "workflow_runs": [value]} if wrapper else value)


@dataclass
class _Gateway:
    root: Path
    responses: list[str]

    def __call__(self, argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == self.root
        assert capture_output
        if argv[0] == "git":
            return ProcessResult(0, BASE if argv[-1].endswith("^") else TREE)
        assert argv[:4] == ("gh", "api", "--method", "GET")
        return ProcessResult(0, self.responses.pop(0))


def test_recent_successful_owned_merged_pr_is_eligible(tmp_path: Path) -> None:
    gateway = _Gateway(tmp_path, [_pulls(), _run()])
    run = find_reviewed_run(tmp_path, "owner/repo", SHA, runner=gateway, now=NOW)
    assert run is not None
    assert run.run_id == WorkflowRunId(5)
    assert not gateway.responses


@pytest.mark.parametrize(
    "pulls",
    [_pulls(head_id=7), _pulls(merged=False), _pulls(merge=SOURCE), _pulls(ref="topic"), "[]"],
    ids=["fork", "unmerged", "other-merge", "other-base", "missing"],
)
def test_forks_unmerged_or_unrelated_pulls_require_fresh_checks(tmp_path: Path, pulls: str) -> None:
    assert find_reviewed_run(tmp_path, "owner/repo", SHA, runner=_Gateway(tmp_path, [pulls]), now=NOW) is None


@pytest.mark.parametrize(
    "run",
    [
        _run(conclusion="failure"),
        _run(conclusion=None, status="in_progress"),
        _run(event="push"),
        _run(path=".github/workflows/other.yml"),
        _run(head=SOURCE),
        _run(owner="fork/repo"),
        _run(updated=NOW - timedelta(hours=25)),
        _run(updated=NOW + timedelta(hours=1)),
    ],
    ids=["failure", "pending", "push", "other-workflow", "other-head", "fork", "expired", "future"],
)
def test_failed_pending_other_or_old_runs_require_fresh_checks(tmp_path: Path, run: str) -> None:
    gateway = _Gateway(tmp_path, [_pulls(), run])
    assert find_reviewed_run(tmp_path, "owner/repo", SHA, runner=gateway, now=NOW) is None


def test_latest_failed_ci_cannot_inherit_an_older_success(tmp_path: Path) -> None:
    runs = (
        '{"total_count":2,"workflow_runs":['
        + _run(wrapper=False)
        + ","
        + _run(identifier=6, conclusion="failure", wrapper=False)
        + "]}"
    )
    assert find_reviewed_run(tmp_path, "owner/repo", SHA, runner=_Gateway(tmp_path, [_pulls(), runs]), now=NOW) is None


@dataclass(frozen=True)
class _Archive:
    path: Path
    digest: str


def _archive(
    root: Path,
    *,
    kind: CheckKind = CheckKind.STATIC,
    tree: str = TREE,
    base: str = BASE,
    attempt: int = 1,
    extra: str | None = None,
    sarif: bool = True,
    wheel_source: str = SOURCE,
) -> _Archive:
    proof = AnalysisProof(
        schema_version=1,
        repository="owner/repo",
        source_commit=SOURCE,
        comparison_base=base,
        tree=tree,
        run_id=WorkflowRunId(5),
        run_attempt=attempt,
        kind=kind,
    )
    archive = root / "analysis.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("proof.json", proof.model_dump_json())
        if sarif and kind in {CheckKind.PYTHON, CheckKind.JAVASCRIPT}:
            bundle.writestr("results.sarif", '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"CodeQL"}}}]}')
        if kind == CheckKind.WHEELS:
            bundle.writestr("SOURCE_COMMIT", wheel_source)
            bundle.writestr("SOURCE_TREE", tree)
            bundle.writestr("code_standards-1.0.0-py3-none-any.whl", b"tested wheel")
            bundle.writestr("deps/", b"")
            bundle.writestr("deps/sarj_python_lint-1.0.0-py3-none-any.whl", b"tested dependency")
        if extra:
            bundle.writestr(extra, b"unexpected member")
    return _Archive(archive, "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest())


def _verify(archive: _Archive, destination: Path, *, kind: CheckKind = CheckKind.STATIC) -> None:
    verify_analysis_archive(
        archive.path,
        destination,
        digest=archive.digest,
        repository="owner/repo",
        tree=TREE,
        base=BASE,
        run_id=WorkflowRunId(5),
        run_attempt=1,
        kind=kind,
    )


@pytest.mark.parametrize("kind", list(CheckKind))
def test_verified_archives_preserve_exact_checked_payloads(tmp_path: Path, kind: CheckKind) -> None:
    archive = _archive(tmp_path, kind=kind)
    destination = tmp_path / "verified"
    _verify(archive, destination, kind=kind)
    assert (destination / "proof.json").is_file()
    if kind == CheckKind.WHEELS:
        assert (destination / "code_standards-1.0.0-py3-none-any.whl").read_bytes() == b"tested wheel"
        assert (destination / "deps/sarj_python_lint-1.0.0-py3-none-any.whl").read_bytes() == b"tested dependency"


@pytest.mark.parametrize("field", ["tree", "base", "attempt"])
def test_tree_base_and_attempt_must_match_before_extraction(tmp_path: Path, field: str) -> None:
    archive = _archive(
        tmp_path,
        tree=SOURCE if field == "tree" else TREE,
        base=SOURCE if field == "base" else BASE,
        attempt=2 if field == "attempt" else 1,
    )
    destination = tmp_path / "unverified"
    with pytest.raises(ValueError, match="does not match"):
        _verify(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("extra", ["../escape.sarif", "/absolute.sarif", "deps\\escape.sarif", "execute.py"])
def test_archive_cannot_escape_or_ship_executable_code(tmp_path: Path, extra: str) -> None:
    archive = _archive(tmp_path, kind=CheckKind.PYTHON, extra=extra)
    with pytest.raises(ValueError, match="unsafe"):
        _verify(archive, tmp_path / "unverified", kind=CheckKind.PYTHON)


def test_archive_digest_is_verified_before_parsing(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    archive.path.write_bytes(archive.path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        _verify(archive, tmp_path / "unverified")
    assert not (tmp_path / "unverified").exists()


def test_codeql_proof_without_results_is_not_a_security_certificate(tmp_path: Path) -> None:
    archive = _archive(tmp_path, kind=CheckKind.PYTHON, sarif=False)
    with pytest.raises(ValueError, match="requires its SARIF"):
        _verify(archive, tmp_path / "unverified", kind=CheckKind.PYTHON)


def test_wheel_source_marker_must_match_its_reviewed_commit(tmp_path: Path) -> None:
    archive = _archive(tmp_path, kind=CheckKind.WHEELS, wheel_source=HEAD)
    with pytest.raises(ValueError, match="source commit"):
        _verify(archive, tmp_path / "unverified", kind=CheckKind.WHEELS)


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch", "schedule", "uncertified-base"])
def test_audits_and_uncertified_baselines_never_reuse_checks(tmp_path: Path, event: str) -> None:
    report = reuse_reviewed_analysis(
        tmp_path, "owner/repo", SHA, tmp_path / "out", base=BASE, event=event, runner=_Gateway(tmp_path, [])
    )
    assert not report.checks
    assert report.source_run is None


def test_api_failure_falls_back_to_fresh_checks(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path
        assert capture_output
        if argv[0] == "git":
            return ProcessResult(0, BASE)
        raise ProcessFailureError(argv, 1)

    report = reuse_reviewed_analysis(
        tmp_path, "owner/repo", SHA, tmp_path / "out", base=BASE, event="push", runner=runner
    )
    assert not report.checks
    assert "unavailable" in report.reason


def test_successful_ci_without_current_attempt_proofs_uses_fresh_checks(tmp_path: Path) -> None:
    gateway = _Gateway(
        tmp_path,
        [_pulls(), _run(), '{"total_count":0,"jobs":[]}', '{"total_count":0,"artifacts":[]}', _run(wrapper=False)],
    )
    report = reuse_reviewed_analysis(
        tmp_path, "owner/repo", SHA, tmp_path / "out", base=BASE, event="push", runner=gateway
    )
    assert not report.checks
    assert report.source_run is None


def test_verified_ci_proof_controls_reuse_and_rerun_races_fail_closed(tmp_path: Path) -> None:
    archive = _archive(tmp_path, kind=CheckKind.CI)
    artifacts = json.dumps(
        {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 7,
                    "name": "reviewed-ci-1",
                    "expired": False,
                    "digest": archive.digest,
                    "workflow_run": {
                        "id": 5,
                        "head_sha": HEAD,
                        "head_branch": "topic",
                        "repository_id": 3,
                        "head_repository_id": 3,
                    },
                }
            ],
        }
    )
    jobs = '{"total_count":1,"jobs":[{"name":"CI complete","status":"completed","conclusion":"success"}]}'

    def download(argv: tuple[str, ...], *, cwd: Path, destination: Path) -> None:
        assert cwd == tmp_path
        assert argv == ("gh", "api", "repos/owner/repo/actions/artifacts/7/zip")
        destination.write_bytes(archive.path.read_bytes())

    for attempt, expected in ((1, (CheckKind.CI,)), (2, ())):
        gateway = _Gateway(tmp_path, [_pulls(), _run(), jobs, artifacts, _run(attempt=attempt, wrapper=False)])
        report = reuse_reviewed_analysis(
            tmp_path,
            "owner/repo",
            SHA,
            tmp_path / f"out-{attempt}",
            base=BASE,
            event="push",
            runner=gateway,
            downloader=download,
        )
        assert report.checks == expected


def test_metadata_and_release_helpers_do_not_load_the_sdk(tmp_path: Path) -> None:
    script = (
        "import sys, sarj_standards; "
        "from sarj_standards import __version__; "
        "import sarj_standards.libs.release.reviewed_analysis; "
        "assert 'sarj_standards.api' not in sys.modules; "
        "assert 'sarj_standards.libs.linting.runner' not in sys.modules"
    )
    result = run_process((sys.executable, "-c", script), cwd=tmp_path, capture_output=True)
    assert result.returncode == 0


@pytest.mark.parametrize("missing", ["unavailable_export", "_private_missing"])
def test_sdk_exports_and_star_import_contract_remain_available(tmp_path: Path, missing: str) -> None:
    assert "Standards" in dir(sarj_standards)
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(sarj_standards, missing)
    script = "from sarj_standards import *; from sarj_standards import api; assert Standards is api.Standards; assert to_json is api.to_json"
    assert run_process((sys.executable, "-c", script), cwd=tmp_path, capture_output=True).returncode == 0
