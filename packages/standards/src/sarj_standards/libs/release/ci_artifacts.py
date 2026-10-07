from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import time
from typing import TYPE_CHECKING, Annotated, ClassVar, NewType
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field
import typer

from sarj_standards.libs.release.process import ProcessFailureError, ProcessRunner, run_process, run_process_to_file


if TYPE_CHECKING:
    from collections.abc import Sequence


WorkflowRunId = NewType("WorkflowRunId", int)
RepositoryId = NewType("RepositoryId", int)
ArtifactId = NewType("ArtifactId", int)


_ARTIFACT_NAME = "tested-standards"
_TEST_JOB = "standards wheel and integration"
_MAX_BYTES = 100_000_000


class _Repository(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    full_name: str


class _Run(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    run_id: WorkflowRunId = Field(alias="id", gt=0)
    run_attempt: int = Field(default=1, ge=1)
    head_sha: str
    head_branch: str
    event: str
    path: str
    conclusion: str | None
    head_repository: _Repository


class _Runs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    workflow_runs: tuple[_Run, ...]


class _Job(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    name: str
    status: str
    conclusion: str | None


class _Jobs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    total_count: int
    jobs: tuple[_Job, ...]


class _ArtifactRun(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    run_id: WorkflowRunId = Field(alias="id", gt=0)
    head_sha: str
    head_branch: str
    repository_id: RepositoryId
    head_repository_id: RepositoryId


class TestedArtifact(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    artifact_id: ArtifactId = Field(alias="id", gt=0)
    name: str
    expired: bool
    digest: str
    workflow_run: _ArtifactRun


class _Artifacts(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    total_count: int
    artifacts: tuple[TestedArtifact, ...]


class ArtifactLookup(BaseModel):
    waiting: bool
    artifact: TestedArtifact | None = None


def find_tested_artifact(
    root: Path, repository: str, sha: str, *, runner: ProcessRunner = run_process
) -> ArtifactLookup:
    if (
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
        or re.fullmatch(r"[0-9a-f]{40}", sha) is None
    ):
        msg = "artifact reuse requires a repository and full commit SHA"
        raise ValueError(msg)
    runs = _Runs.model_validate_json(
        _api(root, f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={sha}&event=push&per_page=100", runner)
    )
    candidates = [run for run in runs.workflow_runs if _is_exact_run(run, repository, sha)]
    if not candidates:
        return ArtifactLookup(waiting=True)
    run = max(candidates, key=lambda candidate: candidate.run_id)
    if run.conclusion not in {None, "success"}:
        msg = f"exact-revision CI concluded {run.conclusion}"
        raise ValueError(msg)
    status = _standards_job_status(root, repository, run.run_id, runner)
    if status == "pending":
        # A successful partial rerun can omit previously completed jobs.
        # Fall back instead of waiting for a job that will never appear.
        return ArtifactLookup(waiting=run.conclusion != "success")
    if status == "skipped":
        return ArtifactLookup(waiting=False)
    return ArtifactLookup(
        waiting=False,
        artifact=_artifact_for_run(
            root, repository, sha, run.run_id, runner, artifact_name=f"{_ARTIFACT_NAME}-{run.run_attempt}"
        ),
    )


def _is_exact_run(run: _Run, repository: str, sha: str) -> bool:
    return (
        run.head_sha == sha
        and run.head_branch == "main"
        and run.event == "push"
        and run.head_repository.full_name == repository
        and run.path == ".github/workflows/ci.yml"
    )


def _standards_job_status(root: Path, repository: str, run_id: WorkflowRunId, runner: ProcessRunner) -> str:
    jobs = _Jobs.model_validate_json(_api(root, f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100", runner))
    if jobs.total_count != len(jobs.jobs):
        msg = "incomplete CI job response"
        raise ValueError(msg)
    matches = [job for job in jobs.jobs if job.name == _TEST_JOB]
    if not matches:
        if any(
            job.name == "CI complete" and job.status == "completed" and job.conclusion == "success" for job in jobs.jobs
        ):
            return "skipped"
        return "pending"
    if len(matches) != 1:
        msg = "ambiguous Standards test job"
        raise ValueError(msg)
    job = matches[0]
    if job.status != "completed":
        return "pending"
    if job.conclusion == "skipped":
        return "skipped"
    if job.conclusion != "success":
        msg = f"Standards wheel tests concluded {job.conclusion}"
        raise ValueError(msg)
    return "success"


def _artifact_for_run(
    root: Path, repository: str, sha: str, run_id: WorkflowRunId, runner: ProcessRunner, *, artifact_name: str
) -> TestedArtifact | None:
    artifacts = _Artifacts.model_validate_json(
        _api(root, f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100", runner)
    )
    if artifacts.total_count != len(artifacts.artifacts):
        msg = "incomplete artifact response"
        raise ValueError(msg)
    matching = [artifact for artifact in artifacts.artifacts if artifact.name == artifact_name and not artifact.expired]
    if not matching:
        return None
    if len(matching) != 1:
        msg = "ambiguous tested Standards artifact"
        raise ValueError(msg)
    artifact = matching[0]
    identity = artifact.workflow_run
    if (
        identity.run_id != run_id
        or identity.head_sha != sha
        or identity.head_branch != "main"
        or identity.repository_id != identity.head_repository_id
        or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.digest) is None
    ):
        msg = "tested artifact provenance or digest does not match exact CI"
        raise ValueError(msg)
    return artifact


def _api(root: Path, endpoint: str, runner: ProcessRunner) -> str:
    return runner(("gh", "api", "--method", "GET", endpoint), cwd=root, capture_output=True).stdout


def extract_verified_archive(archive: Path, destination: Path, *, digest: str, sha: str) -> None:
    with archive.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        msg = "tested artifact archive digest mismatch"
        raise ValueError(msg)
    with ZipFile(archive) as bundle:
        members = bundle.infolist()
        if sum(member.file_size for member in members) > _MAX_BYTES:
            msg = "tested artifact archive is too large"
            raise ValueError(msg)
        paths = [PurePosixPath(member.filename) for member in members]
        if len(paths) != len(set(paths)) or any(
            path.is_absolute() or ".." in path.parts or "\\" in str(path) for path in paths
        ):
            msg = "tested artifact archive contains unsafe or duplicate paths"
            raise ValueError(msg)
        if bundle.read("SOURCE_COMMIT").decode("ascii").strip() != sha:
            msg = "tested artifact source commit mismatch"
            raise ValueError(msg)
        for member, path in zip(members, paths, strict=True):
            if member.is_dir():
                continue
            if path.suffix not in {".whl", ".gz"} and str(path) not in {
                "SHA256SUMS",
                "SOURCE_COMMIT",
                "SOURCE_TREE",
                "REVIEWED_SOURCE.json",
                "test-plan.json",
            }:
                msg = "unexpected file in tested artifact"
                raise ValueError(msg)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def reuse_ci_artifact(root: Path, repository: str, sha: str, destination: Path, *, timeout: int = 2700) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lookup = find_tested_artifact(root, repository, sha)
        artifact = lookup.artifact
        if artifact is not None:
            with TemporaryDirectory(prefix="sarj-tested-artifact-") as temporary:
                archive = Path(temporary) / "artifact.zip"
                run_process_to_file(
                    ("gh", "api", f"repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip"),
                    cwd=root,
                    destination=archive,
                )
                extract_verified_archive(archive, destination, digest=artifact.digest, sha=sha)
            sys.stdout.write(
                f"Reused tested artifact {artifact.artifact_id} from main CI {artifact.workflow_run.run_id} at {sha}\n"
            )
            return True
        if not lookup.waiting:
            sys.stdout.write("No reusable artifact for exact CI; building and testing afresh.\n")
            return False
        sys.stdout.write(f"Waiting for tested main artifact at {sha}\n")
        sys.stdout.flush()
        time.sleep(10)
    msg = "timed out waiting for exact-revision tested artifact"
    raise ValueError(msg)


def main(argv: Sequence[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
    exit_code = 0

    @app.command()
    def reuse(
        *,
        root: Annotated[Path, typer.Option("--root")],
        repository: Annotated[str, typer.Option("--repository")],
        commit: Annotated[str, typer.Option("--commit")],
        destination: Annotated[Path, typer.Option("--destination")],
        output: Annotated[Path, typer.Option("--github-output")],
    ) -> None:
        nonlocal exit_code
        try:
            reused = reuse_ci_artifact(root.resolve(), repository, commit, destination)
            with output.open("a") as stream:
                stream.write(f"reused={str(reused).lower()}\n")
        except (OSError, ValueError, ProcessFailureError) as exc:
            sys.stderr.write(f"error: {exc}\n")
            exit_code = 2

    app(args=None if argv is None else list(argv), prog_name="reuse-standards-artifact", standalone_mode=False)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
