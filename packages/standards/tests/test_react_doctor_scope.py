from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.external import ProcessOutput, run_process


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


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Workspace:
    _git(tmp_path, "init", "--template=", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Scope test")
    _git(tmp_path, "config", "user.email", "scope@example.com")
    for name in ("app", "engineering", "qa", "ai-dashboard"):
        project = tmp_path / "packages" / name
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"dependencies":{"react":"19.2.8"}}\n', encoding="utf-8")
        (project / "view.tsx").write_text("export const View = () => <div />;\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Initial workspaces")
    base = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    return _Workspace(root=tmp_path, base=base)


def _change(root: Path, names: Sequence[str], *, staged: bool) -> None:
    for name in names:
        (root / "packages" / name / "view.tsx").write_text("export const View = () => <span />;\n", encoding="utf-8")
    _git(root, "add", ".")
    if not staged:
        _git(root, "commit", "-m", "Change selected workspaces")


def _payload(root: Path, base: str, names: Sequence[str], *, staged: bool) -> dict[str, object]:
    changed = _git(root, "diff", "--cached" if staged else f"{base}...HEAD", "--name-only").splitlines()
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


@pytest.mark.parametrize("staged", [True, False], ids=["staged", "changed"])
@pytest.mark.parametrize("names", [("app",), ("app", "engineering")], ids=["one-workspace", "two-workspaces"])
def test_scoped_scan_accepts_untouched_omissions_and_preserves_diagnostics(
    workspace: _Workspace, staged: bool, names: tuple[str, ...]
) -> None:
    root, base = workspace.root, workspace.base
    _change(root, names, staged=staged)
    payload = _payload(root, base, names, staged=staged)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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


@pytest.mark.parametrize("staged", [True, False], ids=["staged", "changed"])
@pytest.mark.parametrize("failure", ["touched-omission", "git-failure", "unexpected-project", "incomplete"])
def test_scoped_scan_keeps_coverage_failures_blocking(workspace: _Workspace, staged: bool, failure: str) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app", "engineering") if failure == "touched-omission" else ("app",), staged=staged)
    payload = _payload(root, base, ("unselected",) if failure == "unexpected-project" else ("app",), staged=staged)
    if failure == "incomplete":
        payload["projects"] = [{"directory": str(root / "packages" / "app"), "complete": False}]

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "git":
            return ProcessOutput(128, "", "Git unavailable") if failure == "git-failure" else run_process(argv, cwd=cwd)
        return ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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


@pytest.mark.parametrize("failure", ["different-base", "wrong-count", "current-changes", "missing-scope"])
def test_changed_scan_requires_matching_verified_scope(workspace: _Workspace, failure: str) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app",), staged=False)
    payload = _payload(root, base, ("app",), staged=False)
    payload["diff"] = {
        "baseBranch": "HEAD" if failure == "different-base" else base,
        "changedFileCount": 0 if failure == "wrong-count" else 1,
        "isCurrentChanges": failure == "current-changes",
    }
    if failure == "missing-scope":
        payload["diff"] = None

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        return run_process(argv, cwd=cwd) if argv[0] == "git" else ProcessOutput(1, json.dumps(payload), "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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
def test_staged_full_fallback_retains_complete_workspace_coverage(workspace: _Workspace, full_complete: bool) -> None:
    root, base = workspace.root, workspace.base
    _change(root, ("app",), staged=True)
    scoped = _payload(root, base, ("app",), staged=True)
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

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        root,
        projects=tuple(sorted((root / "packages").iterdir())),
        root=root,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert len(doctor_calls) == 2
    assert "--staged" in doctor_calls[0]
    assert doctor_calls[1][doctor_calls[1].index("--scope") + 1] == "full"
    if full_complete:
        assert report.completion is Completion.COMPLETE
        assert tuple(item.location.path for item in report.diagnostics) == ("packages/app/view.tsx",)
    else:
        assert report.completion is Completion.FAILED
        assert "requested project set" in report.issues[0].message
