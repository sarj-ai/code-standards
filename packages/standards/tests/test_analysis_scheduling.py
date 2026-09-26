from __future__ import annotations

from threading import Barrier, Event
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, InvocationId, ToolReport
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.scheduling import analyze_groups


if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.parametrize("jobs", [0, 3])
def test_invalid_worker_count_never_starts_analysis(tmp_path: Path, jobs: int) -> None:
    def unexpected() -> tuple[ToolReport, ...]:
        pytest.fail("invalid worker limit must be rejected before starting")

    with pytest.raises(ValueError, match="1 or 2"):
        analyze_groups(tmp_path, unexpected, unexpected, jobs=jobs)
