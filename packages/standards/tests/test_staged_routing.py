from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.fixture
def adopted_git_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, env={})
    assert cli.main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    subprocess.run(("git", "add", "--all"), cwd=tmp_path, check=True, env={})
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Standards Test",
            "-c",
            "user.email=standards-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        cwd=tmp_path,
        check=True,
        env={},
    )
    return tmp_path


def test_staged_check_routes_additions_renames_and_only_requested_files(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = adopted_git_repo
    added = repository / "added.py"
    added.write_text("added = True\n", encoding="utf-8")
    subprocess.run(("git", "mv", "source.py", "renamed.py"), cwd=repository, check=True)
    subprocess.run(("git", "add", "added.py"), cwd=repository, check=True)
    (repository / "untracked.py").write_text("untracked = True\n", encoding="utf-8")
    routed: list[tuple[str, ...]] = []

    def record_check(
        root: Path,
        paths: Sequence[str] | None,
        *,
        raw: bool = False,
        trusted: bool = False,
        staged: bool = False,
        jobs: int = 1,
        python_type_check: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert root == repository.resolve()
        assert not raw
        assert not trusted
        assert staged
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- canonical staged routing interception is the behavior under test.
        cli, "_run_canonical_check", record_check
    )

    assert cli.main(["--root", str(repository), "check", "--staged"]) == 0
    assert cli.main(["--root", str(repository), "check", "--staged", "--", "added.py"]) == 0
    assert set(routed[0]) == {str(added.resolve()), str((repository / "renamed.py").resolve())}
    assert routed[1] == (str(added.resolve()),)


def test_staged_check_uses_repository_relative_hook_paths_from_a_nested_cwd(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = adopted_git_repo
    nested = repository / "nested"
    nested.mkdir()
    source = nested / "child.py"
    source.write_text("child = True\n", encoding="utf-8")
    subprocess.run(("git", "add", "nested/child.py"), cwd=repository, check=True)
    routed: list[tuple[str, ...]] = []

    def record_check(
        root: Path,
        paths: Sequence[str] | None,
        *,
        raw: bool = False,
        trusted: bool = False,
        staged: bool = False,
        jobs: int = 1,
        python_type_check: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert root == repository.resolve()
        assert not raw
        assert not trusted
        assert staged
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- canonical staged routing interception is the behavior under test.
        cli, "_run_canonical_check", record_check
    )
    monkeypatch.chdir(nested)

    assert cli.main(["--root", str(repository), "check", "--staged", "--", "nested/child.py"]) == 0
    assert routed == [(str(source.resolve()),)]


@pytest.mark.parametrize("worktree_state", ["modified", "deleted"])
def test_staged_check_refuses_a_worktree_version_that_differs_from_the_index(
    adopted_git_repo: Path,
    capsys: pytest.CaptureFixture[str],
    worktree_state: str,
) -> None:
    source = adopted_git_repo / "source.py"
    source.write_text("value = 2\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.py"), cwd=adopted_git_repo, check=True)
    if worktree_state == "modified":
        source.write_text("value = 3\n", encoding="utf-8")
    else:
        source.unlink()

    status = cli.main(["--root", str(adopted_git_repo), "check", "--staged"])

    output = capsys.readouterr()
    assert status == 2
    assert "files with unstaged content" in output.err
    assert "source.py" in output.err


def test_staged_check_still_runs_repository_policy_without_source_selections(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routed: list[tuple[Sequence[str] | None, bool]] = []

    def record_check(
        _root: Path,
        paths: Sequence[str] | None,
        *,
        raw: bool = False,
        trusted: bool = False,
        staged: bool = False,
        jobs: int = 1,
        python_type_check: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert not raw
        assert not trusted
        routed.append((paths, staged))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- canonical staged routing interception is the behavior under test.
        cli, "_run_canonical_check", record_check
    )

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0
    subprocess.run(("git", "rm", "source.py"), cwd=adopted_git_repo, check=True, capture_output=True)
    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0
    assert routed == [((), True), ((), True)]


def test_staged_check_does_not_hide_deleted_adoption_config(
    adopted_git_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(("git", "rm", ".ruff-strict.toml"), cwd=adopted_git_repo, check=True, capture_output=True)

    status = cli.main(["--root", str(adopted_git_repo), "check", "--staged"])

    output = capsys.readouterr()
    assert status == 1
    assert "doctor.config.missing" in output.out


def test_staged_check_discovers_mixed_supported_paths_without_a_hook_filter(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "typed.pyi",
        "app.py",
        "app.ts",
        "app.tsx",
        "app.mts",
        "app.cts",
        "app.js",
        "app.jsx",
        "app.mjs",
        "app.cjs",
        "app.kt",
        "app.kts",
        "app.swift",
        "query.sql",
        "main.tf",
        "main.tfvars",
        "module.hcl",
        "main.tf.json",
        "variables.tfvars.json",
        "example.tftest.hcl",
        "document.yaml",
        "document.yml",
        "settings.toml",
        "deploy/settings.json",
        "settings.jsonc",
        "README.md",
        "page.mdx",
        "settings.ini",
        "library.sh",
        "Dockerfile",
        "Makefile",
        "requirements/prod.txt",
        "space name.pyi",
        "newline\nname.pyi",
        "-leading.py",
    )
    for name in names:
        path = adopted_git_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    subprocess.run(("git", "add", "--", *names), cwd=adopted_git_repo, check=True)
    routed: list[tuple[str, ...]] = []

    def healthy_adoption(_root: Path, _paths: object, *, args: object) -> int:  # ruff: ignore[unused-function-argument] -- callback keyword must match the CLI boundary.
        return 0

    def record_check(_root: Path, paths: Sequence[str] | None, **_options: bool | int) -> int:
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- verifies the complete canonical index selection.
        cli, "_run_canonical_check", record_check
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native tool installation is independent of index selection.
        cli, "_check_staged_adoption_health", healthy_adoption
    )

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0
    assert set(routed[0]) == {str((adopted_git_repo / name).resolve()) for name in names}


def test_staged_check_includes_file_type_changes(adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = adopted_git_repo / "typed.pyi"
    source.symlink_to("source.py")
    subprocess.run(("git", "add", "typed.pyi"), cwd=adopted_git_repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "symlink"),
        cwd=adopted_git_repo,
        check=True,
    )
    source.unlink()
    source.write_text("value: int\n", encoding="utf-8")
    subprocess.run(("git", "add", "typed.pyi"), cwd=adopted_git_repo, check=True)
    routed: list[tuple[str, ...]] = []

    def record_check(_root: Path, paths: Sequence[str] | None, **_options: bool | int) -> int:
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a Git type change must reach the canonical gate.
        cli, "_run_canonical_check", record_check
    )
    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0
    assert routed == [(str(source.resolve()),)]


@pytest.mark.parametrize("state", ["empty", "deleted"])
def test_staged_fix_does_not_format_the_repository_when_no_sources_are_selected(
    adopted_git_repo: Path, state: str
) -> None:
    if state == "deleted":
        subprocess.run(("git", "rm", "source.py"), cwd=adopted_git_repo, check=True, capture_output=True)
    unrelated = adopted_git_repo / "untracked.py"
    original = "unrelated=  (  3 )\n"
    unrelated.write_text(original, encoding="utf-8")
    assert cli.main(["--root", str(adopted_git_repo), "fix", "--staged"]) == 0
    assert (
        unrelated.read_text(encoding="utf-8") == original
    )  # sarj-noqa: SARJ402 -- exact untracked byte preservation is the contract.


def test_staged_fix_refuses_partial_staging_before_modifying_content(adopted_git_repo: Path) -> None:
    source = adopted_git_repo / "source.py"
    source.write_text("value=  ( 2 )\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.py"), cwd=adopted_git_repo, check=True)
    original = "value=  ( 3 )\n"
    source.write_text(original, encoding="utf-8")
    assert cli.main(["--root", str(adopted_git_repo), "fix", "--staged"]) == 2
    assert (
        source.read_text(encoding="utf-8") == original
    )  # sarj-noqa: SARJ402 -- exact unstaged byte preservation is the contract.
    assert (
        subprocess.run(
            ("git", "show", ":source.py"), cwd=adopted_git_repo, check=True, capture_output=True, text=True
        ).stdout
        == "value=  ( 2 )\n"
    )


def test_staged_fix_handles_option_like_paths_and_converges(adopted_git_repo: Path) -> None:
    source = adopted_git_repo / "--config.pyi"
    source.write_text("value :  int\n", encoding="utf-8")
    unrelated = adopted_git_repo / "untracked.py"
    unrelated.write_text("unrelated= ( 3 )\n", encoding="utf-8")
    subprocess.run(("git", "add", "--", source.name), cwd=adopted_git_repo, check=True)
    assert cli.main(["--root", str(adopted_git_repo), "fix", "--staged"]) == 0
    assert (
        source.read_text(encoding="utf-8") == "value: int\n"
    )  # sarj-noqa: SARJ402 -- exact formatter output and convergence are the contract.
    assert (
        unrelated.read_text(encoding="utf-8") == "unrelated= ( 3 )\n"
    )  # sarj-noqa: SARJ402 -- the unselected file must remain byte-identical.
    subprocess.run(("git", "add", "--", source.name), cwd=adopted_git_repo, check=True)
    assert cli.main(["--root", str(adopted_git_repo), "fix", "--staged"]) == 0
    assert (
        source.read_text(encoding="utf-8") == "value: int\n"
    )  # sarj-noqa: SARJ402 -- exact formatter output and convergence are the contract.


def test_staged_requirement_manifest_runs_the_library_policy(
    adopted_git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    requirement = adopted_git_repo / "requirements-dev.in"
    requirement.write_text("pytz==2026.1\n", encoding="utf-8")
    subprocess.run(("git", "add", requirement.name), cwd=adopted_git_repo, check=True)
    capsys.readouterr()
    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 1
    output = capsys.readouterr().out
    assert "LIB008" in output
    assert "code-standards fix --staged" in output


@pytest.mark.parametrize("state", ["empty", "deleted"])
def test_empty_staged_json_remains_structured_and_does_not_scan_unrelated_sources(
    adopted_git_repo: Path, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    if state == "deleted":
        subprocess.run(("git", "rm", "source.py"), cwd=adopted_git_repo, check=True, capture_output=True)
    (adopted_git_repo / "untracked.py").write_text("def invalid syntax\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged", "--format", "json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)
    assert "untracked.py" not in output
    assert "Agent:" not in output
