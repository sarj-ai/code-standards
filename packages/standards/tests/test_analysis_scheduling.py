from __future__ import annotations

from threading import Barrier, Event
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Severity,
    ToolReport,
)
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.scheduling import analyze_groups


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.linting.scheduling import AnalyzeGroup


def _consumer_group(report: ToolReport) -> AnalyzeGroup:
    return lambda: (report,)


def test_two_jobs_overlap_groups_without_reordering_results(tmp_path: Path) -> None:
    started = Barrier(2, timeout=5)
    external_finished = Event()

    def native() -> tuple[ToolReport, ...]:
        started.wait()
        assert external_finished.wait(timeout=5)
        return (ToolReport("native", Completion.COMPLETE),)

    def external() -> tuple[ToolReport, ...]:
        started.wait()
        external_finished.set()
        return (ToolReport("external", Completion.COMPLETE),)

    reports = analyze_groups(tmp_path, native, external, jobs=2)
    assert [report.name for report in reports] == ["native", "external"]


def test_one_job_completes_native_before_starting_external(tmp_path: Path) -> None:
    calls: list[str] = []

    def native() -> tuple[ToolReport, ...]:
        calls.append("native")
        return ()

    def external() -> tuple[ToolReport, ...]:
        assert calls == ["native"]
        calls.append("external")
        return ()

    assert analyze_groups(tmp_path, native, external, jobs=1) == ()
    assert calls == ["native", "external"]


@pytest.mark.parametrize("jobs", [1, 2])
def test_failed_group_preserves_completed_group_and_redacts_root(tmp_path: Path, jobs: int) -> None:
    successful = ToolReport("native", Completion.COMPLETE)

    def external() -> tuple[ToolReport, ...]:
        message = f"analyzer failed in {tmp_path}"
        raise RuntimeError(message)

    reports = analyze_groups(tmp_path, lambda: (successful,), external, jobs=jobs)
    report = report_from_tools(tmp_path, reports)
    assert report.completion is Completion.PARTIAL
    assert successful in report.tools
    assert str(tmp_path) not in report.issues[0].message


def test_same_analyzer_invocations_have_deterministic_report_order(tmp_path: Path) -> None:
    first = ToolReport("eslint", Completion.COMPLETE, invocation_id=InvocationId("a"))
    second = ToolReport("eslint", Completion.COMPLETE, invocation_id=InvocationId("b"))
    assert report_from_tools(tmp_path, [second, first]) == report_from_tools(tmp_path, [first, second])


@pytest.mark.parametrize(
    "jobs",
    [0, 3, True, False, 1.0, 2.0, "1", None, pytest.param([1], id="mutable-list")],
)
def test_invalid_worker_count_never_starts_analysis(tmp_path: Path, jobs: int) -> None:
    def unexpected() -> tuple[ToolReport, ...]:
        pytest.fail("invalid worker limit must be rejected before starting")

    with pytest.raises(ValueError, match="1 or 2"):
        analyze_groups(tmp_path, unexpected, unexpected, jobs=jobs)


@pytest.mark.parametrize("jobs", [1, 2])
def test_typed_groups_preserve_entire_reports_in_native_first_order(tmp_path: Path, jobs: int) -> None:
    native = ToolReport(
        "sarj-python-lint",
        Completion.COMPLETE,
        diagnostics=(Diagnostic("SARJ001", "native finding", Severity.ERROR, "python", Location("app.py")),),
        duration_ms=7,
        file_count=1,
    )
    external = ToolReport(
        "ruff",
        Completion.PARTIAL,
        diagnostics=(Diagnostic("F401", "external finding", Severity.ERROR, "ruff", Location("app.py")),),
        issues=(ExecutionIssue("ruff", "coverage-missing", "one input unavailable"),),
        invocation_id=InvocationId("ruff:project"),
        duration_ms=11,
        file_count=2,
    )

    actual = analyze_groups(tmp_path, _consumer_group(native), _consumer_group(external), jobs=jobs)

    assert actual == (native, external)
    assert report_from_tools(tmp_path, actual) == report_from_tools(tmp_path, (native, external))


@pytest.mark.parametrize("jobs", [1, 2])
@pytest.mark.parametrize("error", [OSError, TypeError, ValueError, RuntimeError])
def test_typed_native_failure_preserves_external_report(tmp_path: Path, jobs: int, error: type[Exception]) -> None:
    successful = ToolReport("ruff", Completion.COMPLETE, file_count=1)

    def native() -> tuple[ToolReport, ...]:
        message = f"failed in {tmp_path}"
        raise error(message)

    reports = analyze_groups(tmp_path, native, lambda: (successful,), jobs=jobs)

    assert reports == (
        ToolReport(
            "native",
            Completion.FAILED,
            issues=(ExecutionIssue("native", "execution-failure", f"{error.__name__}: failed in ."),),
        ),
        successful,
    )
    assert type(reports[0].name) is str
