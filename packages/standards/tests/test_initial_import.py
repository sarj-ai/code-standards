from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Unpack

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.diagnostics import baseline, initial_import
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.staged_git import staged_environment


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tests.call_contracts import NativeAnalyzeOptions


_ENV = "SARJ_STANDARDS_INITIAL_IMPORT_SOURCE"
_RULES = ["python:no-secret-in-log"]


@dataclass(frozen=True)
class ImportRepository:
    root: Path
    original: Path
    source: str
    parent: str


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=root, text=True).strip()


def _init(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Standards Test")
    _git(root, "config", "user.email", "standards@example.com")


@pytest.fixture
def imported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ImportRepository:
    monkeypatch.delenv(_ENV, raising=False)
    original = tmp_path / "original"
    _init(original)
    app = original / "app.py"
    app.write_text("logger.info('inherited', token=token)\nvalue = 1\n", encoding="utf-8")
    _git(original, "add", ".")
    _git(original, "commit", "-qm", "Inherited source")
    parent = _git(original, "rev-parse", "HEAD")
    app.write_text(
        "logger.info('inherited', token=token)\nvalue = 1\nlogger.info('introduced', token=token)\n", encoding="utf-8"
    )
    findings = api.Standards(original).analyze(["app.py"], mode=api.AnalysisMode.RAW, rules=_RULES)
    assert len(findings.diagnostics) == 2
    budget = original / "diagnostic-baseline.json"
    budget.write_text(
        baseline.render(
            findings.diagnostics,
            bundle_version=api.__version__,
            consumer_base_sha=parent,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        verify_paths=(".",),
        diagnostic_baseline=budget.name,
    )
    (original / MANIFEST_NAME).write_text(manifest.render(), encoding="utf-8")
    _git(original, "add", ".")
    _git(original, "commit", "-qm", "Qualified source delta")
    source = _git(original, "rev-parse", "HEAD")
    root = tmp_path / "imported"
    _init(root)
    _git(original, "checkout-index", "--all", f"--prefix={root}/")
    _git(root, "add", ".")
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(original / ".git" / "objects"))
    return ImportRepository(root, original, source, parent)


def test_initial_import_preserves_the_original_delta_and_new_debt(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_BASE", imported.parent)
    original = baseline.changed_line_scope(imported.original, staged=False)
    ordinary = baseline.changed_line_scope(imported.root, staged=True)
    ordinary_report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)
    assert ordinary is not None
    assert ordinary.lines["app.py"] == frozenset({1, 2, 3})
    assert len(ordinary_report.diagnostics) == 2
    assert sum(tool.baselined_count for tool in ordinary_report.tools) == 0
    monkeypatch.setenv(_ENV, imported.source)

    context = initial_import.load(imported.root, staged=True)
    scope = baseline.changed_line_scope(imported.root, staged=True)
    report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)

    assert context is not None
    assert context.parent == imported.parent
    assert scope == original
    assert scope is not None
    assert scope.lines["app.py"] == frozenset({3})
    assert report.issues == ()
    assert report.exit_code == 1
    assert [item.location.position.line for item in report.diagnostics if item.location.position is not None] == [2]
    assert sum(tool.baselined_count for tool in report.tools) == 1
    assert not (imported.root / ".git" / "objects" / imported.source[:2] / imported.source[2:]).exists()


@pytest.mark.parametrize("source", ["", "HEAD", "a" * 39, "A" * 40, "f" * 40])
def test_invalid_explicit_source_fails_even_a_clean_report(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.setenv(_ENV, source)
    report = api.Standards(imported.root).analyze([], staged=True, rules=_RULES)
    assert report.exit_code == 2
    assert [item.kind for item in report.issues] == ["invalid-input"]


@pytest.mark.parametrize(
    "source_kind", ["root", "merge", "tag", "blob", "missing-parent", "missing-parent-tree", "missing-parent-blob"]
)
def test_initial_import_requires_an_available_single_parent_commit(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, source_kind: str
) -> None:
    source = imported.source
    match source_kind:
        case "root":
            source = imported.parent
        case "merge":
            tree = _git(imported.original, "rev-parse", "HEAD^{tree}")
            source = _git(
                imported.original, "commit-tree", tree, "-p", imported.source, "-p", imported.parent, "-m", "Merge"
            )
        case "tag":
            _git(imported.original, "tag", "-a", "example", "-m", "Annotated tag")
            source = _git(imported.original, "rev-parse", "refs/tags/example")
        case "blob":
            source = _git(imported.original, "rev-parse", "HEAD:app.py")
        case _:
            missing = imported.parent
            match source_kind:
                case "missing-parent-tree":
                    missing = _git(imported.original, "rev-parse", f"{imported.parent}^{{tree}}")
                case "missing-parent-blob":
                    missing = _git(imported.original, "rev-parse", f"{imported.parent}:app.py")
                case _:
                    pass
            (imported.original / ".git" / "objects" / missing[:2] / missing[2:]).unlink()
    monkeypatch.setenv(_ENV, source)
    report = api.Standards(imported.root).analyze([], staged=True, rules=_RULES)
    assert report.exit_code == 2
    assert report.issues


@pytest.mark.parametrize(
    "state",
    ["existing-head", "corrupt-head", "detached-head", "index", "worktree", "mode", "untracked", "assume", "skip"],
)
def test_initial_import_rejects_unverifiable_repository_state(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    root = imported.root
    if state == "existing-head":
        _git(root, "commit", "-qm", "Existing history")
    elif state == "corrupt-head":
        (root / ".git" / "refs" / "heads").mkdir(exist_ok=True)
        branch = _git(root, "symbolic-ref", "--short", "HEAD")
        (root / ".git" / "refs" / "heads" / branch).write_text("f" * 40 + "\n", encoding="ascii")
    elif state == "detached-head":
        (root / ".git" / "HEAD").write_text("f" * 40 + "\n", encoding="ascii")
    elif state in {"index", "worktree"}:
        (root / "app.py").write_text("value = 2\n", encoding="utf-8")
        if state == "index":
            _git(root, "add", ".")
    elif state == "mode":
        _git(root, "config", "core.filemode", "false")
        (root / "app.py").chmod(0o755)
    elif state == "untracked":
        (root / "new.py").write_text("value = 2\n", encoding="utf-8")
    else:
        _git(root, "update-index", "--assume-unchanged" if state == "assume" else "--skip-worktree", "app.py")
    monkeypatch.setenv(_ENV, imported.source)
    report = api.Standards(root).analyze([], staged=True, rules=_RULES)
    assert report.exit_code == 2
    assert report.issues


def test_import_context_is_not_valid_for_nonstaged_analysis(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, imported.source)
    assert api.Standards(imported.root).analyze([], rules=_RULES).exit_code == 2


def test_initial_import_preserves_rename_and_non_ascii_line_attribution(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "résumé.py"
    _git(imported.original, "mv", "app.py", name)
    with (imported.original / name).open("a", encoding="utf-8") as app:
        app.write("value = 2\n")
    _git(imported.original, "add", ".")
    _git(imported.original, "commit", "-qm", "Rename and change one line")
    source = _git(imported.original, "rev-parse", "HEAD")
    (imported.root / "app.py").unlink()
    _git(imported.root, "read-tree", source)
    _git(imported.root, "checkout-index", "--all", "--force")
    monkeypatch.setenv(_ENV, source)

    scope = baseline.changed_line_scope(imported.root, staged=True, paths=(name,))

    assert scope is not None
    assert not scope.failed
    assert scope.paths == frozenset({name})
    assert scope.lines[name] == frozenset({4})


def test_initial_import_uses_actual_objects_despite_replacement_refs(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(imported.root, "replace", imported.source, imported.parent)
    monkeypatch.setenv(_ENV, imported.source)

    scope = baseline.changed_line_scope(imported.root, staged=True, paths=("app.py",))

    assert scope is not None
    assert not scope.failed
    assert scope.lines["app.py"] == frozenset({3})


def test_git_routing_cannot_validate_a_different_worktree(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = imported.root.parent / "decoy"
    _init(decoy)
    _git(decoy, "read-tree", imported.source)
    _git(decoy, "checkout-index", "--all")
    (imported.root / "app.py").write_text("value = 2\n", encoding="utf-8")
    monkeypatch.setenv(_ENV, imported.source)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_COMMON_DIR", str(decoy / ".git"))

    report = api.Standards(imported.root).analyze([], staged=True, rules=_RULES)

    assert report.exit_code == 2
    assert [item.kind for item in report.issues] == ["invalid-input"]


def test_initial_import_uses_the_prospective_index(imported: ImportRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    pending = imported.root / ".git" / "pending-index"
    pending.write_bytes((imported.root / ".git" / "index").read_bytes())
    _git(imported.root, "rm", "--cached", "app.py")
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending))
    monkeypatch.setenv(_ENV, imported.source)

    scope = baseline.changed_line_scope(imported.root, staged=True, paths=("app.py",))
    environment = staged_environment(imported.root)
    report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)

    assert scope is not None
    assert not scope.failed
    assert scope.lines["app.py"] == frozenset({3})
    assert environment["GIT_INDEX_FILE"] == str(pending)
    assert environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] == str(imported.original / ".git/objects")
    assert report.issues == ()
    assert report.exit_code == 1
    assert sum(tool.baselined_count for tool in report.tools) == 1


@pytest.mark.parametrize("index_kind", ["external", "symlink"])
def test_initial_import_does_not_authorize_an_unowned_index(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, index_kind: str
) -> None:
    index = imported.root / ".git/index"
    supplied = imported.root / ".git/pending-index"
    if index_kind == "external":
        supplied = imported.root.parent / "foreign-index"
        supplied.write_bytes(index.read_bytes())
    else:
        supplied.symlink_to(index)
    before = index.read_bytes(), supplied.read_bytes()
    monkeypatch.setenv(_ENV, imported.source)
    monkeypatch.setenv("GIT_INDEX_FILE", str(supplied))

    report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)
    scope = baseline.changed_line_scope(imported.root, staged=True, paths=("app.py",))

    assert report.exit_code == 2
    assert any("active Git index" in issue.message for issue in report.issues)
    assert scope is not None
    assert scope.failed
    assert (index.read_bytes(), supplied.read_bytes()) == before


@pytest.mark.parametrize("variable", ["GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_SHALLOW", "GIT_QUARANTINE_PATH"])
def test_initial_import_does_not_authorize_other_object_routing(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    pending = imported.root / ".git/pending-index"
    pending.write_bytes((imported.root / ".git/index").read_bytes())
    before = pending.read_bytes()
    monkeypatch.setenv(_ENV, imported.source)
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending))
    monkeypatch.setenv(variable, str(imported.original / ".git/objects"))

    report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)

    assert report.exit_code == 2
    assert any("unsupported object-store context" in issue.message for issue in report.issues)
    assert pending.read_bytes() == before


def test_initial_import_rejects_failed_scope_and_preserves_findings(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, imported.source)

    def failed_comparison(root: Path, *, staged: bool, paths: Iterable[str] | None = None) -> baseline.ChangedLineScope:
        assert root == imported.root
        assert staged
        assert paths is not None
        return baseline.ChangedLineScope(frozenset(paths), {}, failed=True)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- inject a transient diff failure after the real source context validated, while retaining real native analyzer findings.
        baseline, "changed_line_scope", failed_comparison
    )
    report = api.Standards(imported.root).analyze(["app.py"], staged=True, rules=_RULES)

    assert report.exit_code == 2
    assert len(report.diagnostics) == 2
    assert [item.kind for item in report.issues] == ["invalid-input"]


@pytest.mark.parametrize("mutation", ["worktree", "index", "environment"])
def test_initial_import_revalidates_after_native_analysis(
    imported: ImportRepository, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    monkeypatch.setenv(_ENV, imported.source)

    def mutate(paths: Sequence[str], **kwargs: Unpack[NativeAnalyzeOptions]) -> api.AnalysisReport:
        report = analyze(paths, **kwargs)
        if mutation == "environment":
            monkeypatch.delenv(_ENV)
        else:
            (imported.root / "app.py").write_text("value = 2\n", encoding="utf-8")
            if mutation == "index":
                _git(imported.root, "add", ".")
        return report

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- mutate actual Git/worktree state after the real native analyzer to verify the import transaction boundary.
        api, "analyze_paths", mutate
    )
    report = api.Standards(imported.root).analyze([], staged=True, rules=_RULES)
    assert report.exit_code == 2
    assert [item.kind for item in report.issues] == ["invalid-input"]
