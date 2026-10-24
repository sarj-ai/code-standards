from __future__ import annotations

import ast
from concurrent.futures.process import BrokenProcessPool
import multiprocessing
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, final, override

import pytest

from sarj_python_lint import __main__ as engine
from sarj_python_lint.__main__ import analyze, main
import sarj_python_lint._parallel as parallel_engine
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from sarj_python_lint._analysis_session import AnalysisSession
    from sarj_python_lint._file_context import PythonFileContext


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
            facts = context.session.local_source
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


@pytest.mark.parametrize("entrypoint", ["console", "module"])
def test_native_cli_workers_preserve_order_output_baselines_and_errors(tmp_path: Path, entrypoint: str) -> None:
    files = [tmp_path / name for name in ("z.py", "a.py")]
    for path in files:
        path.write_text('__all__ = ["value"]\nvalue = 1\n')
    command = (
        [str(Path(sys.executable).with_name("sarj-python-lint"))]
        if entrypoint == "console"
        else [sys.executable, "-m", "sarj_python_lint"]
    )
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
