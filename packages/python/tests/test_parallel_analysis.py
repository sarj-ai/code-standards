from __future__ import annotations

import ast
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import copy
import multiprocessing
from pathlib import Path
import shutil
import subprocess
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

import pytest
from sarj_rule_contracts import SourceCatalog

from sarj_python_lint import __main__ as engine
from sarj_python_lint.__main__ import analyze, main
import sarj_python_lint._parallel as parallel_engine
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._local_source import LocalSourceFacts
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.context import BaseContext

    from sarj_python_lint._analysis_session import AnalysisSession
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint._prepared_sources import PreparedSourceInputs, PreparedSourceSnapshot
    from sarj_python_lint.rules._project_index import ProjectSourceSnapshot


@final
class _RequestFacts(Rule):
    id = "parallel-quota-fixture"
    code = "TEST001"
    description = "Exercise native session quotas across real spawned workers."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        mode, *names = (line.removeprefix("# ") for line in context.source.splitlines())
        findings: list[Diagnostic] = []
        for name in names:
            path = context.path.parent / name
            facts = (
                LocalSourceFacts(source_inputs=context.session.source_inputs)
                if mode == "fresh"
                else context.session.local_source
            )
            found = (
                facts.read_module(path)
                if mode == "modules"
                else facts.resolve_module(context.path, Path(name).stem, 0, facts=context.session.first_party)
            )
            if found is not None:
                findings.append(Diagnostic(context.path, 1, 1, self.code, name))
        return findings


@final
class _SnapshotObserver(ProjectRule):
    id = "parallel-snapshot-fixture"
    code = "TEST002"
    description = "Observe an unselected dependency in the complete frozen graph."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        assert context.session.project is not None
        unit = context.session.project.unit(context.path.with_name("models.py"))
        assert unit is not None
        return [Diagnostic(context.path, 1, 1, self.code, unit.source)]


@final
class _BrokenInitializer(Rule):
    id = "parallel-initialization-fixture"
    code = "TEST003"
    description = "Fail native worker initialization."

    @override
    def prepare_session(self, session: AnalysisSession) -> None:
        super().prepare_session(session)
        msg = "fixture initialization failed"
        raise RuntimeError(msg)

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return []


@final
class _PreparationObserver(ProjectRule):
    id = "parallel-preparation-fixture"
    code = "TEST004"
    description = "Observe the same rule lifecycle in serial and spawned analysis."

    @override
    def prepare_session(self, session: AnalysisSession) -> None:
        assert session.project is None
        super().prepare_session(session)

    @override
    def prepare(self, indexes: ProjectIndexSet) -> None:
        assert self._analysis_session is not None
        assert self._analysis_session.project is indexes
        super().prepare(indexes)

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return [Diagnostic(context.path, 1, 1, self.code, "prepared")]


@final
class _FileFailure(Rule):
    id = "parallel-file-failure-fixture"
    code = "TEST005"
    description = "Fail one selected file while other files are queued."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.path.name == "failure.py":
            msg = "fixture file failed"
            raise RuntimeError(msg)
        return [Diagnostic(context.path, 1, 1, self.code, "completed")]


def test_spawned_rule_preparation_matches_serial_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the real registry lifecycle is under test; injecting prepared rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _PreparationObserver.id: _PreparationObserver}
    )
    paths = [tmp_path / name for name in ("first.py", "last.py")]
    for path in paths:
        path.write_text("class Record: pass\n")
    serial = analyze([_PreparationObserver.id], paths)
    assert len(serial) == 2
    assert analyze([_PreparationObserver.id], paths, jobs=2) == serial


def test_worker_initialization_failure_is_not_serial_success(tmp_path: Path) -> None:
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(BrokenProcessPool):
        parallel_engine.check_parallel(
            [_BrokenInitializer], {tmp_path / "first.py": "", tmp_path / "last.py": ""}, None, jobs=2
        )
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("failure_index", [0, 8])
def test_queued_file_failure_propagates_and_reaps_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_index: int
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the real registry must dispatch this rule in spawned workers.
        engine, "REGISTRY", {**REGISTRY, _FileFailure.id: _FileFailure}
    )
    paths = [tmp_path / ("failure.py" if index == failure_index else f"file_{index}.py") for index in range(17)]
    for path in paths:
        path.write_text("value = 1\n")
    before = {child.pid for child in multiprocessing.active_children()}
    for jobs in (1, 2):
        with pytest.raises(RuntimeError, match="fixture file failed"):
            analyze([_FileFailure.id], paths, jobs=jobs)
        assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("mode", ["resolutions", "modules"])
@pytest.mark.parametrize("requests", [511, 512, 513])
def test_parallel_native_quota_boundary_replays_untouched_serial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, requests: int
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the registry lookup is under test; injecting rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts}
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "0.1.0"\n')
    (tmp_path / "provider.py").write_text("value = 1\n")
    first, last = tmp_path / "first.py", tmp_path / "last.py"
    first.write_text(f"# {mode}\n" + "".join(f"# missing_{i}.py\n" for i in range(requests - 1)))
    last.write_text(f"# {mode}\n# provider.py\n")
    original = parallel_engine.check_parallel
    replayed: list[bool] = []

    def observe(
        rule_types: list[type[Rule]], loaded: dict[Path, str], project: ProjectIndexSet | None, *, jobs: int
    ) -> list[Diagnostic] | None:
        result = original(rule_types, loaded, project, jobs=jobs)
        replayed.append(result is None)
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe real replay; a fake pool would miss quota divergence.
        parallel_engine, "check_parallel", observe
    )
    before = {child.pid for child in multiprocessing.active_children()}
    expected = analyze([_RequestFacts.id], [first, last])
    actual = analyze([_RequestFacts.id], [first, last], jobs=2)
    assert actual == expected
    assert len(actual) == (1 if requests <= 512 else 0)
    assert replayed == [requests >= 512]
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("mode", ["resolutions", "modules"])
def test_quota_replay_keeps_later_worker_failure_visible(tmp_path: Path, mode: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "quota-failure"\nversion = "0.1.0"\n')
    first, failure = tmp_path / "first.py", tmp_path / "failure.py"
    first_source = f"# {mode}\n" + "".join(f"# missing_{index}.py\n" for index in range(512))
    failure_source = f"# {mode}\n"
    first.write_text(first_source)
    failure.write_text(failure_source)
    before = {child.pid for child in multiprocessing.active_children()}

    with pytest.raises(RuntimeError, match="fixture file failed"):
        parallel_engine.check_parallel(
            [_RequestFacts, _FileFailure], {first: first_source, failure: failure_source}, None, jobs=2
        )

    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("entrypoint", ["console", "module"])
def test_native_cli_workers_preserve_order_output_baselines_and_errors(tmp_path: Path, entrypoint: str) -> None:
    files = [tmp_path / name for name in ("z.py", "a.py")]
    for path in files:
        path.write_text('__all__ = ["value"]\nvalue = 1\n')
    if entrypoint == "console":
        console = shutil.which("sarj-python-lint")
        assert console is not None
        command = [console]
    else:
        command = [sys.executable, "-m", "sarj_python_lint"]
    arguments = ["check", "--rule", "no-dunder-all"]

    def run(jobs: int, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*command, *arguments, "--jobs", str(jobs), *extra, *(str(path) for path in files)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    serial, parallel = run(1), run(2)
    assert serial.returncode == parallel.returncode == 1
    assert serial.stdout == parallel.stdout
    assert not serial.stderr
    assert not parallel.stderr
    assert [line.split(":1:")[0] for line in parallel.stdout.splitlines()] == [str(path) for path in files]
    baseline = tmp_path / "baseline.json"
    assert run(2, "--update-baseline", str(baseline)).returncode == 0
    accepted = run(2, "--baseline", str(baseline))
    assert accepted.returncode == 0
    assert not accepted.stdout
    files[1].write_text("if broken ==\n")
    failed = run(2)
    assert failed.returncode == 2
    assert not failed.stdout
    assert "selected Python source could not be parsed" in failed.stderr


def test_default_analysis_stays_serial_and_rejects_invalid_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [tmp_path / name for name in ("first.py", "second.py")]
    for path in files:
        path.write_text("value = 1\n")

    def unexpected(
        _rule_types: list[type[Rule]], _loaded: dict[Path, str], _project: ProjectIndexSet | None, *, jobs: int
    ) -> None:
        pytest.fail(f"serial analysis created a worker pool with budget {jobs}")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the boundary to prove the public default never creates a pool.
        parallel_engine, "check_parallel", unexpected
    )
    assert analyze(["no-dunder-all"], files) == []
    assert main(["check", "--rule", "no-dunder-all", *(str(path) for path in files)]) == 0
    with pytest.raises(ValueError, match="jobs must be at least 1"):
        analyze(["no-dunder-all"], files, jobs=0)


def test_complete_project_snapshot_preserves_unselected_sources_and_module_identity(tmp_path: Path) -> None:
    projects = [tmp_path / name for name in ("first", "second")]
    selected: list[Path] = []
    for index, project in enumerate(projects):
        project.mkdir()
        (project / "pyproject.toml").write_text(f'[project]\nname = "sample{index}"\nversion = "0.1.0"\n')
        consumer = project / "consumer.py"
        consumer.write_text("from models import Record\n")
        selected.append(consumer)
        (project / "models.py").write_text(f"class Record:\n    field{index}: str\n")
    original = ProjectIndexSet.build(selected, {path: path.read_text() for path in selected})
    payload = original.source_snapshot()
    for project in projects:
        (project / "models.py").write_text("class Changed: pass\n")
        (project / "pyproject.toml").unlink()
    snapshot = ProjectIndexSet.from_source_snapshot(payload)
    for path in (*selected, *(project / "models.py" for project in projects)):
        before, after = original.unit(path), snapshot.unit(path)
        assert before is not None
        assert after is not None
        assert (after.path, after.module, after.source, after.imports) == (
            before.path,
            before.module,
            before.source,
            before.imports,
        )
        assert before.tree is not None
        assert after.tree is not None
        assert ast.dump(after.tree, include_attributes=True) == ast.dump(before.tree, include_attributes=True)
    findings = parallel_engine.check_parallel(
        [_SnapshotObserver], {path: path.read_text() for path in selected}, original, jobs=2
    )
    assert findings == [
        Diagnostic(path, 1, 1, _SnapshotObserver.code, f"class Record:\n    field{index}: str\n")
        for index, path in enumerate(selected)
    ]


@pytest.mark.parametrize("count", [512, 513])
@pytest.mark.parametrize("captured", [False, True])
def test_large_analysis_preserves_serial_quotas_source_order_and_late_errors_without_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, captured: bool
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the public registry lifecycle with native quota and failure rules.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts, _FileFailure.id: _FileFailure}
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname="large-analysis"\nversion="0.1.0"\n')
    provider = tmp_path / "provider.py"
    provider.write_text("value = 1\n")
    paths = [tmp_path / f"file_{index:04}.py" for index in reversed(range(count - 1))]
    paths.append(tmp_path / "failure.py")
    sources = SourceCatalog() if captured else None
    for path in paths:
        path.write_text("# resolutions\n# provider.py\n")
        if sources is not None:
            sources.capture(path)
            path.write_text("if broken ==\n")
    if sources is not None:
        sources.capture(provider)

    expected = analyze([_RequestFacts.id], paths, sources=sources)
    assert len(expected) == 512
    assert [diagnostic.path for diagnostic in expected] == paths[:512]

    def unexpected_pool(
        *,
        max_workers: int,
        mp_context: BaseContext,
        initializer: Callable[[list[type[Rule]], ProjectSourceSnapshot | None, PreparedSourceSnapshot | None], None],
        initargs: tuple[list[type[Rule]], ProjectSourceSnapshot | None, PreparedSourceSnapshot | None],
    ) -> None:
        pytest.fail(
            f"large analysis attempted {max_workers} {mp_context.get_start_method()} workers "
            f"with initializer {initializer!r} for {len(initargs[0])} rules before serial selection"
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe only the resource boundary; public analysis and real rules still execute unchanged.
        parallel_engine, "ProcessPoolExecutor", unexpected_pool
    )
    before = {child.pid for child in multiprocessing.active_children()}
    assert analyze([_RequestFacts.id], paths, jobs=2, sources=sources) == expected
    for jobs in (1, 2):
        with pytest.raises(RuntimeError, match="fixture file failed"):
            analyze([_RequestFacts.id, _FileFailure.id], paths, jobs=jobs, sources=sources)
    assert {child.pid for child in multiprocessing.active_children()} == before


def _write_saturating_analysis(tmp_path: Path, later: list[str]) -> list[Path]:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "frozen-cache"\nversion = "0.1.0"\n')
    (tmp_path / "provider.py").write_text("value = 1\n")
    first = tmp_path / "first.py"
    first.write_text("# resolutions\n" + "".join(f"# missing_{index}.py\n" for index in range(512)))
    rest = [tmp_path / f"file_{index:03}.py" for index in range(len(later))]
    for path, source in zip(rest, later, strict=True):
        path.write_text(source)
    return [first, *rest]


def _observe_frozen_handoffs(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    original = parallel_engine.check_parallel
    handoffs: list[bool] = []

    def observe(
        rule_types: list[type[Rule]],
        loaded: dict[Path, str],
        project: ProjectIndexSet | None,
        *,
        jobs: int,
        source_inputs: PreparedSourceInputs | None = None,
        frozen: parallel_engine.FrozenResolutions | None = None,
    ) -> list[Diagnostic] | None:
        result = original(rule_types, loaded, project, jobs=jobs, source_inputs=source_inputs, frozen=frozen)
        speculative_small_batch = frozen is None
        if not speculative_small_batch:
            handoffs.append(result is not None)
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the real handoff; a fake pool would miss quota divergence.
        parallel_engine, "check_parallel", observe
    )
    return handoffs


@pytest.mark.parametrize("later", ["resolutions", "modules"])
def test_saturated_resolution_cache_hands_remaining_files_to_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later: str
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the registry lookup is under test; injecting rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts}
    )
    paths = _write_saturating_analysis(tmp_path, [f"# {later}\n# provider.py\n"] * engine.FROZEN_HANDOFF_MIN_FILES)
    expected = analyze([_RequestFacts.id], paths)
    assert len(expected) == (0 if later == "resolutions" else engine.FROZEN_HANDOFF_MIN_FILES)
    handoffs = _observe_frozen_handoffs(monkeypatch)
    before = {child.pid for child in multiprocessing.active_children()}
    assert analyze([_RequestFacts.id], paths, jobs=3) == expected
    assert handoffs == [True]
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_frozen_handoff_replays_serially_when_modules_reach_their_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the registry lookup is under test; injecting rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts}
    )
    count = engine.FROZEN_HANDOFF_MIN_FILES
    later = [
        "# modules\n" + "".join(f"# absent_{index}_{item}.py\n" for item in range(512 // count + 1))
        for index in range(count)
    ]
    paths = _write_saturating_analysis(tmp_path, later)
    expected = analyze([_RequestFacts.id], paths)
    handoffs = _observe_frozen_handoffs(monkeypatch)
    assert analyze([_RequestFacts.id], paths, jobs=2) == expected
    assert handoffs == [False]


@pytest.mark.parametrize("later", ["# modules\n# first.py\n", "# fresh\n# provider.py\n"])
def test_frozen_handoff_uses_captured_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later: str) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the registry lookup is under test; injecting rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts}
    )
    paths = _write_saturating_analysis(tmp_path, [later] * engine.FROZEN_HANDOFF_MIN_FILES)
    sources = SourceCatalog()
    for path in paths:
        sources.capture(path)
    for path in paths:
        path.write_text("if broken ==\n")  # captured bytes must win over changed files
    expected = analyze([_RequestFacts.id], paths, sources=sources)
    assert len(expected) == engine.FROZEN_HANDOFF_MIN_FILES
    handoffs = _observe_frozen_handoffs(monkeypatch)
    assert analyze([_RequestFacts.id], paths, jobs=2, sources=sources) == expected
    assert handoffs == [True]


def test_small_remainder_after_saturation_stays_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the registry lookup is under test; injecting rules would bypass it.
        engine, "REGISTRY", {**REGISTRY, _RequestFacts.id: _RequestFacts}
    )
    paths = _write_saturating_analysis(tmp_path, ["# modules\n# provider.py\n"] * (engine.FROZEN_HANDOFF_MIN_FILES - 1))
    handoffs = _observe_frozen_handoffs(monkeypatch)
    assert analyze([_RequestFacts.id], paths, jobs=2) == analyze([_RequestFacts.id], paths)
    assert handoffs == []


def _index_units(sources: dict[str, str]) -> dict[Path, SourceUnit]:
    return {
        Path(name.replace(".", "/") + ".py"): SourceUnit(
            Path(name.replace(".", "/") + ".py"), name, source, ast.parse(source), MappingProxyType({})
        )
        for name, source in sources.items()
    }


def test_restored_project_facts_match_recomputed_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = {
        "app.models": "class Record:\n    pass\n\n\nclass Escaped:\n    pass\n",
        "app.focus": "import app.patch\nfrom app.models import Record\n\nvalue = Record()\n",
        "app.patch": "import psycopg as driver\nfrom app import models\n\nholder = models.Escaped\ndriver.Connection = object\n",
    }
    symbols = (SymbolRef("app.models", "Record"), SymbolRef("app.models", "Escaped"))
    warm = ProjectIndexSet(_index_units(sources), sealed=True)
    for unit in warm.source_units:
        warm.import_namespace_mutations.for_unit(unit)
        warm.constructor_consumers(unit, "Record")
    dynamic = [warm.nominal_membership_is_dynamic(symbol) for symbol in symbols]
    snapshot = warm.source_snapshot(with_facts=True)
    assert snapshot.facts is not None
    transferred = {name for name, _ in snapshot.facts.cached}
    assert transferred >= {"_escaped_nominal_classes", "_constructor_consumers"}

    with ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as pool:
        restored = ProjectIndexSet.from_source_snapshot(pool.submit(copy.copy, snapshot).result(), sealed=True)
    cold = ProjectIndexSet(_index_units(sources), sealed=True)
    for unit in cold.source_units:
        cold.import_namespace_mutations.for_unit(unit)
        cold.constructor_consumers(unit, "Record")
    assert [cold.nominal_membership_is_dynamic(symbol) for symbol in symbols] == dynamic
    restored_facts, cold_facts = dict[str, object](vars(restored)), dict[str, object](vars(cold))
    assert {name: restored_facts[name] for name in transferred} == {name: cold_facts[name] for name in transferred}
    assert [restored.nominal_membership_is_dynamic(symbol) for symbol in symbols] == dynamic
    for restored_unit, cold_unit in zip(restored.source_units, cold.source_units, strict=True):
        assert restored.import_namespace_mutations.for_unit(restored_unit) == cold.import_namespace_mutations.for_unit(
            cold_unit
        )
    assert ProjectIndexSet(_index_units(sources)).source_snapshot().facts is None

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- an exhausted value-origin budget is the order-dependent state under test.
        warm, "_value_origins_incomplete", True
    )
    assert not warm.value_origins_complete
    assert warm.source_snapshot(with_facts=True).facts is None
