from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from sarj_standards.libs.diagnostics import Completion, ExecutionIssue, ToolReport


if TYPE_CHECKING:
    from pathlib import Path


type AnalyzeGroup = Callable[[], tuple[ToolReport, ...]]


def analyze_groups(
    root: Path,
    native: AnalyzeGroup,
    external: AnalyzeGroup,
    *,
    jobs: int,
) -> tuple[ToolReport, ...]:
    if jobs not in {1, 2}:
        msg = "analysis jobs must be 1 or 2"
        raise ValueError(msg)
    if jobs == 1:
        return (*_run_group("native", native, root), *_run_group("external", external, root))
    # External type analyzers retain their existing serial execution and shared
    # deadlines. Only this boundary owns concurrency; no nested worker pools.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="standards") as workers:
        native_result = workers.submit(_run_group, "native", native, root)
        external_result = workers.submit(_run_group, "external", external, root)
        return (*native_result.result(), *external_result.result())


def _run_group(name: str, analyze: AnalyzeGroup, root: Path) -> tuple[ToolReport, ...]:
    try:
        return analyze()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        message = f"{type(exc).__name__}: {exc}".replace(str(root), ".")
        issue = ExecutionIssue(name, "execution-failure", message)
        return (ToolReport(name, Completion.FAILED, issues=(issue,)),)
