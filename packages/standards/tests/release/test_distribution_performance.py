from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from threading import Barrier
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field
import pytest
import yaml

from sarj_standards.libs.release import wheel_tests
from sarj_standards.libs.release.process import ProcessResult
from sarj_standards.libs.release.registry import RegistryRequirement, publication_results
from sarj_standards.libs.release.status import release_status


if TYPE_CHECKING:
    from collections.abc import Mapping


REPO_ROOT = Path(__file__).resolve().parents[4]
SHA = "a" * 40


class _WorkflowJob(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    needs: str | tuple[str, ...] = ()
    condition: str = Field(default="", alias="if")


class _Workflow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    jobs: dict[str, _WorkflowJob]


def _release_workflow() -> _Workflow:
    value: object = yaml.safe_load(  # pyright: ignore[reportAny] -- validate the untyped YAML boundary immediately
        (REPO_ROOT / ".github/workflows/release.yml").read_text()
    )
    return _Workflow.model_validate(value)


def test_registry_reads_overlap_and_deduplicate_requirements() -> None:
    barrier = Barrier(4)
    requirements = tuple(RegistryRequirement("pypi", f"package-{index}", "1.0.0") for index in range(4))
    calls: list[RegistryRequirement] = []

    def checker(requirement: RegistryRequirement) -> bool:
        calls.append(requirement)
        barrier.wait(timeout=5)
        return True

    results = publication_results((*requirements, requirements[0]), checker=checker)
    assert tuple(results) == requirements
    assert all(results.values())
    assert sorted(calls) == sorted(requirements)


def test_registry_reads_keep_successes_beside_a_transport_failure() -> None:
    requirements = tuple(RegistryRequirement("pypi", f"package-{index}", "1.0.0") for index in range(3))

    def checker(requirement: RegistryRequirement) -> bool:
        if requirement == requirements[0]:
            msg = "registry unavailable"
            raise OSError(msg)
        return requirement == requirements[1]

    results = publication_results(requirements, checker=checker)
    assert isinstance(results[requirements[0]], OSError)
    assert results[requirements[1]] is True
    assert results[requirements[2]] is False


@pytest.mark.parametrize(
    "target", ["typescript", "bootstrap", "contracts", "python", "sql", "iac", "standards", "tsconfig"]
)
def test_every_publisher_retains_the_exact_revision_safety_gate(target: str) -> None:
    publisher = _release_workflow().jobs[f"publish-{target}"]
    assert "release-safety" in publisher.needs
    assert "needs.release-safety.result == 'success'" in publisher.condition
    assert f"needs.build-{target}.result == 'success'" in publisher.condition


def test_standards_publication_retains_portability_and_sibling_gates() -> None:
    jobs = _release_workflow().jobs
    assert jobs["build-standards"].needs == "detect"
    assert jobs["portability-standards"].needs == "detect"
    publisher = jobs["publish-standards"]
    assert "needs.portability-standards.result == 'success'" in publisher.condition
    for sibling in ("bootstrap", "contracts", "typescript", "python", "sql", "iac"):
        assert f"publish-{sibling}" in publisher.needs
        assert f"needs.publish-{sibling}.result == 'success'" in publisher.condition


def test_release_conditions_reference_declared_dependencies() -> None:
    for name, job in _release_workflow().jobs.items():
        dependencies = (job.needs,) if isinstance(job.needs, str) else job.needs
        referenced = set(re.findall(r"needs\.([a-z-]+)\.", job.condition))
        assert referenced.issubset(dependencies), f"{name}: undeclared needs {referenced.difference(dependencies)}"


def test_release_status_reports_queue_time_and_latest_attempt(tmp_path: Path) -> None:
    runs = [
        {
            "databaseId": identifier,
            "workflowName": "release",
            "status": "completed",
            "conclusion": conclusion,
            "createdAt": created,
            "updatedAt": "2026-10-07T15:00:00Z",
            "headSha": SHA,
            "url": f"https://github.com/example/repo/actions/runs/{identifier}",
        }
        for identifier, conclusion, created in (
            (1, "failure", "2026-10-07T14:00:00Z"),
            (2, "success", "2026-10-07T14:30:00Z"),
        )
    ]

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path
        assert capture_output
        if argv[0] == "git":
            return ProcessResult(0, SHA)
        if argv[2] == "list":
            return ProcessResult(0, json.dumps(runs))
        assert argv[3] == "2"
        return ProcessResult(
            0,
            json.dumps(
                {
                    "jobs": [
                        {
                            "name": "build-standards",
                            "status": "completed",
                            "conclusion": "success",
                            "startedAt": "2026-10-07T14:40:00Z",
                            "completedAt": "2026-10-07T14:50:00Z",
                        }
                    ]
                }
            ),
        )

    report = release_status(tmp_path, runner=runner, now=datetime(2026, 10, 7, 15, tzinfo=UTC))
    stage = next(item for item in report.workflows if item.workflow == "release")
    assert stage.status == "success"
    assert stage.elapsed_seconds == 1800
    assert stage.queue_seconds == 600
    assert stage.jobs[0].elapsed_seconds == 600
    assert next(item for item in report.workflows if item.workflow == "CI").status == "not-started"


def test_wheel_tests_preserve_existing_distributions_and_use_fresh_local_wheels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "packages/standards/dist/keep.whl"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing artifact")
    installed: list[str] = []
    test_paths: list[Path] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path
        assert not capture_output
        if argv[1] == "build":
            destination = Path(argv[-1])
            destination.mkdir(exist_ok=True)
            (destination / (Path(argv[4]).name + ".whl")).write_text("fresh")
        elif argv[1] == "pip":
            installed.extend(argv)
        return ProcessResult(0)

    def execute(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool = False,
        environment: Mapping[str, str] | None,
    ) -> ProcessResult:
        assert cwd == tmp_path / "packages/standards"
        assert not capture_output
        assert environment is not None
        assert "GH_TOKEN" not in environment
        assert "-k" in argv
        assert "release" in argv
        assert argv[argv.index("-n") + 1] == "2"
        test_paths.append(Path(argv[0]))
        return ProcessResult(0)

    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the test process boundary to inspect isolation
        wheel_tests,
        "run_process_environment",
        execute,
    )
    wheel_tests.run_wheel_tests(tmp_path, jobs=2, pytest_args=("-k", "release"), runner=runner)
    assert existing.read_text() == "existing artifact"
    assert len([item for item in installed if item.endswith(".whl")]) == 5
    assert all(str(existing) != item for item in installed)
    assert not test_paths[0].parent.parent.exists()


@pytest.mark.parametrize("jobs", ["0", "17"])
def test_wheel_test_cli_rejects_unbounded_workers(jobs: str) -> None:
    with pytest.raises(SystemExit) as stopped:
        wheel_tests.main(["--jobs", jobs])
    assert stopped.value.code == 2
