from __future__ import annotations

from datetime import UTC, datetime
import re
import sys
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field, RootModel

from sarj_standards.libs.release.process import ProcessRunner, run_process


if TYPE_CHECKING:
    from pathlib import Path


_WORKFLOWS = ("release-ready", "private references", "CI", "release", "release-tags", "Standards rollout")
_FIRST_VALID_YEAR = 1970
_RUN_FIELDS = "databaseId,workflowName,status,conclusion,createdAt,updatedAt,headSha,url"


class _Run(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    database_id: int = Field(alias="databaseId", gt=0)
    workflow_name: str = Field(alias="workflowName")
    status: str
    conclusion: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    head_sha: str = Field(alias="headSha")
    url: str


class _Runs(RootModel[tuple[_Run, ...]]):
    pass


class _Job(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str
    status: str
    conclusion: str | None
    started_at: datetime | None = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")


class _Jobs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    jobs: tuple[_Job, ...]


class ReleaseJobStatus(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    name: str
    status: str
    elapsed_seconds: float = Field(serialization_alias="elapsedSeconds")


class ReleaseStage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    workflow: str
    status: str
    elapsed_seconds: float = Field(default=0, serialization_alias="elapsedSeconds")
    queue_seconds: float = Field(default=0, serialization_alias="queueSeconds")
    url: str = ""
    jobs: tuple[ReleaseJobStatus, ...] = ()


class ReleaseStatus(BaseModel):
    commit: str
    workflows: tuple[ReleaseStage, ...]


def release_status(
    root: Path,
    *,
    commit: str = "HEAD",
    runner: ProcessRunner = run_process,
    now: datetime | None = None,
) -> ReleaseStatus:
    if not commit or commit.startswith("-"):
        msg = "release status requires a commit or revision"
        raise ValueError(msg)
    sha = runner(("git", "rev-parse", "--verify", f"{commit}^{{commit}}"), cwd=root, capture_output=True).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        msg = "could not resolve release status revision"
        raise ValueError(msg)
    result = runner(
        ("gh", "run", "list", "--branch", "main", "--commit", sha, "--limit", "50", "--json", _RUN_FIELDS),
        cwd=root,
        capture_output=True,
    )
    runs = _Runs.model_validate_json(result.stdout).root
    latest: dict[str, _Run] = {}
    for run in sorted(
        runs,
        key=lambda item: (item.conclusion not in {"cancelled", "skipped"}, item.created_at),
        reverse=True,
    ):
        if run.head_sha == sha and run.workflow_name in _WORKFLOWS:
            latest.setdefault(run.workflow_name, run)
    current = datetime.now(UTC) if now is None else now
    stages: list[ReleaseStage] = []
    for name in _WORKFLOWS:
        run = latest.get(name)
        if run is None:
            stages.append(ReleaseStage(workflow=name, status="not-started"))
            continue
        result = runner(
            ("gh", "run", "view", str(run.database_id), "--json", "jobs"),
            cwd=root,
            capture_output=True,
        )
        jobs = _Jobs.model_validate_json(result.stdout).jobs
        stages.append(_release_stage(run, jobs, current))
    return ReleaseStatus(commit=sha, workflows=tuple(stages))


def print_release_status(root: Path, *, commit: str = "HEAD", output_format: str = "text") -> int:
    report = release_status(root, commit=commit)
    if output_format == "json":
        sys.stdout.write(report.model_dump_json(by_alias=True, indent=2) + "\n")
    else:
        sys.stdout.write(f"Release stages at {report.commit}\n")
        for stage in report.workflows:
            sys.stdout.write(
                f"{stage.workflow}: {stage.status} (elapsed {stage.elapsed_seconds}s, queued {stage.queue_seconds}s)\n"
            )
            for job in stage.jobs:
                sys.stdout.write(f"  {job.name}: {job.status} ({job.elapsed_seconds}s)\n")
            if stage.url:
                sys.stdout.write(stage.url + "\n")
    return 0


def _release_stage(run: _Run, jobs: tuple[_Job, ...], current: datetime) -> ReleaseStage:
    end = run.updated_at if run.status == "completed" else current
    started = tuple(
        job.started_at
        for job in jobs
        if job.status != "queued" and job.started_at is not None and job.started_at.year >= _FIRST_VALID_YEAR
    )
    return ReleaseStage(
        workflow=run.workflow_name,
        status=run.conclusion or run.status,
        elapsed_seconds=_seconds(run.created_at, end),
        queue_seconds=_seconds(run.created_at, min(started) if started else end),
        url=run.url,
        jobs=tuple(
            ReleaseJobStatus(
                name=job.name,
                status=job.conclusion or job.status,
                elapsed_seconds=_seconds(job.started_at, _job_end(job, current)),
            )
            for job in jobs
        ),
    )


def _job_end(job: _Job, current: datetime) -> datetime:
    if job.completed_at is not None and job.completed_at.year >= _FIRST_VALID_YEAR:
        return job.completed_at
    return current


def _seconds(start: datetime | None, end: datetime) -> float:
    if start is None or start.year < _FIRST_VALID_YEAR:
        return 0
    return max(0, round((end - start).total_seconds(), 1))
