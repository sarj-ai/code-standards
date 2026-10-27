from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.external import ProcessOutput, run_process
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Sequence


def _git(root: Path, *args: str) -> str:
    output = run_process(("git", *args), cwd=root)
    assert output.returncode == 0, output.stderr
    return output.stdout.strip()


@dataclass(frozen=True)
class _Workspace:
    root: Path
    base: str


@pytest.fixture(scope="module")
def workspace_seed(tmp_path_factory: pytest.TempPathFactory) -> _Workspace:
    root = tmp_path_factory.mktemp("react-doctor-workspace-seed")
    # run_process strips inherited GIT_* routing before function autouse fixtures run.
    _git(root, "init", "--template=", "--initial-branch=main")
    _git(root, "config", "user.name", "Scope test")
    _git(root, "config", "user.email", "scope@example.com")
    for name in ("app", "engineering", "qa", "ai-dashboard"):
        project = root / "packages" / name
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"dependencies":{"react":"19.2.8"}}\n', encoding="utf-8")
        (project / "view.tsx").write_text("export const View = () => <div />;\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Initial workspaces")
    return _Workspace(root=root, base=_git(root, "rev-parse", "HEAD"))


@pytest.fixture
def workspace(workspace_seed: _Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Workspace:
    shutil.copytree(workspace_seed.root, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("SARJ_STANDARDS_BASE", workspace_seed.base)
    return _Workspace(root=tmp_path, base=workspace_seed.base)


def test_workspace_copy_keeps_seed_git_state_independent(workspace: _Workspace, workspace_seed: _Workspace) -> None:
    root = workspace.root
    assert (root / ".git").is_dir()
    assert not (root / ".git").is_symlink()
    assert not (root / ".git/objects/info/alternates").exists()
    assert not _git(root, "status", "--porcelain")
    original_config = (workspace_seed.root / ".git/config").read_bytes()
    _git(root, "config", "scope.private", "copy")
    _git(root, "checkout", "-b", "private-copy")
    _change(root, ("app",), staged=True)
    assert _git(root, "diff", "--cached", "--name-only") == "packages/app/view.tsx"
    assert not _git(workspace_seed.root, "status", "--porcelain")
    assert (workspace_seed.root / ".git/config").read_bytes() == original_config

    _git(root, "commit", "-m", "Change private copy")
    assert _git(root, "rev-parse", "HEAD") != workspace_seed.base
    assert _git(workspace_seed.root, "rev-parse", "HEAD") == workspace_seed.base
    assert not _git(workspace_seed.root, "branch", "--list", "private-copy")


def _change(root: Path, names: Sequence[str], *, staged: bool) -> None:
    for name in names:
        (root / "packages" / name / "view.tsx").write_text("export const View = () => <span />;\n", encoding="utf-8")
    _git(root, "add", ".")
    if not staged:
        _git(root, "commit", "-m", "Change selected workspaces")


def _payload(root: Path, base: str, names: Sequence[str], *, staged: bool) -> dict[str, object]:
    changed = _git(root, "diff", "--cached" if staged else base, "--name-only", "--diff-filter=ACMR").splitlines()
    return {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "reactDetected": True,
        "diff": None if staged else {"baseBranch": base, "changedFileCount": len(changed), "isCurrentChanges": False},
        "projects": [
            {
                "directory": str(root / "packages" / name),
                "complete": True,
                "skippedChecks": [],
                "analyzedFileCount": 1,
                "scannedFileCount": 1,
                "diagnostics": [
                    {
                        "filePath": "view.tsx",
                        "plugin": "react-doctor",
                        "rule": "example",
                        "severity": "error",
                        "message": "A scoped diagnostic.",
                        "line": 1,
                        "column": 1,
                    }
                ],
            }
            for name in names
        ],
        "error": None,
    }


@pytest.mark.parametrize("scope", ["staged", "changed", "current"])
@pytest.mark.parametrize("names", [("app",), ("app", "engineering")], ids=["one-workspace", "two-workspaces"])
@pytest.mark.parametrize("metadata_type_changed", [False, True], ids=["untouched", "metadata-type-change"])
def test_scoped_scan_accepts_untouched_omissions_and_preserves_diagnostics(
    workspace: _Workspace,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    names: tuple[str, ...],
    metadata_type_changed: bool,
) -> None:
    root, base = workspace.root, workspace.base
    staged = scope == "staged"
    current = scope == "current"
    _change(root, names, staged=staged or current)
    if metadata_type_changed:
        metadata = root / "packages" / "qa" / "package.json"
        metadata.unlink()
        metadata.symlink_to("../app/package.json")
        _git(root, "add", ".")
        if scope == "changed":
            _git(root, "commit", "-m", "Type-change untouched project metadata")
        assert (
            _git(
                root,
                "diff",
                "--cached" if staged else base,
                "--name-status",
                "--",
                "packages/qa/package.json",
            )
            == "T\tpackages/qa/package.json"
        )
    payload = _payload(root, base, names, staged=staged)
    if current:
        for key in ("SARJ_STANDARDS_BASE", "SARJ_REACT_DOCTOR_BASE", "GITHUB_EVENT_PATH"):
            monkeypatch.delenv(key, raising=False)
        payload["diff"] = {"baseBranch": "main", "changedFileCount": len(names), "isCurrentChanges": True}

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=len(names),
        staged=staged,
    )

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert tuple(item.location.path for item in report.diagnostics) == tuple(
        f"packages/{name}/view.tsx" for name in names
    )
    assert all(item.code == "react-doctor/example" for item in report.diagnostics)


@pytest.mark.parametrize("scope", ["staged", "changed", "current"])
@pytest.mark.parametrize("failure", ["touched-omission", "git-failure", "unexpected-project", "incomplete"])
def test_scoped_scan_keeps_coverage_failures_blocking(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch, scope: str, failure: str
) -> None:
    root, base = workspace.root, workspace.base
    staged = scope == "staged"
    current = scope == "current"
    _change(root, ("app", "engineering") if failure == "touched-omission" else ("app",), staged=staged or current)
    payload = _payload(root, base, ("unselected",) if failure == "unexpected-project" else ("app",), staged=staged)
    if current:
        for key in ("SARJ_STANDARDS_BASE", "SARJ_REACT_DOCTOR_BASE", "GITHUB_EVENT_PATH"):
            monkeypatch.delenv(key, raising=False)
        payload["diff"] = {
            "baseBranch": "main",
            "changedFileCount": 2 if failure == "touched-omission" else 1,
            "isCurrentChanges": True,
        }
    if failure == "incomplete":
        payload["projects"] = [{"directory": str(root / "packages" / "app"), "complete": False}]

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "git":
            return ProcessOutput(128, "", "Git unavailable") if failure == "git-failure" else run_process(argv, cwd=cwd)
        return ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=staged,
    )

    assert report.completion is Completion.FAILED
    expected_message = "did not complete" if failure == "incomplete" else "requested project set"
    assert expected_message in report.issues[0].message


@pytest.mark.parametrize(
    "failure",
    [
        "different-base",
        "wrong-count",
        "current-count-mismatch",
        "current-base-mismatch",
        "missing-scope-kind",
        "missing-scope",
    ],
)
def test_changed_scan_requires_matching_verified_scope(workspace: _Workspace, failure: str) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app",), staged=False)
    payload = _payload(root, base, ("app",), staged=False)
    payload["diff"] = {
        "baseBranch": "HEAD" if failure in {"different-base", "current-base-mismatch"} else base,
        "changedFileCount": 0 if failure in {"wrong-count", "current-count-mismatch"} else 1,
        "isCurrentChanges": failure in {"current-count-mismatch", "current-base-mismatch"},
    }
    if failure == "missing-scope-kind":
        payload["diff"] = {"baseBranch": base, "changedFileCount": 1}
    elif failure == "missing-scope":
        payload["diff"] = None

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "requested project set" in report.issues[0].message


def test_full_scan_still_requires_every_selected_workspace(workspace: _Workspace) -> None:
    root, base = workspace.root, workspace.base
    payload = _payload(root, base, ("app",), staged=False)

    with pytest.raises(ValueError, match="requested project set"):
        external.parse_react_doctor(
            json.dumps(payload), root=root, expected_projects=frozenset((root / "packages").iterdir())
        )


def test_staged_omissions_use_index_instead_of_worktree(workspace: _Workspace) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app",), staged=True)
    (root / "packages" / "engineering" / "view.tsx").write_text(
        "export const View = () => <span />;\n", encoding="utf-8"
    )
    payload = _payload(root, base, ("app",), staged=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("packages/app/view.tsx",)


@pytest.mark.parametrize("change", ["rename", "delete-and-change", "symlink"])
def test_staged_omissions_cannot_hide_source_path_changes(workspace: _Workspace, change: str) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app",), staged=True)
    source = root / "packages" / "engineering" / "view.tsx"
    match change:
        case "rename":
            _git(root, "mv", "packages/app/view.tsx", "packages/engineering/moved.tsx")
        case "delete-and-change":
            source.unlink()
            (source.parent / "new.tsx").write_text("export const View = () => <span />;\n", encoding="utf-8")
        case _:
            source.unlink()
            source.symlink_to(root.parent / "outside.tsx")
    _git(root, "add", ".")
    payload = _payload(root, base, ("app",), staged=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=2,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "requested project set" in report.issues[0].message


@pytest.mark.parametrize("full_complete", [True, False], ids=["complete-fallback", "missing-fallback-projects"])
@pytest.mark.parametrize("type_changed_source", [False, True], ids=["modified-source", "type-changed-source"])
def test_staged_full_fallback_retains_complete_workspace_coverage(
    workspace: _Workspace, full_complete: bool, type_changed_source: bool
) -> None:
    root, base = workspace.root, workspace.base
    if type_changed_source:
        source = root / "packages" / "engineering" / "view.tsx"
        source.unlink()
        source.symlink_to("package.json")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "Record source symlink before type change")
        source.unlink()
        source.write_text("export const View = () => <span />;\n", encoding="utf-8")
    _change(root, ("app",), staged=True)
    if type_changed_source:
        assert _git(root, "diff", "--cached", "--name-status", "--", "packages/engineering/view.tsx") == (
            "T\tpackages/engineering/view.tsx"
        )
    scoped = _payload(root, base, ("app", "engineering") if type_changed_source else ("app",), staged=True)
    scoped["reactDetected"] = False
    full = _payload(
        root, base, ("app", "engineering", "qa", "ai-dashboard") if full_complete else ("app",), staged=True
    )
    doctor_calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "git":
            return run_process(argv, cwd=cwd)
        doctor_calls.append(tuple(argv))
        return ProcessOutput(1, json.dumps(full if "--scope" in argv else scoped), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=2 if type_changed_source else 1,
        staged=True,
    )

    assert len(doctor_calls) == 2
    assert "--staged" in doctor_calls[0]
    assert doctor_calls[1][doctor_calls[1].index("--scope") + 1] == "full"
    if full_complete:
        assert report.completion is Completion.COMPLETE
        expected_paths = (
            ("packages/app/view.tsx", "packages/engineering/view.tsx")
            if type_changed_source
            else ("packages/app/view.tsx",)
        )
        assert tuple(item.location.path for item in report.diagnostics) == expected_paths
    else:
        assert report.completion is Completion.FAILED
        assert "requested project set" in report.issues[0].message


@pytest.mark.parametrize("staged", [True, False], ids=["staged", "changed"])
@pytest.mark.parametrize("root_source_changed", [False, True], ids=["nested-only", "root-source"])
@pytest.mark.parametrize(
    "root_report",
    [
        "omitted",
        "empty",
        "incomplete",
        "skipped",
        "skipped-reason",
        "missing-count",
        "partial-count",
        "diagnostic",
        "touched-empty",
        "git-failure",
    ],
)
def test_nested_project_change_does_not_require_enclosing_root_project(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch, staged: bool, root_source_changed: bool, root_report: str
) -> None:
    root = workspace.root
    (root / "package.json").write_text('{"devDependencies":{"react":"19.2.8"}}\n', encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Declare React at the repository root")
    base = _git(root, "rev-parse", "HEAD")
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    if root_source_changed:
        (root / "snippet.tsx").write_text("export const Snippet = () => <div />;\n", encoding="utf-8")
    _change(root, ("app",), staged=staged)
    payload = _payload(root, base, ("app",), staged=staged)
    projects = payload["projects"]
    assert is_object_list(projects)
    app_project = projects[0]
    assert is_object_mapping(app_project)
    overrides: dict[str, dict[str, object]] = {
        "empty": {},
        "incomplete": {"complete": False},
        "skipped": {"skippedChecks": ["lint"]},
        "skipped-reason": {"skippedCheckReasons": {"lint": "unavailable"}},
        "missing-count": {"scannedFileCount": None},
        "partial-count": {"scannedFileCount": 1},
        "diagnostic": {"diagnostics": app_project["diagnostics"]},
        "touched-empty": {},
        "git-failure": {},
    }
    if root_report != "omitted":
        projects.insert(
            0,
            {
                "directory": ".",
                "complete": True,
                "skippedChecks": [],
                "analyzedFileCount": 0,
                "scannedFileCount": 0,
                "diagnostics": [],
                **overrides[root_report],
            },
        )
    if root_report == "touched-empty":
        app_project.update({"analyzedFileCount": 0, "scannedFileCount": 0})

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if root_report == "git-failure" and argv[:2] == ("git", "diff"):
            return ProcessOutput(2, "", "Git scope proof unavailable")
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=(root, *sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=2 if root_source_changed else 1,
        staged=staged,
    )

    if root_source_changed or root_report not in {"omitted", "empty"}:
        assert report.completion is Completion.FAILED
        assert report.issues
    else:
        assert report.completion is Completion.COMPLETE
        assert tuple(item.location.path for item in report.diagnostics) == ("packages/app/view.tsx",)


@pytest.mark.parametrize("degraded", [False, True], ids=["ordinary", "degraded"])
@pytest.mark.parametrize("source_changed", [True, False], ids=["source", "metadata"])
@pytest.mark.parametrize("reported_count", [0, 1], ids=["native-count", "inconsistent-count"])
def test_empty_changed_scope_checks_type_changes(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch, degraded: bool, source_changed: bool, reported_count: int
) -> None:
    root, base = workspace.root, workspace.base
    project = root / "packages" / "app"
    changed = project / ("view.tsx" if source_changed else "policy.json")
    if not source_changed:
        changed.write_text("{}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "Track project metadata")
        base = _git(root, "rev-parse", "HEAD")
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    changed.unlink()
    changed.symlink_to("package.json")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Type-change selected file")
    relative = changed.relative_to(root).as_posix()
    assert _git(root, "diff", "--name-status", base, "HEAD", "--", relative) == f"T\t{relative}"
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "baselineDegraded": degraded,
        "diff": {"baseBranch": base, "changedFileCount": reported_count, "isCurrentChanges": False},
        "projects": [],
        "diagnostics": [],
        "error": None,
    }
    native_called = False

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal native_called
        if argv[0] == "git":
            return run_process(argv, cwd=cwd)
        native_called = True
        return ProcessOutput(0, json.dumps(payload), "")

    reports = external.analyze_external(
        (str(project / "package.json"),),
        root=root,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert native_called
    assert len(reports) == 1
    if source_changed or reported_count:
        assert reports[0].completion is Completion.FAILED
        assert reports[0].diagnostics == ()
        expected_message = "baseline degraded" if degraded else "no analyzed projects"
        assert expected_message in reports[0].issues[0].message
    else:
        assert reports[0].completion is Completion.COMPLETE
        assert reports[0].diagnostics == ()
        assert reports[0].issues == ()


def test_empty_degraded_scope_cannot_substitute_selected_base(workspace: _Workspace) -> None:
    root, base = workspace.root, workspace.base
    project = root / "packages" / "app"
    _change(root, ("app",), staged=False)
    head = _git(root, "rev-parse", "HEAD")
    assert head != base
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "baselineDegraded": True,
        "diff": {"baseBranch": head, "changedFileCount": 0, "isCurrentChanges": False},
        "projects": [],
        "diagnostics": [],
        "error": None,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    reports = external.analyze_external(
        (str(project / "package.json"),),
        root=root,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert "baseline degraded" in reports[0].issues[0].message


@pytest.mark.parametrize("scope", ["ordinary", "degraded", "current", "degraded-current"])
@pytest.mark.parametrize("staged", [False, True], ids=["worktree", "index"])
@pytest.mark.parametrize("change", ["metadata", "source-type", "metadata-and-source"])
def test_empty_changed_scope_proves_the_native_tracked_worktree(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch, scope: str, staged: bool, change: str
) -> None:
    root = workspace.root
    degraded = scope in {"degraded", "degraded-current"}
    current = scope in {"current", "degraded-current"}
    project = root / "packages" / "app"
    metadata = project / "policy.json"
    metadata.write_text("{}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Track project metadata")
    base = _git(root, "rev-parse", "HEAD")
    if current:
        for key in ("SARJ_STANDARDS_BASE", "SARJ_REACT_DOCTOR_BASE", "GITHUB_EVENT_PATH"):
            monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    if change != "source-type":
        metadata.write_text('{"reviewed":true}\n', encoding="utf-8")
    if change != "metadata":
        source = project / "view.tsx"
        source.unlink()
        source.symlink_to("package.json")
    if staged:
        _git(root, "add", ".")
    reported_count = 0 if change == "source-type" else 1
    assert len(_git(root, "diff", base, "--name-only", "--diff-filter=ACMR").splitlines()) == reported_count
    assert not _git(root, "diff", f"{base}...HEAD", "--name-only")
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "baselineDegraded": degraded,
        "diff": {
            "baseBranch": "main" if current else base,
            "changedFileCount": reported_count,
            "isCurrentChanges": current,
        },
        "projects": [],
        "diagnostics": [],
        "error": None,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    reports = external.analyze_external(
        (str(project / "package.json"),),
        root=root,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(reports) == 1
    if change == "metadata":
        assert reports[0].completion is Completion.COMPLETE
        assert reports[0].issues == ()
    else:
        assert reports[0].completion is Completion.FAILED
        expected_message = "baseline degraded" if degraded else "no analyzed projects"
        assert expected_message in reports[0].issues[0].message


@pytest.mark.parametrize("kind", ["untracked-metadata", "untracked-source", "ignored-source"])
def test_empty_changed_scope_keeps_native_untracked_exclusions(workspace: _Workspace, kind: str) -> None:
    root, base = workspace.root, workspace.base
    project = root / "packages" / "app"
    local_file = project / ("local/ignored.tsx" if kind == "ignored-source" else "untracked.tsx")
    if kind == "untracked-metadata":
        local_file = project / "untracked.json"
    if kind == "ignored-source":
        local_file.parent.mkdir()
        excludes = root / ".git" / "info"
        excludes.mkdir(exist_ok=True)
        (excludes / "exclude").write_text("packages/app/local/\n", encoding="utf-8")
    local_file.write_text(
        "{}\n" if kind == "untracked-metadata" else "export const Local = () => <div />;\n", encoding="utf-8"
    )
    assert not _git(root, "diff", base, "--name-only", "--diff-filter=ACMRT")
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "diff": {"baseBranch": base, "changedFileCount": 0, "isCurrentChanges": False},
        "projects": [],
        "diagnostics": [],
        "error": None,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    reports = external.analyze_external(
        (str(project / "package.json"),),
        root=root,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].issues == ()


@pytest.mark.parametrize("failure", ["none", "source", "wrong-count", "wrong-base", "unrelated"])
def test_empty_changed_scope_uses_the_requested_bases_common_ancestor(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root, common = workspace.root, workspace.base
    project = root / "packages" / "app"
    _git(root, "checkout", "-b", "requested-base")
    (project / "view.tsx").write_text("export const View = () => <em>Base branch</em>;\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Advance requested base with source")
    requested = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "main")
    if failure == "source":
        _change(root, ("app",), staged=False)
    else:
        (project / "package.json").write_text(
            '{"dependencies":{"react":"19.2.8"},"version":"0.0.1"}\n', encoding="utf-8"
        )
        _git(root, "add", ".")
        _git(root, "commit", "-m", "Advance feature branch with metadata")
    if failure == "unrelated":
        _git(root, "checkout", "--orphan", "unrelated-base")
        _git(root, "rm", "-r", "-f", ".")
        (root / "unrelated.md").write_text("Unrelated history\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "Create unrelated base")
        requested = _git(root, "rev-parse", "HEAD")
        _git(root, "checkout", "main")
    monkeypatch.setenv("SARJ_STANDARDS_BASE", requested)
    assert run_process(("git", "merge-base", "--is-ancestor", requested, "HEAD"), cwd=root).returncode == 1
    if failure != "unrelated":
        assert _git(root, "merge-base", requested, "HEAD") == common
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "diff": {
            "baseBranch": common if failure == "wrong-base" else requested,
            "changedFileCount": 2 if failure == "wrong-count" else 1,
            "isCurrentChanges": False,
        },
        "projects": [],
        "diagnostics": [],
        "error": None,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    reports = external.analyze_external(
        (str(project / "package.json"),),
        root=root,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(reports) == 1
    if failure == "none":
        assert reports[0].completion is Completion.COMPLETE
        assert reports[0].issues == ()
    else:
        assert reports[0].completion is Completion.FAILED
        assert "no analyzed projects" in reports[0].issues[0].message


@pytest.mark.parametrize("scope", ["staged", "changed", "current"])
@pytest.mark.parametrize("partial", [False, True], ids=["empty", "omitted-workspace"])
@pytest.mark.parametrize(
    ("relative", "eligible"),
    [
        pytest.param("view.ts\n", False, id="terminal-lf"),
        pytest.param("view.ts\r", False, id="terminal-cr"),
        pytest.param("view.ts\r\n", False, id="terminal-crlf"),
        pytest.param("view.ts\u2028", False, id="terminal-u2028"),
        pytest.param("view.ts\u2029", False, id="terminal-u2029"),
        pytest.param("bundle.min.js\n", False, id="bundle-terminal-lf"),
        pytest.param("bundle.m\u0131n.js\n", False, id="unicode-bundle-terminal-lf"),
        pytest.param("view\n.ts", True, id="internal-lf"),
        ("helper.cts", False),
        ("helper.cjs", False),
        ("view.htm", False),
        # Keep the uppercase-extension probe distinct from the existing view.tsx
        # on case-insensitive filesystems; it must create its own Git path.
        ("uppercase.TSX", False),
        ("view.JS", False),
        ("view.ASTRO", False),
        ("bundle.iife.js", False),
        ("bundle.umd.mjs", False),
        ("bundle.global.js", False),
        ("bundle.min.js", False),
        ("bundle.MiN.mjs", False),
        ("__generated__/view.tsx", False),
        ("nested/__generated__/view.tsx", False),
        ("view.ts", True),
        ("view.tsx", True),
        ("view.js", True),
        ("view.jsx", True),
        ("view.mts", True),
        ("view.mjs", True),
        ("view.astro", True),
        ("view.html", True),
        ("view.hTmL", True),
        ("types.d.ts", True),
        ("types.d.mts", True),
        ("eslint.strict.mjs", True),
        ("eslint.strict.ts", True),
        ("bundle.min.tsx", True),
        ("bundle.minimum.js", True),
        ("bundle.mın.js", True),
        ("__generated__prefix/view.tsx", True),
        ("nested__generated__/view.tsx", True),
        ("__Generated__/view.tsx", True),
    ],
)
def test_scoped_scan_matches_native_source_eligibility(
    workspace: _Workspace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scope: str,
    partial: bool,
    relative: str,
    eligible: bool,
) -> None:
    root, base = workspace.root, workspace.base
    staged = scope == "staged"
    current = scope == "current"
    changed = root / "packages" / "engineering" / relative
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("export const reviewed = true;\n", encoding="utf-8")
    names = ("app",) if partial else ()
    _change(root, names, staged=staged or current)
    payload = _payload(root, base, names, staged=staged)
    if current:
        for key in ("SARJ_STANDARDS_BASE", "SARJ_REACT_DOCTOR_BASE", "GITHUB_EVENT_PATH"):
            monkeypatch.delenv(key, raising=False)
        payload["diff"] = {
            "baseBranch": "main",
            "changedFileCount": 2 if partial else 1,
            "isCurrentChanges": True,
        }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=2 if partial else 1,
        staged=staged,
    )

    if eligible:
        assert report.completion is Completion.FAILED
        expected_message = "requested project set" if partial else "no analyzed projects"
        assert expected_message in report.issues[0].message
    else:
        assert report.completion is Completion.COMPLETE
        assert report.issues == ()
        assert tuple(item.location.path for item in report.diagnostics) == tuple(
            f"packages/{name}/view.tsx" for name in names
        )


@pytest.mark.parametrize("failure", ["wrong-count", "wrong-base"])
def test_native_excluded_source_keeps_changed_scope_guards(workspace: _Workspace, failure: str) -> None:
    root, base = workspace.root, workspace.base
    project = root / "packages" / "app"
    (project / "helper.cts").write_text("export const reviewed = true;\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Add source outside the native filter")
    payload = _payload(root, base, (), staged=False)
    payload["diff"] = {
        "baseBranch": "HEAD" if failure == "wrong-base" else base,
        "changedFileCount": 0 if failure == "wrong-count" else 1,
        "isCurrentChanges": False,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message


def test_generated_checkout_parent_does_not_exclude_authored_source(workspace: _Workspace) -> None:
    root = workspace.root.parent / "__generated__" / workspace.root.name
    root.parent.mkdir(exist_ok=True)
    workspace.root.rename(root)
    _change(root, ("app",), staged=False)
    payload = _payload(root, workspace.base, (), staged=False)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(0, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message
