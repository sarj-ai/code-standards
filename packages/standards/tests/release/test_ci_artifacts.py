from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from sarj_standards.libs.release.ci_artifacts import (
    ArtifactLookup,
    extract_verified_archive,
    find_tested_artifact,
    main,
)
from sarj_standards.libs.release.process import ProcessResult


SHA = "a" * 40


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
) -> ArtifactLookup:
    responses = [
        {
            "workflow_runs": [
                {
                    "id": 1,
                    "head_sha": sha,
                    "head_branch": "main",
                    "event": event,
                    "path": ".github/workflows/ci.yml",
                    "conclusion": None,
                    "head_repository": {"full_name": repository},
                }
            ]
        },
        {
            "total_count": 1,
            "jobs": [{"name": "standards wheel and integration", "status": job_status, "conclusion": conclusion}],
        },
        {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 2,
                    "name": "tested-standards",
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
    ]

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == root
        assert capture_output
        assert argv[:4] == ("gh", "api", "--method", "GET")
        return ProcessResult(0, json.dumps(responses.pop(0)))

    return find_tested_artifact(root, "owner/repo", SHA, runner=runner)


def test_successful_exact_main_job_reuses_only_its_artifact(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path)
    assert not lookup.waiting
    assert lookup.artifact is not None


@pytest.mark.parametrize(
    ("event", "repository", "sha"),
    [("pull_request", "owner/repo", SHA), ("push", "fork/repo", SHA), ("push", "owner/repo", "c" * 40)],
)
def test_other_runs_cannot_supply_publishable_artifacts(tmp_path: Path, event: str, repository: str, sha: str) -> None:
    lookup = _lookup(tmp_path, event=event, repository=repository, sha=sha)
    assert lookup.waiting
    assert lookup.artifact is None


def test_pending_job_cannot_supply_an_artifact(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, job_status="in_progress")
    assert lookup.waiting is True
    assert lookup.artifact is None


def test_skipped_job_requires_fresh_full_validation(tmp_path: Path) -> None:
    lookup = _lookup(tmp_path, conclusion="skipped")
    assert lookup.waiting is False
    assert lookup.artifact is None


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
    assert lookup.waiting is False
    assert lookup.artifact is None


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
