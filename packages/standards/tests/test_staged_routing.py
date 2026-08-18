from __future__ import annotations

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
    ) -> int:
        assert root == repository.resolve()
        assert not raw
        assert not trusted
        assert staged
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(cli, "_run_canonical_check", record_check)

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
    ) -> int:
        assert root == repository.resolve()
        assert not raw
        assert not trusted
        assert staged
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(cli, "_run_canonical_check", record_check)
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


def test_staged_check_ignores_clean_and_deleted_only_selections(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_check(*_args: object, **_kwargs: object) -> int:
        pytest.fail("no analyzable staged file should reach the diagnostic boundary")

    monkeypatch.setattr(cli, "_run_canonical_check", unexpected_check)

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0
    subprocess.run(("git", "rm", "source.py"), cwd=adopted_git_repo, check=True, capture_output=True)
    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged"]) == 0


def test_staged_check_does_not_hide_deleted_adoption_config(
    adopted_git_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(("git", "rm", ".ruff-strict.toml"), cwd=adopted_git_repo, check=True, capture_output=True)

    status = cli.main(["--root", str(adopted_git_repo), "check", "--staged"])

    output = capsys.readouterr()
    assert status == 1
    assert "doctor.config.missing" in output.out
