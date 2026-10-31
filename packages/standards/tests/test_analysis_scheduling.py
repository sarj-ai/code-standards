from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import TYPE_CHECKING, override

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
from sarj_standards.libs.linting import scheduling
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.process import (
    ProcessCancelledError,
    current_cancellation,
    initialize_process_cancellation,
)
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


@pytest.mark.parametrize("jobs", [1, 2])
def test_cancelled_nested_analysis_never_dispatches_callbacks_and_does_not_leak(tmp_path: Path, jobs: int) -> None:
    cancellation = Event()
    cancellation.set()

    def unexpected() -> tuple[ToolReport, ...]:
        pytest.fail("cancelled analysis must not enter a new adapter")

    with ThreadPoolExecutor(
        max_workers=1,
        initializer=initialize_process_cancellation,
        initargs=(cancellation,),
    ) as workers:
        result = workers.submit(analyze_groups, tmp_path, unexpected, unexpected, jobs=jobs)
        with pytest.raises(ProcessCancelledError):
            result.result(timeout=5)
    successful = ToolReport("native", Completion.COMPLETE)
    assert analyze_groups(tmp_path, _consumer_group(successful), lambda: (), jobs=jobs) == (successful,)


@pytest.mark.parametrize("failure_kind", ["native", "external"])
@pytest.mark.parametrize("failure_type", [LookupError, AssertionError])
@pytest.mark.parametrize("cleanup_type", [ProcessCancelledError, LookupError, RuntimeError])
def test_unexpected_worker_failure_cancels_peer_and_retains_cleanup_details(
    tmp_path: Path, failure_kind: str, failure_type: type[Exception], cleanup_type: type[BaseException]
) -> None:
    peer_started = Event()
    peer_finished = Event()
    original = failure_type("unexpected analyzer failure")
    original.add_note("original worker note")

    def failing() -> tuple[ToolReport, ...]:
        assert peer_started.wait(timeout=5)
        raise original

    def peer() -> tuple[ToolReport, ...]:
        cancellation = current_cancellation()
        assert cancellation is not None
        peer_started.set()
        assert cancellation.wait(timeout=5)
        failure = cleanup_type("cancelled peer cleanup")
        failure.add_note("owned peer cleanup witness")
        peer_finished.set()
        raise failure

    native, external = (failing, peer) if failure_kind == "native" else (peer, failing)
    with pytest.raises(failure_type) as observed:
        analyze_groups(tmp_path, native, external, jobs=2)
    assert observed.value is original
    assert peer_finished.is_set()
    assert original.__notes__[0] == "original worker note"
    peer_kind = "external" if failure_kind == "native" else "native"
    assert f"{peer_kind} worker: owned peer cleanup witness" in original.__notes__
    if cleanup_type is not ProcessCancelledError:
        assert f"{peer_kind} worker: {cleanup_type.__name__}: cancelled peer cleanup" in original.__notes__
    assert original.__cause__ is None
    successful = ToolReport("native", Completion.COMPLETE)
    assert analyze_groups(tmp_path, _consumer_group(successful), lambda: (), jobs=2) == (successful,)


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_caller_interruption_retains_actual_worker_cleanup_notes(
    tmp_path: Path, interruption_type: type[BaseException]
) -> None:
    worker_started = Event()
    original = interruption_type("caller interruption")
    original.add_note("original caller note")

    def native() -> tuple[ToolReport, ...]:
        assert worker_started.wait(timeout=5)
        raise original

    def external() -> tuple[ToolReport, ...]:
        worker_started.set()
        cancellation = current_cancellation()
        assert cancellation is not None
        assert cancellation.wait(timeout=5)
        failure = ProcessCancelledError("analysis process cancelled")
        failure.add_note("analyzer process cleanup failed: owned wait failure")
        raise failure

    with pytest.raises(interruption_type) as observed:
        analyze_groups(tmp_path, native, external, jobs=2)
    assert observed.value is original
    assert original.__notes__ == [
        "original caller note",
        "external worker: analyzer process cleanup failed: owned wait failure",
    ]
    assert original.__cause__ is None


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("replacement_type", [RuntimeError, LookupError])
def test_caller_interruption_retains_replacement_worker_failure_and_its_cause(
    tmp_path: Path, interruption_type: type[BaseException], replacement_type: type[Exception]
) -> None:
    worker_started = Event()
    original = interruption_type("caller interruption")

    def native() -> tuple[ToolReport, ...]:
        assert worker_started.wait(timeout=5)
        raise original

    def external() -> tuple[ToolReport, ...]:
        worker_started.set()
        cancellation = current_cancellation()
        assert cancellation is not None
        assert cancellation.wait(timeout=5)
        cancelled = ProcessCancelledError("analysis process cancelled")
        cancelled.add_note("analyzer stream cleanup failed: owned drain failure")
        message = "replacement cleanup failure"
        raise replacement_type(message) from cancelled

    with pytest.raises(interruption_type) as observed:
        analyze_groups(tmp_path, native, external, jobs=2)
    assert observed.value is original
    assert any(f"{replacement_type.__name__}: replacement cleanup failure" in note for note in original.__notes__)
    assert any("owned drain failure" in note for note in original.__notes__)
    assert original.__cause__ is None


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_unformattable_worker_failure_cannot_replace_caller_interruption(
    tmp_path: Path, interruption_type: type[BaseException]
) -> None:
    class UnformattableWorkerError(LookupError):
        @override
        def __str__(self) -> str:
            message = "worker detail formatting failed"
            raise RuntimeError(message)

    worker_started = Event()
    original = interruption_type("caller interruption")

    def native() -> tuple[ToolReport, ...]:
        assert worker_started.wait(timeout=5)
        raise original

    def external() -> tuple[ToolReport, ...]:
        worker_started.set()
        cancellation = current_cancellation()
        assert cancellation is not None
        assert cancellation.wait(timeout=5)
        raise UnformattableWorkerError

    with pytest.raises(interruption_type) as observed:
        analyze_groups(tmp_path, native, external, jobs=2)
    assert observed.value is original
    assert any("cleanup remains unconfirmed" in note for note in original.__notes__)
    assert original.__cause__ is None


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_first_caller_interrupt_during_failure_join_cancels_the_running_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption_type: type[BaseException]
) -> None:
    original = interruption_type("caller interrupted the failure join")
    worker_started = Event()
    native_failure = LookupError("native failed before caller interruption")

    class InterruptedFirstJoin(ThreadPoolExecutor):
        interrupted: bool = False

        @override
        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
            if not self.interrupted:
                self.interrupted = True
                raise original
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def native() -> tuple[ToolReport, ...]:
        assert worker_started.wait(timeout=5)
        raise native_failure

    def external() -> tuple[ToolReport, ...]:
        worker_started.set()
        cancellation = current_cancellation()
        assert cancellation is not None
        assert cancellation.wait(timeout=5)
        failure = ProcessCancelledError("analysis process cancelled")
        failure.add_note("analyzer stream cleanup failed: first-join interruption witness")
        raise failure

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- interrupt the first real executor shutdown; preserve actual workers and subsequent join.
        scheduling, "ThreadPoolExecutor", InterruptedFirstJoin
    )
    with pytest.raises(interruption_type) as observed:
        analyze_groups(tmp_path, native, external, jobs=2)
    assert observed.value is original
    assert original.__context__ is native_failure
    assert any("LookupError: native failed before caller interruption" in note for note in original.__notes__)
    assert any("first-join interruption witness" in note for note in original.__notes__)
