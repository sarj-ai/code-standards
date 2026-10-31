from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.diagnostics import Completion, ExecutionIssue, ToolReport

from .execution_plan import AnalysisPlan, AnalyzeGroup as AnalyzeGroup, GroupKind, GroupTask, analysis_jobs
from .process import (
    ProcessCancelledError,
    current_cancellation,
    initialize_process_cancellation,
    raise_if_cancelled,
)


if TYPE_CHECKING:
    from concurrent.futures import Future
    from pathlib import Path


_MAX_WORKER_EXCEPTION_DETAILS: Final = 8


def analyze_groups(
    root: Path,
    native: AnalyzeGroup,
    external: AnalyzeGroup,
    *,
    jobs: int,
) -> tuple[ToolReport, ...]:
    validated_jobs = analysis_jobs(jobs)
    plan = AnalysisPlan(GroupTask(GroupKind.NATIVE, native), GroupTask(GroupKind.EXTERNAL, external), validated_jobs)
    if plan.jobs == 1:
        return (*_run_group(plan.native, root), *_run_group(plan.external, root))
    cancellation = current_cancellation() or Event()
    workers = ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="standards",
        initializer=initialize_process_cancellation,
        initargs=(cancellation,),
    )
    submitted: list[tuple[GroupKind, Future[tuple[ToolReport, ...]]]] = []
    try:
        for group in (plan.native, plan.external):
            future = workers.submit(_run_group, group, root)
            submitted.append((group.kind, future))
        reports = (*submitted[0][1].result(), *submitted[1][1].result())
    except (KeyboardInterrupt, SystemExit) as interruption:
        _finish_interruption(workers, submitted, cancellation, interruption, root)
        raise
    except BaseException:
        try:
            workers.shutdown(wait=True)
        except (KeyboardInterrupt, SystemExit) as interruption:
            # This is a first caller interruption, even though a peer failed earlier.
            _finish_interruption(workers, submitted, cancellation, interruption, root)
            raise
        raise
    else:
        try:
            workers.shutdown(wait=True)
        except (KeyboardInterrupt, SystemExit) as interruption:
            _finish_interruption(workers, submitted, cancellation, interruption, root)
            raise
        return reports


def _finish_interruption(
    workers: ThreadPoolExecutor,
    submitted: list[tuple[GroupKind, Future[tuple[ToolReport, ...]]]],
    cancellation: Event,
    interruption: BaseException,
    root: Path,
) -> None:
    # Signal before joining; queued callbacks and running waits share this token.
    cancellation.set()
    try:
        workers.shutdown(wait=True, cancel_futures=True)
    except BaseException as cleanup_error:  # ruff: ignore[blind-except] -- preserve the original caller interruption if joining fails or is interrupted again.
        interruption.add_note("Analysis worker shutdown was interrupted or failed; remaining cleanup is unconfirmed.")
        try:
            _attach_worker_error(interruption, cleanup_error, "worker shutdown", root)
        except BaseException:  # ruff: ignore[blind-except] -- malformed custom exception details cannot replace the original interruption.
            interruption.add_note("Worker shutdown failure details could not be fully collected.")
    try:
        _attach_worker_outcomes(interruption, submitted, root)
    except BaseException:  # ruff: ignore[blind-except] -- preserve interruption even if formatting fails or collection is interrupted again.
        interruption.add_note("Worker cleanup evidence could not be fully collected; cleanup remains unconfirmed.")


def _attach_worker_outcomes(
    interruption: BaseException,
    submitted: list[tuple[GroupKind, Future[tuple[ToolReport, ...]]]],
    root: Path,
) -> None:
    for kind, result in submitted:
        if not result.done():
            interruption.add_note(f"{kind.value} worker has not completed; its cleanup is unconfirmed.")
            continue
        if not result.cancelled() and (error := result.exception()) is not None:
            _attach_worker_error(interruption, error, f"{kind.value} worker", root)


def _attach_worker_error(interruption: BaseException, error: BaseException, label: str, root: Path) -> None:
    pending = [(label, error)]
    seen = {id(interruption)}
    # Preserve actual exception chains as notes without changing the caller's cause.
    # The bound also handles arbitrarily long or cyclic custom exception chains.
    while pending and len(seen) <= _MAX_WORKER_EXCEPTION_DETAILS:
        current_label, current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if not isinstance(current, ProcessCancelledError):
            message = f"{current_label}: {type(current).__name__}: {current}".replace(str(root), ".")
            interruption.add_note(message)
        if hasattr(  # sarj-noqa: SARJ499 -- Exception notes are optional until add_note is called; preserve available failure details.
            current, "__notes__"
        ):
            for note in current.__notes__:
                interruption.add_note(f"{current_label}: {note}".replace(str(root), "."))
        if current.__context__ is not None:
            pending.append((f"{current_label} context", current.__context__))
        if current.__cause__ is not None:
            pending.append((f"{current_label} cause", current.__cause__))
    if pending:
        interruption.add_note("Additional worker exception-chain detail was truncated after eight distinct exceptions.")


def _run_group(task: GroupTask, root: Path) -> tuple[ToolReport, ...]:
    raise_if_cancelled(current_cancellation())
    try:
        return task.analyze()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        cancellation = current_cancellation()
        if cancellation is not None and cancellation.is_set():
            # During caller cancellation, retain replacement cleanup failures and
            # their original exception chains for the caller's interruption notes.
            raise
        message = f"{type(exc).__name__}: {exc}".replace(str(root), ".")
        issue = ExecutionIssue(task.kind.value, "execution-failure", message)
        return (ToolReport(task.kind.value, Completion.FAILED, issues=(issue,)),)
