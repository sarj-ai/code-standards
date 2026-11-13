from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from sarj_standards.libs.release.ci_artifacts import (
    ArtifactLookup,
    AwaitingArtifact,
    FreshValidationRequired,
    RepositoryId,
    VerifiedArtifact,
    extract_verified_archive,
    find_tested_artifact,
    main,
    reuse_ci_artifact,
)
from sarj_standards.libs.release.process import ProcessResult


SHA = "a" * 40
REPOSITORY = RepositoryId(3)


def _lookup(
    root: Path,
    *,
    event: str = "push",
    repository: str = "owner/repo",
    sha: str = SHA,
    job_status: str = "completed",
    conclusion: str = "success",
    digest: str = "sha256:" + "b" * 64,
    artifact_sha: str = SHA,
    artifact_run: int = 1,
    expired: bool = False,
    run_conclusion: str | None = None,
    job_name: str = "standards wheel and integration",
    run_attempt: int = 1,
    artifact_name: str = "tested-standards-1",
    current_attempt: int | None = None,
    repository_id: RepositoryId = REPOSITORY,
    total_count: int = 1,
) -> ArtifactLookup:
    run = {
        "id": 1,
        "head_sha": sha,
        "head_branch": "main",
        "event": event,
        "path": ".github/workflows/ci.yml",
        "conclusion": run_conclusion,
        "run_attempt": run_attempt,
        "head_repository": {"id": repository_id, "full_name": repository},
    }
    responses = [
        {
            "total_count": total_count,
            "workflow_runs": [run],
        },
        {
            "total_count": 1,
            "jobs": [{"name": job_name, "status": job_status, "conclusion": conclusion}],
        },
        {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 2,
                    "name": artifact_name,
                    "expired": expired,
                    "digest": digest,
                    "workflow_run": {
                        "id": artifact_run,
                        "head_sha": artifact_sha,
                        "head_branch": "main",
                        "repository_id": 3,
                        "head_repository_id": 3,
                    },
                }
            ],
        },
        {**run, "run_attempt": run_attempt if current_attempt is None else current_attempt},
    ]

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == root
        assert capture_output
        assert argv[:4] == ("gh", "api", "--method", "GET")
        if "/jobs?" in argv[-1]:
            assert f"/runs/1/attempts/{run_attempt}/jobs?" in argv[-1]
        return ProcessResult(0, json.dumps(responses.pop(0)))

    return find_tested_artifact(root, "owner/repo", SHA, runner=runner)


def test_successful_exact_main_job_reuses_only_its_artifact(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path)
    assert isinstance(lookup, VerifiedArtifact)
    assert lookup.source == SHA
    assert lookup.run.run_id == 1
    assert lookup.run.attempt == 1
    assert lookup.run.repository_id == 3
    assert lookup.artifact.artifact_id == 2


@pytest.mark.parametrize(
    ("event", "repository", "sha"),
    [("pull_request", "owner/repo", SHA), ("push", "fork/repo", SHA), ("push", "owner/repo", "c" * 40)],
)
def test_other_runs_cannot_supply_publishable_artifacts(tmp_path: Path, event: str, repository: str, sha: str) -> None:
    lookup = _lookup(tmp_path, event=event, repository=repository, sha=sha)
    assert isinstance(lookup, AwaitingArtifact)


def test_pending_job_cannot_supply_an_artifact(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, job_status="in_progress")
    assert isinstance(lookup, AwaitingArtifact)


def test_skipped_job_requires_fresh_full_validation(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, conclusion="skipped")
    assert isinstance(lookup, FreshValidationRequired)


def test_failed_job_aborts_reuse_instead_of_bypassing_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="concluded failure"):
        _lookup(tmp_path, conclusion="failure")


@pytest.mark.parametrize(
    ("digest", "artifact_sha", "artifact_run"),
    [("", SHA, 1), ("sha256:" + "b" * 64, "c" * 40, 1), ("sha256:" + "b" * 64, SHA, 8)],
)
def test_artifact_metadata_is_bound_to_its_tested_run(
    tmp_path: Path, digest: str, artifact_sha: str, artifact_run: int
) -> None:
    with pytest.raises(ValueError, match="provenance or digest"):
        _lookup(tmp_path, digest=digest, artifact_sha=artifact_sha, artifact_run=artifact_run)


def test_expired_artifact_uses_full_fallback(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, expired=True)
    assert isinstance(lookup, FreshValidationRequired)


def test_completed_partial_rerun_with_missing_job_uses_full_fallback(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, run_conclusion="success", job_name="codeql")
    assert isinstance(lookup, FreshValidationRequired)


def test_partial_rerun_terminal_job_avoids_outer_finalization_wait(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, job_name="CI complete")
    assert isinstance(lookup, FreshValidationRequired)


def test_rerun_artifact_is_immutable_and_bound_to_its_attempt(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, run_attempt=2, artifact_name="tested-standards-2")
    assert isinstance(lookup, VerifiedArtifact)
    assert lookup.run.attempt == 2
    old_attempt = _lookup(tmp_path, run_attempt=2)
    assert isinstance(old_attempt, FreshValidationRequired)


def test_rerun_during_metadata_validation_cannot_qualify_old_artifact(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CI identity changed"):
        _lookup(tmp_path, current_attempt=2)


@pytest.mark.parametrize("value", [True, False, 0, -1])
def test_provider_repository_identity_must_be_a_positive_exact_integer(tmp_path: Path, value: int) -> None:
    with pytest.raises(ValueError, match=r"repository_id|head_repository|valid integer"):
        _lookup(tmp_path, repository_id=RepositoryId(value))


@pytest.mark.parametrize("count", [True, False, 0, 2])
def test_workflow_collection_count_must_be_exact_and_complete(tmp_path: Path, count: int) -> None:
    with pytest.raises(ValueError, match=r"total_count|incomplete CI workflow response"):
        _lookup(tmp_path, total_count=count)


@pytest.mark.parametrize("attempt", [True, False, 0, -1])
def test_provider_attempt_must_be_a_positive_exact_integer(tmp_path: Path, attempt: int) -> None:
    with pytest.raises(ValueError, match="run_attempt"):
        _lookup(tmp_path, run_attempt=attempt)


@dataclass(frozen=True)
class _Archive:
    path: Path
    digest: str


def _archive(root: Path, *, sha: str = SHA, path: str = "code_standards-1.0.0.whl") -> _Archive:
    archive = root / "artifact.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("SOURCE_COMMIT", sha + "\n")
        bundle.writestr(path, b"tested wheel")
    return _Archive(archive, "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest())


def test_zip_digest_is_verified_before_extraction(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    destination = tmp_path / "dist"
    extract_verified_archive(archive.path, destination, digest=archive.digest, sha=SHA)
    assert (destination / "code_standards-1.0.0.whl").read_bytes() == b"tested wheel"
    with pytest.raises(ValueError, match="archive digest mismatch"):
        extract_verified_archive(archive.path, tmp_path / "unverified", digest="sha256:" + "0" * 64, sha=SHA)
    assert not (tmp_path / "unverified").exists()


@pytest.mark.parametrize("path", ["../escape.whl", "/absolute.whl", "deps\\escape.whl", "execute.py"])
def test_archive_cannot_write_outside_distribution_or_ship_code(tmp_path: Path, path: str) -> None:
    archive = _archive(tmp_path, path=path)
    with pytest.raises(ValueError, match=r"unsafe|unexpected"):
        extract_verified_archive(archive.path, tmp_path / "dist", digest=archive.digest, sha=SHA)


def test_archive_commit_must_match_requested_revision(tmp_path: Path) -> None:
    archive = _archive(tmp_path, sha="c" * 40)
    with pytest.raises(ValueError, match="source commit mismatch"):
        extract_verified_archive(archive.path, tmp_path / "dist", digest=archive.digest, sha=SHA)


@pytest.mark.parametrize(("rerun", "existing"), [(False, False), (True, False), (False, True)])
def test_download_is_staged_until_its_attempt_is_revalidated(tmp_path: Path, rerun: bool, existing: bool) -> None:
    archive = _archive(tmp_path)
    initial = _lookup(tmp_path, digest=archive.digest)
    assert isinstance(initial, VerifiedArtifact)
    run = {
        "id": 1,
        "run_attempt": 1,
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "path": ".github/workflows/ci.yml",
        "conclusion": "success",
        "head_repository": {"id": 3, "full_name": "owner/repo"},
    }
    current_attempt = 1
    current_reads: list[int] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path
        assert capture_output
        endpoint = argv[-1]
        if "/workflows/ci.yml/runs?" in endpoint:
            document = {"total_count": 1, "workflow_runs": [run]}
        elif "/attempts/1/jobs?" in endpoint:
            document = {
                "total_count": 1,
                "jobs": [{"name": "standards wheel and integration", "status": "completed", "conclusion": "success"}],
            }
        elif "/runs/1/artifacts?" in endpoint:
            artifact = initial.artifact
            document = {
                "total_count": 1,
                "artifacts": [
                    {
                        "id": artifact.artifact_id,
                        "name": artifact.name,
                        "expired": artifact.expired,
                        "digest": artifact.digest,
                        "workflow_run": {
                            "id": artifact.workflow_run.run_id,
                            "head_sha": artifact.workflow_run.head_sha,
                            "head_branch": artifact.workflow_run.head_branch,
                            "repository_id": artifact.workflow_run.repository_id,
                            "head_repository_id": artifact.workflow_run.head_repository_id,
                        },
                    }
                ],
            }
        else:
            assert endpoint == "repos/owner/repo/actions/runs/1"
            current_reads.append(current_attempt)
            document = {**run, "run_attempt": current_attempt}
        return ProcessResult(0, json.dumps(document))

    def download(argv: tuple[str, ...], *, cwd: Path, destination: Path) -> None:
        nonlocal current_attempt
        assert cwd == tmp_path
        assert argv[-1] == "repos/owner/repo/actions/artifacts/2/zip"
        destination.write_bytes(archive.path.read_bytes())
        if rerun:
            current_attempt = 2

    destination = tmp_path / "dist"
    if existing:
        destination.mkdir()
        (destination / "unrelated.txt").write_bytes(b"preserve\n")
    if rerun:
        with pytest.raises(ValueError, match="CI identity changed"):
            reuse_ci_artifact(tmp_path, "owner/repo", SHA, destination, runner=runner, file_runner=download)
        assert not destination.exists()
    elif existing:
        with pytest.raises(FileExistsError):
            reuse_ci_artifact(tmp_path, "owner/repo", SHA, destination, runner=runner, file_runner=download)
        assert list(destination.iterdir()) == [destination / "unrelated.txt"]
        assert (destination / "unrelated.txt").read_bytes() == b"preserve\n"
    else:
        assert reuse_ci_artifact(tmp_path, "owner/repo", SHA, destination, runner=runner, file_runner=download)
        assert (destination / "code_standards-1.0.0.whl").read_bytes() == b"tested wheel"
    assert current_reads == [1, 2 if rerun else 1]


def test_reuse_cli_preserves_failure_exit_code(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--repository",
                "owner/repo",
                "--commit",
                "invalid",
                "--destination",
                str(tmp_path / "dist"),
                "--github-output",
                str(tmp_path / "output"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "output").exists()
