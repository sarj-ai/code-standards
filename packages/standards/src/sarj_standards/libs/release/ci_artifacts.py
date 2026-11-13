from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import time
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, NewType, assert_never
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field
import typer

from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.release.process import (
    ProcessFailureError,
    ProcessFileRunner,
    ProcessRunner,
    run_process,
    run_process_to_file,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


WorkflowRunId = NewType("WorkflowRunId", int)
RepositoryId = NewType("RepositoryId", int)
ArtifactId = NewType("ArtifactId", int)
WorkflowRunAttempt = NewType("WorkflowRunAttempt", int)
SourceCommit = NewType("SourceCommit", str)


_ARTIFACT_NAME = "tested-standards"
_TEST_JOB = "standards wheel and integration"
_MAX_BYTES = 100_000_000
_MAX_FILES = 10_000


class _Repository(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    repository_id: RepositoryId = Field(alias="id", gt=0)
    full_name: str


class _Run(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    run_id: WorkflowRunId = Field(alias="id", gt=0)
    run_attempt: WorkflowRunAttempt = Field(ge=1)
    head_sha: str
    head_branch: str
    event: str
    path: str
    conclusion: str | None
    head_repository: _Repository


class _Runs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    total_count: int = Field(ge=0)
    workflow_runs: tuple[_Run, ...]


class _Job(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    name: str
    status: str
    conclusion: str | None


class _Jobs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    total_count: int = Field(ge=0)
    jobs: tuple[_Job, ...]


class _ArtifactRun(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    run_id: WorkflowRunId = Field(alias="id", gt=0)
    head_sha: str
    head_branch: str
    repository_id: RepositoryId = Field(gt=0)
    head_repository_id: RepositoryId = Field(gt=0)


class TestedArtifact(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    artifact_id: ArtifactId = Field(alias="id", gt=0)
    name: str
    expired: bool
    digest: str
    workflow_run: _ArtifactRun


class _Artifacts(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    total_count: int = Field(ge=0)
    artifacts: tuple[TestedArtifact, ...]


@dataclass(frozen=True, slots=True)
class AwaitingArtifact:
    kind: ClassVar[Literal["awaiting"]] = "awaiting"
    reason: str


@dataclass(frozen=True, slots=True)
class FreshValidationRequired:
    kind: ClassVar[Literal["fresh-validation-required"]] = "fresh-validation-required"
    reason: str


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: WorkflowRunId
    attempt: WorkflowRunAttempt
    repository_id: RepositoryId


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    kind: ClassVar[Literal["verified"]] = "verified"
    source: SourceCommit
    run: RunIdentity
    artifact: TestedArtifact


type ArtifactLookup = AwaitingArtifact | FreshValidationRequired | VerifiedArtifact


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
    if runs.total_count != len(runs.workflow_runs):
        msg = "incomplete CI workflow response"
        raise ValueError(msg)
    candidates = [run for run in runs.workflow_runs if _is_exact_run(run, repository, sha)]
    if not candidates:
        return AwaitingArtifact("waiting for exact main CI")
    run = max(candidates, key=lambda candidate: candidate.run_id)
    if run.conclusion not in {None, "success"}:
        msg = f"exact-revision CI concluded {run.conclusion}"
        raise ValueError(msg)
    identity = RunIdentity(run.run_id, run.run_attempt, run.head_repository.repository_id)
    status = _standards_job_status(root, repository, identity, runner)
    if status == "pending":
        # A successful partial rerun can omit previously completed jobs.
        # Fall back instead of waiting for a job that will never appear.
        return (
            FreshValidationRequired("successful partial rerun has no artifact job")
            if run.conclusion == "success"
            else AwaitingArtifact("waiting for the current-attempt artifact job")
        )
    if status == "skipped":
        return FreshValidationRequired("artifact job was not part of this qualification")
    artifact = _artifact_for_run(
        root, repository, sha, identity, runner, artifact_name=f"{_ARTIFACT_NAME}-{run.run_attempt}"
    )
    if artifact is None:
        return FreshValidationRequired("current-attempt artifact is missing or expired")
    verified = VerifiedArtifact(SourceCommit(sha), identity, artifact)
    _require_current_attempt(root, repository, verified, runner)
    return verified


def _is_exact_run(run: _Run, repository: str, sha: str) -> bool:
    return (
        run.head_sha == sha
        and run.head_branch == "main"
        and run.event == "push"
        and run.head_repository.full_name == repository
        and run.path == ".github/workflows/ci.yml"
    )


def _standards_job_status(
    root: Path, repository: str, run: RunIdentity, runner: ProcessRunner
) -> Literal["pending", "skipped", "success"]:
    jobs = _Jobs.model_validate_json(
        _api(root, f"repos/{repository}/actions/runs/{run.run_id}/attempts/{run.attempt}/jobs?per_page=100", runner)
    )
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
    root: Path, repository: str, sha: str, run: RunIdentity, runner: ProcessRunner, *, artifact_name: str
) -> TestedArtifact | None:
    artifacts = _Artifacts.model_validate_json(
        _api(root, f"repos/{repository}/actions/runs/{run.run_id}/artifacts?per_page=100", runner)
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
    actual = (
        identity.run_id,
        identity.head_sha,
        identity.head_branch,
        identity.repository_id,
        identity.head_repository_id,
    )
    expected = run.run_id, sha, "main", run.repository_id, run.repository_id
    if actual != expected or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.digest) is None:
        msg = "tested artifact provenance or digest does not match exact CI"
        raise ValueError(msg)
    return artifact


def _api(root: Path, endpoint: str, runner: ProcessRunner) -> str:
    document = runner(("gh", "api", "--method", "GET", endpoint), cwd=root, capture_output=True).stdout
    parse_unique_json(document)
    return document


def _require_current_attempt(root: Path, repository: str, verified: VerifiedArtifact, runner: ProcessRunner) -> None:
    current = _Run.model_validate_json(_api(root, f"repos/{repository}/actions/runs/{verified.run.run_id}", runner))
    if (
        not _is_exact_run(current, repository, verified.source)
        or current.run_id != verified.run.run_id
        or current.run_attempt != verified.run.attempt
        or current.head_repository.repository_id != verified.run.repository_id
        or current.conclusion not in {None, "success"}
    ):
        msg = "exact CI identity changed while verifying its artifact"
        raise ValueError(msg)


def extract_verified_archive(archive: Path, destination: Path, *, digest: str, sha: str) -> None:
    with archive.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        msg = "tested artifact archive digest mismatch"
        raise ValueError(msg)
    with ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > _MAX_FILES or sum(member.file_size for member in members) > _MAX_BYTES:
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


def reuse_ci_artifact(
    root: Path,
    repository: str,
    sha: str,
    destination: Path,
    *,
    timeout: int = 2700,
    poll_interval: float = 10,
    runner: ProcessRunner = run_process,
    file_runner: ProcessFileRunner = run_process_to_file,
) -> bool:
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
        msg = "artifact timeout must be finite and non-negative"
        raise ValueError(msg)
    if isinstance(poll_interval, bool) or not math.isfinite(poll_interval) or poll_interval <= 0:
        msg = "artifact poll interval must be finite and positive"
        raise ValueError(msg)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lookup = find_tested_artifact(root, repository, sha, runner=runner)
        if isinstance(lookup, VerifiedArtifact):
            artifact = lookup.artifact
            with TemporaryDirectory(prefix="sarj-tested-artifact-") as temporary:
                archive = Path(temporary) / "artifact.zip"
                file_runner(
                    ("gh", "api", f"repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip"),
                    cwd=root,
                    destination=archive,
                )
                staged = Path(temporary) / "verified"
                extract_verified_archive(archive, staged, digest=artifact.digest, sha=sha)
                _require_current_attempt(root, repository, lookup, runner)
                shutil.copytree(staged, destination)
            sys.stdout.write(
                f"Reused tested artifact {artifact.artifact_id} from main CI {artifact.workflow_run.run_id} at {sha}\n"
            )
            return True
        match lookup:
            case FreshValidationRequired():
                sys.stdout.write("No reusable artifact for exact CI; building and testing afresh.\n")
                return False
            case AwaitingArtifact():
                sys.stdout.write(f"Waiting for tested main artifact at {sha}\n")
                sys.stdout.flush()
                time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            case _:
                assert_never(lookup)
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
