from __future__ import annotations

import ast
import codecs
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from io import BufferedReader, FileIO
import multiprocessing
from pathlib import Path
from typing import TYPE_CHECKING, final, override

import pytest
from sarj_rule_contracts import SourceCatalog, SourceSnapshot

from sarj_python_lint import __main__ as engine
from sarj_python_lint._analysis_session import AnalysisSession
import sarj_python_lint._parallel as parallel_engine
from sarj_python_lint._prepared_sources import NeedsSerialSourceError, PreparedSourceInputs
from sarj_python_lint._source import python_source_encoding, read_python_source
from sarj_python_lint.rule_base import Diagnostic, ProjectRule, Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._local_source import LocalSourceFacts
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import IO

    from sarj_python_lint._file_context import PythonFileContext


@dataclass(frozen=True)
class PreparedFixture:
    catalog: SourceCatalog
    inputs: PreparedSourceInputs
    project: ProjectIndexSet
    loaded: dict[Path, str]


def prepare_sources(root: Path, raw: bytes = b"class Record: pass\n") -> PreparedFixture:
    (root / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0.0"\n')
    (root / "models.py").write_bytes(raw)
    selected = [root / name for name in ("first.py", "last.py")]
    for path in selected:
        path.write_text("from models import Record\n")
    catalog = SourceCatalog()
    inputs = PreparedSourceInputs(catalog)
    loaded: dict[Path, str] = {}
    for path in selected:
        loaded[path] = read_python_source(path, sources=catalog)
        inputs.remember_selected(path, catalog.capture(path))
    project = ProjectIndexSet.build(selected, loaded, source_inputs=inputs)
    return PreparedFixture(catalog, inputs, project, loaded)


class _ObservedReader(BufferedReader):
    def __init__(self, raw: FileIO, reads: list[int | None]) -> None:
        super().__init__(raw)
        self.reads = reads

    @override
    def read(self, size: int | None = -1, /) -> bytes:
        self.reads.append(size)
        return super().read(size)


def observe_binary_reads(
    target: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    before_open: Callable[[], None] | None = None,
) -> list[list[int | None]]:
    original_open = Path.open
    streams: list[list[int | None]] = []

    def observed_open(  # ruff: ignore[too-many-positional-arguments] -- Preserve pathlib.Path.open's six-argument positional and keyword protocol while observing bounded reads.
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[bytes] | IO[str]:
        if path != target or mode != "rb":
            return original_open(path, mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline)
        if before_open is not None:
            before_open()
        stream = original_open(path, "rb", buffering=0)
        assert isinstance(stream, FileIO)
        reads: list[int | None] = []
        streams.append(reads)
        return _ObservedReader(stream, reads)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- forward every real filesystem read and observe its actual bound.
        Path, "open", observed_open
    )
    return streams


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "latin-1", "cp1252"])
def test_project_and_local_share_one_capture_with_distinct_decoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
    encoding: str,
) -> None:
    model = tmp_path / "models.py"
    streams = observe_binary_reads(model, monkeypatch)
    text = (
        f"# coding: {encoding}\n"
        "from typing import TYPE_CHECKING\n"
        "from runtime import Record as RuntimeRecord\n"
        "if TYPE_CHECKING:\n    from typed import Record as TypedRecord\n"
        "def nested():\n    from nested import Record as NestedRecord\n"
        "class Café: pass\n"
    ).replace("\n", ending)
    raw = text.encode(encoding)
    prepared = prepare_sources(tmp_path, raw)
    unit = prepared.project.unit(model)
    local = LocalSourceFacts(source_inputs=prepared.inputs).read_module(model)

    assert unit is not None
    assert local is not None
    assert local.source == text == raw.decode(python_source_encoding(raw))
    assert unit.source == text.replace("\r\n", "\n").replace("\r", "\n")
    assert "TypedRecord" in unit.imports
    assert "RuntimeRecord" in local.runtime_imports.bindings
    assert "TypedRecord" not in local.runtime_imports.bindings
    assert "NestedRecord" not in local.runtime_imports.bindings
    assert len(streams) == 1
    assert streams[0] == [500_001]
    assert unit.captured is not None
    assert unit.captured.snapshot is prepared.inputs.module_snapshot(model)


@pytest.mark.parametrize("raw_size", [256_000, 256_001])
def test_local_raw_limit_uses_exact_prepared_bytes_without_rereading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_size: int,
) -> None:
    prefix = b"class Record: pass\n# "
    raw = prefix + b"x" * (raw_size - len(prefix))
    prepared = prepare_sources(tmp_path, raw)
    model = tmp_path / "models.py"
    streams = observe_binary_reads(model, monkeypatch)
    model.unlink()
    local = LocalSourceFacts(source_inputs=prepared.inputs).read_module(model)

    assert (local is not None) == (raw_size == 256_000)
    assert streams == []
    unit = prepared.project.unit(model)
    assert unit is not None
    assert unit.captured is not None
    assert unit.captured.raw_size == raw_size
    wire = prepared.project.source_snapshot()
    transported = next(item for item in wire.units if item.path == model)
    assert (transported.source is None) == (raw_size == 256_000)
    assert (transported.captured is not None and transported.captured.snapshot is not None) == (raw_size == 256_000)


def test_multibyte_character_count_cannot_bypass_local_raw_limit(tmp_path: Path) -> None:
    raw = ("class Record: pass\n# " + "🌱" * 64_000).encode()
    assert len(raw) > 256_000
    prepared = prepare_sources(tmp_path, raw)
    unit = prepared.project.unit(tmp_path / "models.py")
    assert unit is not None
    assert len(unit.source) < 256_000
    assert LocalSourceFacts(source_inputs=prepared.inputs).read_module(unit.path) is None


def test_growth_after_metadata_check_keeps_project_read_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "growing.py"
    target.write_bytes(b"class Record: pass\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0.0"\n')
    consumer = tmp_path / "consumer.py"
    consumer.write_text("import growing\n")

    def grow_before_open() -> None:
        target.write_bytes(b"# " + b"x" * 500_001)

    # The production reader opens this stream only after checking real metadata.
    streams = observe_binary_reads(target, monkeypatch, before_open=grow_before_open)
    inputs = PreparedSourceInputs()
    project = ProjectIndexSet.build([consumer], {consumer: "import growing\n"}, source_inputs=inputs)
    assert project.unit(target) is None
    assert target.stat().st_size == 500_003
    assert len(streams) == 1
    assert streams[0] == [500_001]
    assert inputs.source_snapshot().entries == ()


@pytest.mark.parametrize(
    "raw",
    [b"# coding: unknown-codec\nclass Record: pass\n", b"class Record:\n  broken = '\xff'\n", b"class :\n"],
)
def test_failed_local_reads_consume_budget_without_retaining_raw(tmp_path: Path, raw: bytes) -> None:
    target = tmp_path / "bad.py"
    target.write_bytes(raw)
    inputs = PreparedSourceInputs()
    facts = LocalSourceFacts(source_inputs=inputs)
    assert facts.read_module(target) is None
    target.write_text("class Replaced: pass\n")
    assert facts.read_module(target) is None
    assert facts.cache_keys().modules == frozenset({target})
    payload = inputs.source_snapshot()
    assert payload.entries == ()
    assert payload.failed_modules == frozenset({target})
    sealed = LocalSourceFacts(source_inputs=PreparedSourceInputs.from_source_snapshot(payload))
    assert sealed.read_module(target) is None
    assert sealed.cache_keys() == facts.cache_keys()


def test_non_candidate_helper_is_unprepared_and_uses_local_bounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_bytes(b"answer = 1\r\n")
    prepared = prepare_sources(tmp_path)
    assert prepared.project.unit(helper) is None
    assert prepared.inputs.project_snapshot(helper) is None
    sealed = PreparedSourceInputs.from_source_snapshot(prepared.inputs.source_snapshot())
    with pytest.raises(NeedsSerialSourceError):
        LocalSourceFacts(source_inputs=sealed).read_module(helper)
    streams = observe_binary_reads(helper, monkeypatch)
    module = LocalSourceFacts(source_inputs=prepared.inputs).read_module(helper)
    assert module is not None
    assert module.source == "answer = 1\r\n"
    assert streams[0] == [256_001]


def test_prepared_local_import_facts_preserve_existing_shadowing_profile(tmp_path: Path) -> None:
    raw = (
        b"from service import Record as Local\nLocal = object()\n"
        b"if True:\n    from conditional import Record as Conditional\n"
        b"class Container:\n    from nested import Record as Nested\n"
    )
    prepared = prepare_sources(tmp_path, raw)
    model = tmp_path / "models.py"
    original = LocalSourceFacts().read_module(model)
    captured = LocalSourceFacts(source_inputs=prepared.inputs).read_module(model)
    assert original is not None
    assert captured is not None
    assert captured.runtime_imports == original.runtime_imports
    assert ast.dump(captured.tree, include_attributes=True) == ast.dump(original.tree, include_attributes=True)


def test_explicit_relative_alias_preserves_catalog_key_and_wire_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = Path("model.py")
    path.write_bytes(codecs.BOM_UTF8 + b"class Record: pass\r\n")
    catalog = SourceCatalog()
    loaded = {path: read_python_source(path, sources=catalog)}
    inputs = PreparedSourceInputs(catalog)
    captured = catalog.capture(path)
    inputs.remember_selected(path, captured)
    project = ProjectIndexSet.build([path], loaded, source_inputs=inputs)
    absolute = path.resolve()
    assert catalog.get(absolute) is None
    assert captured.path == path
    unit = project.unit(path)
    assert unit is not None
    assert unit.path == absolute
    assert inputs.module_snapshot(absolute) is captured
    wire = project.source_snapshot()
    path.unlink()
    restored = ProjectIndexSet.from_source_snapshot(wire, sealed=True)
    after = restored.unit(path)
    assert after is not None
    assert after is restored.unit(absolute)
    assert (after.path, after.module, after.source, after.imports) == (
        unit.path,
        unit.module,
        unit.source,
        unit.imports,
    )
    assert after.tree is not None
    assert unit.tree is not None
    assert ast.dump(after.tree, include_attributes=True) == ast.dump(unit.tree, include_attributes=True)
    assert wire.aliases == ((path, absolute),)


def test_conflicting_alias_revisions_keep_last_project_winner_and_force_local_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative, absolute = Path("model.py"), tmp_path / "model.py"
    relative.write_bytes(b"class Earlier: pass\n")
    catalog = SourceCatalog()
    first = read_python_source(relative, sources=catalog)
    relative.write_bytes(b"class Later: pass\n")
    last = read_python_source(absolute, sources=catalog)
    inputs = PreparedSourceInputs(catalog)
    for path in (relative, absolute):
        inputs.remember_selected(path, catalog.capture(path))
    project = ProjectIndexSet.build([relative, absolute], {relative: first, absolute: last}, source_inputs=inputs)
    unit = project.unit(relative)
    assert unit is not None
    assert unit.source == last
    assert catalog.capture(relative).raw != catalog.capture(absolute).raw
    payload = inputs.source_snapshot()
    assert absolute in payload.conflicts
    assert payload.eligible_raw_count == 2
    sealed = PreparedSourceInputs.from_source_snapshot(payload)
    assert sealed.selected_text(relative) == first
    assert sealed.selected_text(absolute) == last
    with pytest.raises(NeedsSerialSourceError):
        LocalSourceFacts(source_inputs=sealed).read_module(absolute)
    absolute.write_text("class Live: pass\n")
    local = LocalSourceFacts(source_inputs=inputs).read_module(absolute)
    assert local is not None
    assert local.source == "class Live: pass\n"


@pytest.mark.parametrize("boundary", ["ambiguous-src", "package", "symlink", "nested-git", "dotdot"])
def test_prepared_bytes_never_bypass_original_resolution_policy(tmp_path: Path, boundary: str) -> None:
    prepared = prepare_sources(tmp_path)
    consumer = next(iter(prepared.loaded))
    model = tmp_path / "models.py"
    match boundary:
        case "ambiguous-src":
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "models.py").write_text("class Shadow: pass\n")
        case "package":
            (tmp_path / "models").mkdir()
            (tmp_path / "models" / "__init__.py").write_text("class Shadow: pass\n")
        case "symlink":
            model.rename(tmp_path / "original.py")
            model.symlink_to(tmp_path / "original.py")
        case "nested-git":
            nested = tmp_path / "nested"
            nested.mkdir()
            (nested / ".git").mkdir()
            consumer = nested / "consumer.py"
            consumer.write_text("from models import Record\n")
        case _:
            consumer = tmp_path / "nested" / ".." / consumer.name
    facts = LocalSourceFacts(source_inputs=prepared.inputs)
    assert facts.resolve_module(consumer, "models", 0, facts=FirstPartyFacts()) is None
    sealed = LocalSourceFacts(
        source_inputs=PreparedSourceInputs.from_source_snapshot(prepared.inputs.source_snapshot())
    )
    assert sealed.resolve_module(consumer, "models", 0, facts=FirstPartyFacts()) is None


@pytest.mark.parametrize("requests", [511, 512, 513])
def test_raw_preloading_does_not_preconsume_ordered_module_budget(tmp_path: Path, requests: int) -> None:
    provider = tmp_path / "provider.py"
    inputs = PreparedSourceInputs()
    inputs.remember_selected(provider, SourceSnapshot(provider, b"class Record: pass\n"))
    facts = LocalSourceFacts(source_inputs=inputs)
    assert facts.cache_keys().modules == frozenset()
    for index in range(requests - 1):
        assert facts.read_module(tmp_path / f"missing_{index}.py") is None
    module = facts.read_module(provider)
    assert (module is not None) == (requests <= 512)
    assert len(facts.cache_keys().modules) == min(requests, 512)
    if module is not None:
        assert module.source == "class Record: pass\n"


@final
class _PreparedReader(ProjectRule):
    id = "prepared-byte-reader-fixture"
    code = "TEST201"
    description = "Observe raw dependency bytes and the complete prepared graph in a real worker."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        project = context.session.project
        assert project is not None
        model = context.path.with_name("models.py")
        local = context.session.local_source.read_module(model)
        unit = project.unit(model)
        dynamic = project.unit(model.with_name("customization.py"))
        assert local is not None
        assert unit is not None
        assert dynamic is not None
        return [Diagnostic(context.path, 1, 1, self.code, f"{local.source}|{unit.source}|{dynamic.source}")]


@final
class _UnpreparedReader(ProjectRule):
    id = "unprepared-byte-reader-fixture"
    code = "TEST202"
    description = "Exercise real serial replay for an unprepared local helper."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        module = context.session.local_source.read_module(context.path.with_name("helper.py"))
        return [Diagnostic(context.path, 1, 1, self.code, "missing" if module is None else module.source)]


@final
class _PreparationNeedsSource(Rule):
    id = "prepared-initializer-fixture"
    code = "TEST203"
    description = "Request unknown local source while a sealed worker prepares."

    @override
    def prepare_session(self, session: AnalysisSession) -> None:
        super().prepare_session(session)
        session.local_source.read_module(Path("unprepared-initializer.py"))

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return []


@final
class _PreparationFailure(Rule):
    id = "prepared-initializer-failure-fixture"
    code = "TEST204"
    description = "Keep genuine initializer failures distinct from missing prepared input."

    @override
    def prepare_session(self, session: AnalysisSession) -> None:
        super().prepare_session(session)
        msg = "genuine prepared initializer failure"
        raise RuntimeError(msg)

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return []


@final
class _PreparedFileFailure(Rule):
    id = "prepared-file-failure-fixture"
    code = "TEST208"
    description = "Propagate genuine file failures from sealed workers."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        msg = "genuine prepared file failure"
        raise RuntimeError(msg)


@final
class _PreparedCancellation(Rule):
    id = "prepared-cancellation-fixture"
    code = "TEST209"
    description = "Preserve cancellation exceptions through real worker futures."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        raise KeyboardInterrupt


@final
class _PreparedQuota(Rule):
    id = "prepared-quota-fixture"
    code = "TEST205"
    description = "Exercise ordered native cache budgets against frozen raw and resolution receipts."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        mode, *names = (line.removeprefix("# ") for line in context.source.splitlines())
        diagnostics: list[Diagnostic] = []
        facts = context.session.local_source
        for name in names:
            found = (
                facts.read_module(context.path.with_name(name))
                if mode == "modules"
                else facts.resolve_module(context.path, Path(name).stem, 0, facts=context.session.first_party)
            )
            if found is not None:
                diagnostics.append(Diagnostic(context.path, 1, 1, self.code, name))
        return diagnostics


@final
class _AliasObserver(ProjectRule):
    id = "prepared-alias-fixture"
    code = "TEST206"
    description = "Observe distinct selected alias views and the existing last project assignment."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        assert context.session.project is not None
        unit = context.session.project.unit(context.path)
        assert unit is not None
        return [Diagnostic(context.path, 1, 1, self.code, f"{context.source}|{unit.source}")]


@final
class _ResolutionObserver(ProjectRule):
    id = "prepared-resolution-fixture"
    code = "TEST207"
    description = "Avoid treating prepared byte inventory as live import-resolution proof."

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        local = context.session.local_source
        resolved = local.resolve_module(context.path, "models", 0, facts=context.session.first_party)
        module = None if resolved is None else local.read_module(resolved)
        return [Diagnostic(context.path, 1, 1, self.code, "missing" if module is None else module.source)]


def test_real_spawn_preserves_conflicting_selected_alias_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative, absolute = Path("model.py"), tmp_path / "model.py"
    relative.write_text("class Earlier: pass\n", encoding="utf-8")
    catalog = SourceCatalog()
    catalog.capture(relative)
    relative.write_text("class Later: pass\n", encoding="utf-8")
    catalog.capture(absolute)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the real native entrypoint must prepare and serialize alias associations.
        engine, "REGISTRY", {**REGISTRY, _AliasObserver.id: _AliasObserver}
    )
    before = {child.pid for child in multiprocessing.active_children()}
    serial = engine.analyze([_AliasObserver.id], [relative, absolute], sources=catalog)
    actual = engine.analyze([_AliasObserver.id], [relative, absolute], jobs=2, sources=catalog)
    assert actual == serial
    assert [finding.message for finding in actual] == [
        "class Earlier: pass\n|class Later: pass\n",
        "class Later: pass\n|class Later: pass\n",
    ]
    assert catalog.get(relative) is not catalog.get(absolute)
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("mutation", ["replace", "delete"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "latin-1", "cp1252"])
def test_real_spawn_uses_exact_raw_inputs_and_complete_graph_after_mutation(
    tmp_path: Path,
    mutation: str,
    encoding: str,
) -> None:
    customization = tmp_path / "customization.py"
    dynamic_source = "from models import Record\nRecord.changed = True\n"
    customization.write_text(dynamic_source)
    physical = f"# coding: {encoding}\r\nclass Café: pass\r\n"
    prepared = prepare_sources(tmp_path, physical.encode(encoding))
    original_wire = prepared.project.source_snapshot()
    serial_session = AnalysisSession(source_inputs=prepared.inputs)
    serial_session.project = prepared.project
    serial_rule = _PreparedReader()
    serial_rule.prepare_session(serial_session)
    serial_rule.prepare(prepared.project)
    serial = [
        diagnostic
        for path, text in prepared.loaded.items()
        for diagnostic in engine.check_source([serial_rule], path, text, session=serial_session)
    ]
    for path in (*prepared.loaded, tmp_path / "models.py", customization, tmp_path / "pyproject.toml"):
        if mutation == "delete":
            path.unlink()
        else:
            path.write_text("class Replacement: pass\n")
    before = {child.pid for child in multiprocessing.active_children()}
    actual = parallel_engine.check_parallel(
        [_PreparedReader],
        prepared.loaded,
        prepared.project,
        jobs=2,
        source_inputs=prepared.inputs,
    )
    assert actual == serial
    assert [finding.message for finding in actual or []] == [
        f"{physical}|{physical.replace(chr(13), '')}|{dynamic_source}"
    ] * 2
    assert {child.pid for child in multiprocessing.active_children()} == before
    restored = ProjectIndexSet.from_source_snapshot(original_wire, sealed=True)
    assert [(unit.key, unit.module) for unit in restored.source_snapshot().units] == [
        (unit.key, unit.module) for unit in original_wire.units
    ]


@pytest.mark.parametrize("mutation", ["addition", "replacement", "deletion"])
def test_unknown_worker_input_replays_and_reaps_before_parent_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    helper = tmp_path / "helper.py"
    if mutation != "addition":
        helper.write_text("value = 'before'\n")
    prepare_sources(tmp_path)
    paths = [tmp_path / name for name in ("first.py", "last.py")]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- use real registry dispatch and spawned rule instances.
        engine, "REGISTRY", {**REGISTRY, _UnpreparedReader.id: _UnpreparedReader}
    )
    original = parallel_engine.check_parallel
    replays: list[bool] = []
    before = {child.pid for child in multiprocessing.active_children()}

    def observe(
        rule_types: list[type[Rule]],
        loaded: dict[Path, str],
        project: ProjectIndexSet | None,
        *,
        jobs: int,
        source_inputs: PreparedSourceInputs | None = None,
    ) -> list[Diagnostic] | None:
        if mutation == "deletion":
            helper.unlink()
        else:
            helper.write_text("value = 'after'\n")
        result = original(rule_types, loaded, project, jobs=jobs, source_inputs=source_inputs)
        replays.append(result is None)
        assert {child.pid for child in multiprocessing.active_children()} == before
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- forward the real pool and mutate only after project preparation.
        parallel_engine, "check_parallel", observe
    )
    actual = engine.analyze([_UnpreparedReader.id], paths, jobs=2, sources=SourceCatalog())
    assert replays == [True]
    expected_message = "missing" if mutation == "deletion" else "value = 'after'\n"
    assert [diagnostic.message for diagnostic in actual] == [expected_message] * 2
    assert engine.analyze([_UnpreparedReader.id], paths, sources=SourceCatalog()) == actual


@pytest.mark.parametrize("mutation", ["shadow", "delete"])
def test_new_worker_resolution_replays_instead_of_inferring_presence_from_raw_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    prepared = prepare_sources(tmp_path)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the actual resolver through native spawned dispatch.
        engine, "REGISTRY", {**REGISTRY, _ResolutionObserver.id: _ResolutionObserver}
    )
    original = parallel_engine.check_parallel
    before = {child.pid for child in multiprocessing.active_children()}
    replays: list[bool] = []

    def observe(
        rule_types: list[type[Rule]],
        loaded: dict[Path, str],
        project: ProjectIndexSet | None,
        *,
        jobs: int,
        source_inputs: PreparedSourceInputs | None = None,
    ) -> list[Diagnostic] | None:
        if mutation == "delete":
            (tmp_path / "models.py").unlink()
        else:
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "models.py").write_text("class Shadow: pass\n")
        result = original(rule_types, loaded, project, jobs=jobs, source_inputs=source_inputs)
        replays.append(result is None)
        assert {child.pid for child in multiprocessing.active_children()} == before
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- forward real execution after a namespace mutation at the worker boundary.
        parallel_engine, "check_parallel", observe
    )
    actual = engine.analyze([_ResolutionObserver.id], list(prepared.loaded), jobs=2, sources=SourceCatalog())
    assert replays == [True]
    assert [finding.message for finding in actual] == ["missing", "missing"]
    assert engine.analyze([_ResolutionObserver.id], list(prepared.loaded), sources=SourceCatalog()) == actual


def test_only_private_initializer_signal_requests_serial_replay(tmp_path: Path) -> None:
    prepared = prepare_sources(tmp_path)
    before = {child.pid for child in multiprocessing.active_children()}
    assert (
        parallel_engine.check_parallel(
            [_PreparationNeedsSource],
            prepared.loaded,
            prepared.project,
            jobs=2,
            source_inputs=prepared.inputs,
        )
        is None
    )
    assert {child.pid for child in multiprocessing.active_children()} == before
    with pytest.raises(BrokenProcessPool):
        parallel_engine.check_parallel(
            [_PreparationFailure],
            prepared.loaded,
            prepared.project,
            jobs=2,
            source_inputs=prepared.inputs,
        )
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize(
    ("rule_type", "error"),
    [(_PreparedFileFailure, RuntimeError), (_PreparedCancellation, KeyboardInterrupt)],
)
def test_genuine_worker_failure_and_cancellation_propagate_and_reap(
    tmp_path: Path,
    rule_type: type[Rule],
    error: type[BaseException],
) -> None:
    prepared = prepare_sources(tmp_path)
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(error):
        parallel_engine.check_parallel(
            [rule_type],
            prepared.loaded,
            prepared.project,
            jobs=2,
            source_inputs=prepared.inputs,
        )
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_parent_only_codec_requests_serial_during_worker_graph_reconstruction(tmp_path: Path) -> None:
    def fixture_codec(name: str) -> codecs.CodecInfo | None:
        return codecs.lookup("latin-1") if name in {"prepared-fixture", "prepared_fixture"} else None

    codecs.register(fixture_codec)
    try:
        prepared = prepare_sources(tmp_path, "# coding: prepared-fixture\nclass Café: pass\n".encode("latin-1"))
        before = {child.pid for child in multiprocessing.active_children()}
        assert (
            parallel_engine.check_parallel(
                [],
                prepared.loaded,
                prepared.project,
                jobs=2,
                source_inputs=prepared.inputs,
            )
            is None
        )
        assert {child.pid for child in multiprocessing.active_children()} == before
        unit = prepared.project.unit(tmp_path / "models.py")
        assert unit is not None
        assert "Café" in unit.source
    finally:
        codecs.unregister(fixture_codec)


def test_parent_admitted_non_candidate_codec_requests_real_worker_replay(tmp_path: Path) -> None:
    def fixture_codec(name: str) -> codecs.CodecInfo | None:
        return codecs.lookup("latin-1") if name in {"prepared-fixture", "prepared_fixture"} else None

    codecs.register(fixture_codec)
    try:
        helper = tmp_path / "helper.py"
        physical = "# coding: prepared-fixture\nvalue = 'Café'\r\n"
        helper.write_bytes(physical.encode("latin-1"))
        prepared = prepare_sources(tmp_path)
        assert prepared.project.unit(helper) is None
        assert prepared.inputs.project_snapshot(helper) is None
        admitted = LocalSourceFacts(source_inputs=prepared.inputs).read_module(helper)
        assert admitted is not None
        assert admitted.source == physical
        assert prepared.inputs.module_snapshot(helper) is not None
        assert prepared.inputs.source_snapshot().eligible_raw_count == 4
        parent = AnalysisSession(source_inputs=prepared.inputs)
        rule = _UnpreparedReader()
        rule.prepare_session(parent)
        parent.project = prepared.project
        rule.prepare(prepared.project)
        assert not parent.local_source.cache_keys().modules
        before = {child.pid for child in multiprocessing.active_children()}

        result = parallel_engine.check_parallel(
            [_UnpreparedReader],
            prepared.loaded,
            prepared.project,
            jobs=2,
            source_inputs=prepared.inputs,
        )

        assert result is None
        assert {child.pid for child in multiprocessing.active_children()} == before
        assert not parent.local_source.cache_keys().modules
        replayed = [
            diagnostic
            for path, text in prepared.loaded.items()
            for diagnostic in engine.check_source([rule], path, text, session=parent)
        ]
        assert replayed == [Diagnostic(path, 1, 1, rule.code, physical) for path in prepared.loaded]
        assert parent.local_source.cache_keys().modules == frozenset({helper})
    finally:
        codecs.unregister(fixture_codec)


def test_known_malformed_module_remains_ordinary_failure_in_real_spawn(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_bytes(b"class :\n")
    prepared = prepare_sources(tmp_path)
    unit = prepared.project.unit(helper)
    assert unit is not None
    assert unit.tree is None
    sealed = LocalSourceFacts(
        source_inputs=PreparedSourceInputs.from_source_snapshot(prepared.inputs.source_snapshot())
    )
    assert sealed.read_module(helper) is None
    assert sealed.cache_keys().modules == frozenset({helper})
    before = {child.pid for child in multiprocessing.active_children()}

    result = parallel_engine.check_parallel(
        [_UnpreparedReader],
        prepared.loaded,
        prepared.project,
        jobs=2,
        source_inputs=prepared.inputs,
    )

    assert result == [Diagnostic(path, 1, 1, _UnpreparedReader.code, "missing") for path in prepared.loaded]
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("mode", ["modules", "resolutions"])
@pytest.mark.parametrize("requests", [511, 512, 513])
def test_real_prepared_spawn_preserves_success_and_failure_quota_boundaries(
    tmp_path: Path,
    mode: str,
    requests: int,
) -> None:
    prepared = prepare_sources(tmp_path)
    first, last = prepared.loaded
    first.write_text(f"# {mode}\n" + "".join(f"# missing_{index}.py\n" for index in range(requests - 1)))
    last.write_text(f"# {mode}\n# models.py\n")
    catalog = SourceCatalog()
    inputs = PreparedSourceInputs(catalog)
    loaded: dict[Path, str] = {}
    for path in (first, last):
        loaded[path] = read_python_source(path, sources=catalog)
        inputs.remember_selected(path, catalog.capture(path))
    # Observe fixture receipts using the real parent reader/resolver; none of
    # these semantic caches is transported or reused by the analysis sessions.
    observed = LocalSourceFacts(source_inputs=inputs)
    if mode == "modules":
        assert observed.read_module(tmp_path / "models.py") is not None
        observed = LocalSourceFacts(source_inputs=inputs)
        for index in range(requests - 1):
            assert observed.read_module(tmp_path / f"missing_{index}.py") is None
    else:
        for index in range(requests - 1):
            assert observed.resolve_module(first, f"missing_{index}", 0, facts=FirstPartyFacts()) is None
        assert (
            LocalSourceFacts(source_inputs=inputs).resolve_module(
                last,
                "models",
                0,
                facts=FirstPartyFacts(),
            )
            is not None
        )
    parent = AnalysisSession(source_inputs=inputs)
    assert not parent.local_source.cache_keys().modules
    assert not parent.local_source.cache_keys().resolutions
    rule = _PreparedQuota()
    rule.prepare_session(parent)
    expected = [
        diagnostic
        for path, text in loaded.items()
        for diagnostic in engine.check_source([rule], path, text, session=parent)
    ]
    before = {child.pid for child in multiprocessing.active_children()}
    result = parallel_engine.check_parallel([_PreparedQuota], loaded, None, jobs=2, source_inputs=inputs)
    assert (result is None) == (requests >= 512)
    if result is not None:
        assert result == expected
    assert len(expected) == (1 if requests <= 512 else 0)
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("raw_count", [511, 512, 513])
def test_raw_fanout_gate_keeps_complete_semantic_inventory(tmp_path: Path, raw_count: int) -> None:
    prepared = prepare_sources(tmp_path)
    for index in range(raw_count - 3):
        target = tmp_path / f"extra_{index}.py"
        target.write_text(f"class Record{index}: pass\n")
    project = ProjectIndexSet.build(list(prepared.loaded), prepared.loaded, source_inputs=prepared.inputs)
    payload = prepared.inputs.source_snapshot()
    assert payload.eligible_raw_count == raw_count
    assert len(project.source_snapshot().units) == raw_count
    assert payload.raw_bytes == sum(len(path.read_bytes()) for path in tmp_path.iterdir() if path.suffix == ".py")
    before = {child.pid for child in multiprocessing.active_children()}
    # Empty rule sets still launch the real pool below the boundary. The gate
    # returns None before spawn at/above it without trimming any project unit.
    result = parallel_engine.check_parallel([], prepared.loaded, project, jobs=2, source_inputs=prepared.inputs)
    assert result == ([] if raw_count == 511 else None)
    assert len(project.source_snapshot().units) == raw_count
    assert {child.pid for child in multiprocessing.active_children()} == before
