from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from sarj_standards.libs.diagnostics import Completion, ExecutionIssue, ToolReport

from .execution_plan import AnalysisPlan, AnalyzeGroup as AnalyzeGroup, GroupKind, GroupTask, analysis_jobs


if TYPE_CHECKING:
    from pathlib import Path


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
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="standards") as workers:
        native_result = workers.submit(_run_group, plan.native, root)
        external_result = workers.submit(_run_group, plan.external, root)
        return (*native_result.result(), *external_result.result())


def _run_group(task: GroupTask, root: Path) -> tuple[ToolReport, ...]:
    try:
        return task.analyze()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        message = f"{type(exc).__name__}: {exc}".replace(str(root), ".")
        issue = ExecutionIssue(task.kind.value, "execution-failure", message)
        return (ToolReport(task.kind.value, Completion.FAILED, issues=(issue,)),)
