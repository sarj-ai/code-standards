from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import multiprocessing
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._prepared_sources import NeedsSerialSourceError, PreparedSourceInputs
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule
from sarj_python_lint.rules._local_source import LOCAL_SOURCE_CACHE_LIMIT
from sarj_python_lint.rules._paths import clear_path_caches
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from sarj_python_lint._prepared_sources import PreparedSourceSnapshot
    from sarj_python_lint.rules._project_index import ProjectSourceSnapshot


type _ResolutionKey = tuple[Path, str | None, int]


@dataclass
class _WorkerState:
    rules: list[Rule]
    session: AnalysisSession
    resolutions: frozenset[_ResolutionKey] = frozenset()
    modules: frozenset[Path] = frozenset()
    needs_serial: bool = False


@dataclass(frozen=True, slots=True)
class _FileResult:
    diagnostics: list[Diagnostic]
    resolutions: frozenset[_ResolutionKey]
    modules: frozenset[Path]
    needs_serial: bool = False


_state: _WorkerState | None = None


def _initialize(
    rule_types: list[type[Rule]],
    snapshot: ProjectSourceSnapshot | None,
    source_snapshot: PreparedSourceSnapshot | None = None,
) -> None:
    global _state  # ruff: ignore[global-statement] -- each spawned process owns one initialized session.
    rules = [rule_type() for rule_type in rule_types]
    source_inputs = None if source_snapshot is None else PreparedSourceInputs.from_source_snapshot(source_snapshot)
    session = AnalysisSession() if source_inputs is None else AnalysisSession(source_inputs=source_inputs)
    _state = _WorkerState(rules, session)
    try:
        _prepare_worker(_state, snapshot, source_inputs=source_inputs)
    except NeedsSerialSourceError:
        _state.needs_serial = True


def _prepare_worker(
    state: _WorkerState, snapshot: ProjectSourceSnapshot | None, *, source_inputs: PreparedSourceInputs | None
) -> None:
    for rule in state.rules:
        rule.prepare_session(state.session)
    clear_path_caches()
    project = None
    if snapshot is not None:
        project = (
            ProjectIndexSet.from_source_snapshot(snapshot)
            if source_inputs is None
            else ProjectIndexSet.from_source_snapshot(snapshot, sealed=True)
        )
    state.session.project = project
    for rule in state.rules:
        if isinstance(rule, ProjectRule) and project is not None:
            rule.prepare(project)


def _check_file(item: tuple[Path, str | None]) -> _FileResult:
    from sarj_python_lint.__main__ import check_source  # ruff: ignore[import-outside-top-level] -- keep spawn targets in an importable module.

    if _state is None:
        msg = "Python analysis worker was not initialized"
        raise RuntimeError(msg)
    path, source = item
    if _state.needs_serial:
        return _FileResult([], frozenset(), frozenset(), needs_serial=True)
    try:
        if source is None:
            source = _selected_worker_source(_state.session, path)
        diagnostics = check_source(_state.rules, path, source, session=_state.session)
    except NeedsSerialSourceError:
        _state.needs_serial = True
        return _FileResult([], frozenset(), frozenset(), needs_serial=True)
    keys = _state.session.local_source.cache_keys()
    result = _FileResult(diagnostics, keys.resolutions - _state.resolutions, keys.modules - _state.modules)
    _state.resolutions, _state.modules = keys.resolutions, keys.modules
    return result


def _selected_worker_source(session: AnalysisSession, path: Path) -> str:
    if session.source_inputs is None:
        raise NeedsSerialSourceError
    return session.source_inputs.selected_text(path)


def check_parallel(
    rule_types: list[type[Rule]],
    loaded: dict[Path, str],
    project: ProjectIndexSet | None,
    *,
    jobs: int,
    source_inputs: PreparedSourceInputs | None = None,
) -> list[Diagnostic] | None:
    # The untouched parent rules/session remain the serial fallback. Workers
    # receive the same complete project snapshot and selected source strings.
    source_snapshot = None if source_inputs is None else source_inputs.source_snapshot()
    if source_snapshot is not None and source_snapshot.eligible_raw_count >= LOCAL_SOURCE_CACHE_LIMIT:
        return None
    workers = min(jobs, 2, len(loaded))
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize,
        initargs=(rule_types, project.source_snapshot() if project is not None else None, source_snapshot),
    )
    diagnostics: list[Diagnostic] = []
    resolutions: set[_ResolutionKey] = set()
    modules: set[Path] = set()
    needs_serial = False
    try:
        # Keep workers busy while an earlier file delays ordered results.
        items = (
            (
                path,
                None
                if source_inputs is not None
                and (captured := source_inputs.selected_capture(path)) is not None
                and captured.snapshot is not None
                else source,
            )
            for path, source in loaded.items()
        )
        for result in pool.map(_check_file, items, chunksize=1, buffersize=workers * 4):
            # Drain actual results after either replay signal so a later worker
            # failure cannot be disguised as a clean serial replay.
            if needs_serial:
                continue
            resolutions.update(result.resolutions)
            modules.update(result.modules)
            # A worker cannot hit either order-dependent limit when the whole
            # union stays strictly below it. At the boundary, discard all output.
            if (
                result.needs_serial
                or len(resolutions) >= LOCAL_SOURCE_CACHE_LIMIT
                or len(modules) >= LOCAL_SOURCE_CACHE_LIMIT
            ):
                needs_serial = True
                diagnostics.clear()
                resolutions.clear()
                modules.clear()
                continue
            diagnostics.extend(result.diagnostics)
        return None if needs_serial else diagnostics
    finally:
        # Bound queued work and reap before fallback/error return. Running file
        # checks finish normally; group cancellation belongs to the supervisor.
        pool.shutdown(wait=True, cancel_futures=True)
