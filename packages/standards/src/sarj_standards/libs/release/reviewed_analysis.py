from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, NewType
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, RootModel
import typer

from sarj_standards.libs.release.ci_artifacts import RepositoryId, TestedArtifact, WorkflowRunId
from sarj_standards.libs.release.process import (
    ProcessFailureError,
    ProcessFileRunner,
    ProcessRunner,
    run_process,
    run_process_to_file,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from zipfile import ZipInfo


PullNumber = NewType("PullNumber", int)
_SHA_PATTERN = r"[0-9a-f]{40}"
_MAX_BYTES = 25_000_000
_MAX_FILES = 32
_MAX_AGE = timedelta(hours=24)


class CheckKind(StrEnum):
    STATIC = "static"
    DOCS = "docs"
    PYTHON = "codeql-python"
    JAVASCRIPT = "codeql-javascript-typescript"
    WHEELS = "wheels"
    CI = "ci"


_JOB_NAMES: Final[dict[CheckKind, str]] = {
    CheckKind.STATIC: "standards static analysis",
    CheckKind.DOCS: "documentation build",
    CheckKind.PYTHON: "codeql (python)",
    CheckKind.JAVASCRIPT: "codeql (javascript-typescript)",
    CheckKind.WHEELS: "standards wheel and integration",
    CheckKind.CI: "CI complete",
}


class AnalysisProof(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    repository: str
    source_commit: str = Field(pattern=_SHA_PATTERN, min_length=40, max_length=40)
    comparison_base: str = Field(pattern=_SHA_PATTERN, min_length=40, max_length=40)
    tree: str = Field(pattern=_SHA_PATTERN, min_length=40, max_length=40)
    run_id: WorkflowRunId = Field(gt=0)
    run_attempt: int = Field(ge=1)
    kind: CheckKind


class ReviewedAnalysis(BaseModel):
    source_run: WorkflowRunId | None = None
    checks: tuple[CheckKind, ...] = ()
    reason: str


class _Repository(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    repository_id: RepositoryId = Field(alias="id", gt=0)
    full_name: str


class _Revision(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    sha: str = Field(pattern=_SHA_PATTERN, min_length=40, max_length=40)
    ref: str
    repo: _Repository | None


class _Pull(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    number: PullNumber = Field(gt=0)
    merge_commit_sha: str | None
    merged_at: datetime | None
    head: _Revision
    base: _Revision


class _Pulls(RootModel[tuple[_Pull, ...]]):
    pass


class _Run(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    run_id: WorkflowRunId = Field(alias="id", gt=0)
    run_attempt: int = Field(ge=1)
    head_sha: str = Field(pattern=_SHA_PATTERN, min_length=40, max_length=40)
    head_repository: _Repository
    event: str
    path: str
    status: str
    conclusion: str | None
    updated_at: datetime


class _Runs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    total_count: int
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


class _Artifacts(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    total_count: int
    artifacts: tuple[TestedArtifact, ...]


class _SarifDriver(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    name: Literal["CodeQL"]


class _SarifTool(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    driver: _SarifDriver


class _SarifRun(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    tool: _SarifTool


class _Sarif(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    version: Literal["2.1.0"]
    runs: tuple[_SarifRun, ...] = Field(min_length=1)


def find_reviewed_run(
    root: Path,
    repository: str,
    sha: str,
    *,
    runner: ProcessRunner = run_process,
    now: datetime | None = None,
) -> _Run | None:
    pulls = _Pulls.model_validate_json(_api(root, f"repos/{repository}/commits/{sha}/pulls?per_page=100", runner))
    matching = [
        pull
        for pull in pulls.root
        if pull.merge_commit_sha == sha
        and pull.merged_at is not None
        and pull.base.ref == "main"
        and pull.base.repo is not None
        and pull.head.repo is not None
        and pull.base.repo.full_name == repository
        and pull.head.repo.repository_id == pull.base.repo.repository_id
        and pull.head.repo.full_name == repository
    ]
    if len(matching) != 1:
        return None
    pull = matching[0]
    runs = _Runs.model_validate_json(
        _api(
            root,
            f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={pull.head.sha}&event=pull_request&per_page=100",
            runner,
        )
    )
    if runs.total_count != len(runs.workflow_runs):
        return None
    candidates = [run for run in runs.workflow_runs if _is_own_pull_run(run, pull, repository)]
    if not candidates:
        return None
    run = max(candidates, key=lambda candidate: candidate.run_id)
    current = datetime.now(UTC) if now is None else now
    if (
        run.status != "completed"
        or run.conclusion != "success"
        or run.updated_at.tzinfo is None
        or not timedelta(0) <= current - run.updated_at <= _MAX_AGE
    ):
        return None
    return run


def _is_own_pull_run(run: _Run, pull: _Pull, repository: str) -> bool:
    return (
        pull.head.repo is not None
        and run.head_sha == pull.head.sha
        and run.head_repository.full_name == repository
        and run.head_repository.repository_id == pull.head.repo.repository_id
        and run.event == "pull_request"
        and run.path == ".github/workflows/ci.yml"
    )


def verify_analysis_archive(
    archive: Path,
    destination: Path,
    *,
    digest: str,
    repository: str,
    tree: str,
    base: str,
    run_id: WorkflowRunId,
    run_attempt: int,
    kind: CheckKind,
) -> None:
    with archive.open("rb") as stream:
        if "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            msg = "reviewed analysis ZIP digest mismatch"
            raise ValueError(msg)
    with ZipFile(archive) as bundle:
        paths = _archive_paths(bundle, kind)
        proof = AnalysisProof.model_validate_json(bundle.read("proof.json"))
        actual = (proof.repository, proof.tree, proof.comparison_base, proof.run_id, proof.run_attempt, proof.kind)
        expected = (repository, tree, base, run_id, run_attempt, kind)
        if actual != expected:
            msg = "reviewed analysis proof does not match the checked tree and run"
            raise ValueError(msg)
        _verify_results(bundle, paths, proof)
        destination.mkdir(parents=True, exist_ok=True)
        for path in paths:
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(str(path)) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _archive_paths(bundle: ZipFile, kind: CheckKind) -> tuple[PurePosixPath, ...]:
    members = bundle.infolist()
    if len(members) > _MAX_FILES or sum(member.file_size for member in members) > _MAX_BYTES:
        msg = "reviewed analysis ZIP exceeds file/size limits"
        raise ValueError(msg)
    paths = tuple(_member_path(member, kind) for member in members)
    if len(paths) != len(set(paths)):
        msg = "duplicate reviewed analysis ZIP members"
        raise ValueError(msg)
    return tuple(path for member, path in zip(members, paths, strict=True) if not member.is_dir())


def _member_path(member: ZipInfo, kind: CheckKind) -> PurePosixPath:
    path = PurePosixPath(member.filename)
    if member.is_dir():
        if kind != CheckKind.WHEELS or path != PurePosixPath("deps"):
            msg = "unsafe reviewed analysis ZIP directory"
            raise ValueError(msg)
    elif path.is_absolute() or "\\" in str(path) or not _allowed_member(path, kind):
        msg = "unsafe reviewed analysis ZIP member"
        raise ValueError(msg)
    return path


def _verify_results(bundle: ZipFile, paths: tuple[PurePosixPath, ...], proof: AnalysisProof) -> None:
    sarif_paths = [path for path in paths if path.suffix == ".sarif"]
    if bool(sarif_paths) != (proof.kind in {CheckKind.PYTHON, CheckKind.JAVASCRIPT}):
        msg = "reviewed CodeQL proof requires its SARIF results"
        raise ValueError(msg)
    for path in sarif_paths:
        _Sarif.model_validate_json(bundle.read(str(path)))
    if proof.kind == CheckKind.WHEELS:
        if bundle.read("SOURCE_COMMIT").decode("ascii").strip() != proof.source_commit:
            msg = "reviewed wheel source commit does not match its proof"
            raise ValueError(msg)
        if bundle.read("SOURCE_TREE").decode("ascii").strip() != proof.tree:
            msg = "reviewed wheel source tree does not match its proof"
            raise ValueError(msg)
        if not any(path.suffix == ".whl" and len(path.parts) == 1 for path in paths):
            msg = "reviewed wheel proof contains no release wheel"
            raise ValueError(msg)


def _allowed_member(path: PurePosixPath, kind: CheckKind) -> bool:
    if str(path) == "proof.json":
        return True
    if kind in {CheckKind.PYTHON, CheckKind.JAVASCRIPT}:
        return len(path.parts) == 1 and path.suffix == ".sarif"
    if kind != CheckKind.WHEELS:
        return False
    if str(path) in {"SOURCE_COMMIT", "SOURCE_TREE", "SHA256SUMS", "test-plan.json"}:
        return True
    return (len(path.parts) == 1 and path.suffix in {".whl", ".gz"}) or (
        path.parent == PurePosixPath("deps") and path.suffix == ".whl"
    )


def reuse_reviewed_analysis(
    root: Path,
    repository: str,
    sha: str,
    destination: Path,
    *,
    base: str,
    event: str,
    runner: ProcessRunner = run_process,
    downloader: ProcessFileRunner = run_process_to_file,
) -> ReviewedAnalysis:
    if event != "push":
        return ReviewedAnalysis(reason="fresh analysis for PR, weekly/manual audit or unknown event")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None or re.fullmatch(_SHA_PATTERN, sha) is None:
        msg = "reviewed analysis requires a repository and full commit SHA"
        raise ValueError(msg)
    try:
        return _reuse(root, repository, sha, destination, base=base, runner=runner, downloader=downloader)
    except (ProcessFailureError, OSError, ValueError, BadZipFile, KeyError) as error:
        return ReviewedAnalysis(reason=f"fresh analysis: reviewed proof unavailable ({type(error).__name__})")


def _reuse(
    root: Path,
    repository: str,
    sha: str,
    destination: Path,
    *,
    base: str,
    runner: ProcessRunner,
    downloader: ProcessFileRunner,
) -> ReviewedAnalysis:
    parent = runner(("git", "rev-parse", f"{sha}^"), cwd=root, capture_output=True).stdout.strip()
    if parent != base:
        return ReviewedAnalysis(reason="fresh checks: push comparison does not match the merge parent")
    run = find_reviewed_run(root, repository, sha, runner=runner)
    if run is None:
        return ReviewedAnalysis(reason="no recent successful own-repository merged-PR CI")
    tree = runner(("git", "rev-parse", f"{sha}^{{tree}}"), cwd=root, capture_output=True).stdout.strip()
    jobs = _Jobs.model_validate_json(
        _api(root, f"repos/{repository}/actions/runs/{run.run_id}/jobs?per_page=100", runner)
    )
    artifacts = _Artifacts.model_validate_json(
        _api(root, f"repos/{repository}/actions/runs/{run.run_id}/artifacts?per_page=100", runner)
    )
    if jobs.total_count != len(jobs.jobs) or artifacts.total_count != len(artifacts.artifacts):
        return ReviewedAnalysis(reason="incomplete reviewed CI job/artifact response")
    checks = _verified_checks(
        root,
        repository,
        tree,
        run,
        base=base,
        jobs=jobs,
        artifacts=artifacts,
        destination=destination,
        downloader=downloader,
    )
    latest = _Run.model_validate_json(_api(root, f"repos/{repository}/actions/runs/{run.run_id}", runner))
    if latest != run:
        return ReviewedAnalysis(reason="reviewed CI changed while verifying its certificates")
    return ReviewedAnalysis(
        source_run=run.run_id if checks else None,
        checks=checks,
        reason="verified identical reviewed Git tree" if checks else "no matching checked-tree certificates",
    )


def _verified_checks(
    root: Path,
    repository: str,
    tree: str,
    run: _Run,
    *,
    base: str,
    jobs: _Jobs,
    artifacts: _Artifacts,
    destination: Path,
    downloader: ProcessFileRunner,
) -> tuple[CheckKind, ...]:
    verified: list[CheckKind] = []
    for kind, job_name in _JOB_NAMES.items():
        matching_jobs = [job for job in jobs.jobs if job.name == job_name]
        matching_artifacts = [
            artifact
            for artifact in artifacts.artifacts
            if artifact.name == f"reviewed-{kind}-{run.run_attempt}" and not artifact.expired
        ]
        if (
            len(matching_jobs) != 1
            or matching_jobs[0].status != "completed"
            or matching_jobs[0].conclusion != "success"
            or len(matching_artifacts) != 1
        ):
            continue
        artifact = matching_artifacts[0]
        identity = artifact.workflow_run
        if (
            identity.run_id != run.run_id
            or identity.head_sha != run.head_sha
            or identity.repository_id != run.head_repository.repository_id
            or identity.head_repository_id != run.head_repository.repository_id
            or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.digest) is None
        ):
            continue
        with TemporaryDirectory(prefix="sarj-reviewed-analysis-") as temporary:
            archive = Path(temporary) / "analysis.zip"
            downloader(
                ("gh", "api", f"repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip"),
                cwd=root,
                destination=archive,
            )
            verify_analysis_archive(
                archive,
                destination / kind,
                digest=artifact.digest,
                repository=repository,
                tree=tree,
                base=base,
                run_id=run.run_id,
                run_attempt=run.run_attempt,
                kind=kind,
            )
        verified.append(kind)
    return tuple(verified)


def _api(root: Path, endpoint: str, runner: ProcessRunner) -> str:
    return runner(("gh", "api", "--method", "GET", endpoint), cwd=root, capture_output=True).stdout


def main(argv: Sequence[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)

    @app.command()
    def reuse(
        *,
        root: Annotated[Path, typer.Option("--root")],
        repository: Annotated[str, typer.Option("--repository")],
        commit: Annotated[str, typer.Option("--commit")],
        base: Annotated[str, typer.Option("--base")],
        destination: Annotated[Path, typer.Option("--destination")],
        event: Annotated[str, typer.Option("--event")],
        output: Annotated[Path, typer.Option("--github-output")],
        summary: Annotated[Path, typer.Option("--summary")],
    ) -> None:
        report = reuse_reviewed_analysis(root.resolve(), repository, commit, destination, base=base, event=event)
        with output.open("a") as stream:
            for kind in CheckKind:
                stream.write(f"reviewed-{kind}={str(kind in report.checks).lower()}\n")
            stream.write(f"reviewed-run={report.source_run or ''}\n")
        with summary.open("a") as stream:
            stream.write(f"Reviewed analysis: {report.reason}\n\n")
            if report.source_run:
                stream.write(f"Source: https://github.com/{repository}/actions/runs/{report.source_run}\n\n")
            stream.write(f"Reused checks: {', '.join(report.checks) or 'none'}\n")
        sys.stdout.write(report.model_dump_json() + "\n")

    app(args=None if argv is None else list(argv), prog_name="reviewed-analysis", standalone_mode=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
