from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import multiprocessing
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule
from sarj_python_lint.rules._local_source import LOCAL_SOURCE_CACHE_LIMIT
from sarj_python_lint.rules._paths import clear_path_caches
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from sarj_python_lint.rules._project_index import ProjectSourceSnapshot


type _ResolutionKey = tuple[Path, str | None, int]


@dataclass
class _WorkerState:
    rules: list[Rule]
    session: AnalysisSession
    resolutions: frozenset[_ResolutionKey] = frozenset()
    modules: frozenset[Path] = frozenset()


@dataclass(frozen=True, slots=True)
class _FileResult:
    diagnostics: list[Diagnostic]
    resolutions: frozenset[_ResolutionKey]
    modules: frozenset[Path]


_state: _WorkerState | None = None


def _initialize(rule_types: list[type[Rule]], snapshot: ProjectSourceSnapshot | None) -> None:
    global _state  # ruff: ignore[global-statement] -- each spawned process owns one initialized session.
    rules = [rule_type() for rule_type in rule_types]
    session = AnalysisSession()
    for rule in rules:
        rule.prepare_session(session)
    clear_path_caches()
    project = ProjectIndexSet.from_source_snapshot(snapshot) if snapshot is not None else None
    session.project = project
    for rule in rules:
        if isinstance(rule, ProjectRule) and project is not None:
            rule.prepare(project)
    _state = _WorkerState(rules, session)


def _check_file(item: tuple[Path, str]) -> _FileResult:
    from sarj_python_lint.__main__ import check_source  # ruff: ignore[import-outside-top-level] -- keep spawn targets in an importable module.

    if _state is None:
        msg = "Python analysis worker was not initialized"
        raise RuntimeError(msg)
    path, source = item
    diagnostics = check_source(_state.rules, path, source, session=_state.session)
    keys = _state.session.local_source.cache_keys()
    result = _FileResult(diagnostics, keys.resolutions - _state.resolutions, keys.modules - _state.modules)
    _state.resolutions, _state.modules = keys.resolutions, keys.modules
    return result


def check_parallel(
    rule_types: list[type[Rule]],
    loaded: dict[Path, str],
    project: ProjectIndexSet | None,
    *,
    jobs: int,
) -> list[Diagnostic] | None:
    # The untouched parent rules/session remain the serial fallback. Workers
    # receive the same complete project snapshot and selected source strings.
    workers = min(jobs, 2, len(loaded))
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize,
        initargs=(rule_types, project.source_snapshot() if project is not None else None),
    )
    diagnostics: list[Diagnostic] = []
    resolutions: set[_ResolutionKey] = set()
    modules: set[Path] = set()
    try:
        # Keep workers busy while an earlier file delays ordered results.
        for result in pool.map(_check_file, loaded.items(), chunksize=1, buffersize=workers * 4):
            resolutions.update(result.resolutions)
            modules.update(result.modules)
            # A worker cannot hit either order-dependent limit when the whole
            # union stays strictly below it. At the boundary, discard all output.
            if len(resolutions) >= LOCAL_SOURCE_CACHE_LIMIT or len(modules) >= LOCAL_SOURCE_CACHE_LIMIT:
                return None
            diagnostics.extend(result.diagnostics)
        return diagnostics
    finally:
        # Bound queued work and reap before fallback/error return. Running file
        # checks finish normally; group cancellation belongs to the supervisor.
        pool.shutdown(wait=True, cancel_futures=True)
