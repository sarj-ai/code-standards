from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import lifecycle


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from sarj_standards.cli.main import _Args  # pyright: ignore[reportPrivateUsage]  # sarj-noqa: SARJ048 -- mirrors the private callback contract intercepted by this test.


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


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("invalid", [False, True])
def test_staged_check_uses_only_the_pending_index(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    relative: bool,
    invalid: bool,
) -> None:
    repository = adopted_git_repo
    unrelated = repository / "requirements-unrelated.in"
    unrelated.write_text("pytz==2026.1\n", encoding="utf-8")
    subprocess.run(("git", "add", unrelated.name), cwd=repository, check=True)
    ordinary_index = repository / ".git/index"
    ordinary_before = ordinary_index.read_bytes()
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/pending-index" if relative else str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    selected = repository / "requirements-pending.in"
    selected.write_text("pytz==2026.1\n" if invalid else "packaging==26.3\n", encoding="utf-8")
    subprocess.run(("git", "add", selected.name), cwd=repository, check=True)
    pending_before = pending_index.read_bytes()
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    for variable in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG_GLOBAL",
    ):
        monkeypatch.setenv(variable, str(repository / "unrelated-git-state"))
    monkeypatch.chdir(repository.parent)
    capsys.readouterr()

    assert cli.main(["--root", str(repository), "check", "--staged"]) == int(invalid)

    output = capsys.readouterr()
    assert ("LIB008" in output.out) is invalid
    assert unrelated.name not in output.out + output.err
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("command", ["check", "fix"])
@pytest.mark.parametrize("textconv", [False, True])
def test_pending_index_refuses_unstaged_bytes_before_checking_or_fixing(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    *,
    textconv: bool,
) -> None:
    repository = adopted_git_repo
    source = repository / "source.py"
    ordinary_before = (repository / ".git/index").read_bytes()
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    source.write_bytes(b"value = 2\n")
    subprocess.run(("git", "add", source.name), cwd=repository, check=True)
    pending_before = pending_index.read_bytes()
    source.write_bytes(b"value = 1\n")
    marker = repository / ".git/textconv-called"
    if textconv:
        driver = repository / ".git/textconv.py"
        driver.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_bytes(b'called')\nprint('same rendered source')\n",
            encoding="utf-8",
        )
        (repository / ".git/info/attributes").write_text("source.py diff=fixture\n", encoding="utf-8")
        subprocess.run(
            ("git", "config", "diff.fixture.textconv", shlex.join((sys.executable, str(driver)))),
            cwd=repository,
            check=True,
        )
    arguments = ["--root", str(repository), command, "--staged"]
    if command == "check":
        arguments.append("--fix")

    assert cli.main(arguments) == 2

    assert "files with unstaged content" in capsys.readouterr().err
    assert not marker.exists()
    assert source.read_bytes() == b"value = 1\n"  # sarj-noqa: SARJ402 -- refusal preserves exact source bytes.
    assert pending_index.read_bytes() == pending_before
    assert (repository / ".git/index").read_bytes() == ordinary_before


def _configure_trusted_external_diff(
    repository: Path, monkeypatch: pytest.MonkeyPatch, filename: str, external_driver: str
) -> Path:
    executable = shutil.which("git")
    assert executable is not None
    binaries = repository / ".git/isolated-bin"
    binaries.mkdir()
    wrapper = binaries / "git"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "environment = dict(os.environ)\n"
        "environment.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_SYSTEM': '/dev/null', "
        "'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_ATTR_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'})\n"
        f"os.execve({executable!r}, [{executable!r}, *sys.argv[1:]], environment)\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    marker = repository / ".git/external-diff-called"
    helper = repository / ".git/external-diff.py"
    helper.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_bytes(b'called')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    command = shlex.join((sys.executable, str(helper)))
    if external_driver == "global":
        command_key, trust_key = "diff.external", "diff.trustExitCode"
    else:
        command_key, trust_key = "diff.fixture.command", "diff.fixture.trustExitCode"
        (repository / ".git/info/attributes").write_text(f"{filename} diff=fixture\n", encoding="utf-8")
    subprocess.run(("git", "config", command_key, command), cwd=repository, check=True)
    subprocess.run(("git", "config", trust_key, "true"), cwd=repository, check=True)
    return marker


@pytest.mark.parametrize("external_driver", ["global", "attribute"])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("state", ["dirty-banned-index-valid-worktree", "clean-valid", "clean-banned"])
@pytest.mark.parametrize("output_format", ["text", "json", "sarif"])
def test_staged_external_diff_cannot_hide_a_pending_contract(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    external_driver: str,
    state: str,
    output_format: str,
    pending: bool,
) -> None:
    repository = adopted_git_repo
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    if pending:
        monkeypatch.delenv("GIT_INDEX_FILE")
    unrelated = repository / "requirements-unrelated.in"
    unrelated.write_bytes(b"pytz==2026.1\n")
    subprocess.run(("git", "add", unrelated.name), cwd=repository, check=True)
    if pending:
        monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    else:
        monkeypatch.delenv("GIT_INDEX_FILE")
    selected = repository / "requirements-selected.in"
    marker = _configure_trusted_external_diff(repository, monkeypatch, selected.name, external_driver)
    staged = b"packaging==26.3\n" if state == "clean-valid" else b"pytz==2026.1\n"
    selected.write_bytes(staged)
    subprocess.run(("git", "add", selected.name), cwd=repository, check=True)
    working = b"packaging==26.3\n" if state.startswith("dirty") else staged
    selected.write_bytes(working)
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    capsys.readouterr()

    status = cli.main(["--root", str(repository), "check", "--staged", "--format", output_format])

    output = capsys.readouterr()
    assert status == (2 if state.startswith("dirty") else 1 if state == "clean-banned" else 0)
    assert not marker.exists()
    assert ("LIB008" in output.out) is (state == "clean-banned")
    if state.startswith("dirty"):
        assert "files with unstaged content" in output.out + output.err
    if output_format in {"json", "sarif"}:
        assert json.loads(output.out)
        assert not output.err
    assert selected.read_bytes() == working
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("external_driver", ["global", "attribute"])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("command", ["check", "fix"])
def test_staged_external_diff_refuses_before_native_fixes(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    external_driver: str,
    command: str,
    *,
    pending: bool,
) -> None:
    repository = adopted_git_repo
    source = repository / "source.py"
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    if not pending:
        monkeypatch.delenv("GIT_INDEX_FILE")
    marker = _configure_trusted_external_diff(repository, monkeypatch, source.name, external_driver)
    source.write_bytes(b"# ========\nvalue = 1\n")
    subprocess.run(("git", "add", source.name), cwd=repository, check=True)
    working = b"# ========\nvalue = 2\n"
    source.write_bytes(working)
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    arguments = ["--root", str(repository), command, "--staged"]
    if command == "check":
        arguments.append("--fix")
    capsys.readouterr()

    assert cli.main(arguments) == 2

    assert "files with unstaged content" in capsys.readouterr().err
    assert not marker.exists()
    assert source.read_bytes() == working
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("external_driver", ["global", "attribute"])
@pytest.mark.parametrize("canonical", ["eol", "clean-filter"])
def test_staged_external_diff_preserves_git_canonicalization(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    external_driver: str,
    canonical: str,
) -> None:
    repository = adopted_git_repo
    source = repository / "requirements-selected.in"
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    marker = _configure_trusted_external_diff(repository, monkeypatch, source.name, external_driver)
    attributes = repository / ".git/info/attributes"
    if canonical == "eol":
        subprocess.run(("git", "config", "core.autocrlf", "false"), cwd=repository, check=True)
        declaration = f"{source.name} text eol=crlf\n"
    else:
        cleaner = repository / ".git/canonical-clean.py"
        cleaner.write_text(
            "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'# local annotation\\n', b''))\n",
            encoding="utf-8",
        )
        subprocess.run(
            ("git", "config", "filter.canonical.clean", shlex.join((sys.executable, str(cleaner)))),
            cwd=repository,
            check=True,
        )
        subprocess.run(("git", "config", "filter.canonical.required", "true"), cwd=repository, check=True)
        declaration = f"{source.name} filter=canonical\n"
    with attributes.open("a", encoding="utf-8") as stream:
        stream.write(declaration)
    source.write_bytes(b"packaging==26.3\n")
    subprocess.run(("git", "add", source.name), cwd=repository, check=True)
    working = b"packaging==26.3\r\n" if canonical == "eol" else b"# local annotation\npackaging==26.3\n"
    source.write_bytes(working)
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()

    assert cli.main(["--root", str(repository), "check", "--staged"]) == 0

    assert not marker.exists()
    assert source.read_bytes() == working
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_pending_index_flags_are_checked_instead_of_ordinary_flags(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    repository = adopted_git_repo
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    _stage_hidden_index_source(repository, "flagged.py", (flag,), dirty=False)
    pending_before = pending_index.read_bytes()

    assert cli.main(["--root", str(repository), "check", "--staged", "--fix"]) == 2

    assert "unverifiable Git index flags" in capsys.readouterr().err
    assert pending_index.read_bytes() == pending_before


def test_pending_index_deletion_does_not_resurrect_worktree_content(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = adopted_git_repo
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    subprocess.run(("git", "rm", "--cached", "source.py"), cwd=repository, check=True, capture_output=True)
    (repository / "source.py").write_bytes(b"def invalid syntax\n")
    pending_before = pending_index.read_bytes()

    assert cli.main(["--root", str(repository), "check", "--staged", "--format", "json"]) == 0

    assert pending_index.read_bytes() == pending_before
    assert cli.staged_fix_paths(repository, ()) == []


def test_pending_index_can_select_an_initial_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, env={})
    selected = tmp_path / "source.py"
    selected.write_bytes(b"value = 1\n")
    pending_index = tmp_path / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "add", selected.name), cwd=tmp_path, check=True)
    pending_before = pending_index.read_bytes()

    assert cli.staged_fix_paths(tmp_path, ()) == [str(selected)]

    assert not (tmp_path / ".git/index").exists()
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("command", ["check", "fix"])
def test_pending_safe_fixes_preserve_both_indexes_and_unselected_source(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    repository = adopted_git_repo
    unrelated = repository / "unrelated.py"
    original = b"# ========\n"
    unrelated.write_bytes(original)
    subprocess.run(("git", "add", unrelated.name), cwd=repository, check=True)
    ordinary_before = (repository / ".git/index").read_bytes()
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    selected = repository / "cleanup.py"
    selected.write_bytes(original)
    subprocess.run(("git", "add", selected.name), cwd=repository, check=True)
    pending_before = pending_index.read_bytes()

    def no_external_formatters(
        _root: Path,
        _paths: Iterable[str],
        *,
        trusted: bool = True,  # ruff: ignore[unused-function-argument] -- preserve the formatter planner boundary while testing the real native fix.
        eslint: bool = True,  # ruff: ignore[unused-function-argument] -- preserve the formatter planner boundary while testing the real native fix.
    ) -> list[lifecycle.Command]:
        return []

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the real native fix and Git selection while isolating unrelated external formatting tools.
        lifecycle, "selected_format_commands", no_external_formatters
    )
    arguments = ["--root", str(repository), command, "--staged"]
    if command == "check":
        arguments.append("--fix")

    assert cli.main(arguments) == (1 if command == "check" else 0)

    assert selected.read_bytes() == b"\n"  # sarj-noqa: SARJ402 -- the native fix preserves the exact line ending.
    assert unrelated.read_bytes() == original
    assert pending_index.read_bytes() == pending_before
    assert (repository / ".git/index").read_bytes() == ordinary_before


def test_pull_request_scope_ignores_the_pending_index(adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = adopted_git_repo
    base = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repository / "source.py").write_bytes(b"value = 2\n")
    subprocess.run(("git", "add", "source.py"), cwd=repository, check=True)
    subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "changed"),
        cwd=repository,
        check=True,
        env={},
    )
    monkeypatch.setenv("GIT_INDEX_FILE", str(repository / "missing-index"))
    monkeypatch.setenv("GIT_DIR", str(repository / "unrelated-git-state"))
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    routed: list[tuple[str, ...]] = []

    def record_check(root: Path, paths: Sequence[str] | None, **options: bool | int) -> int:
        assert root == repository
        assert not options["staged"]
        routed.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate language tools while proving native immutable Git diff scoping through the public CLI.
        cli, "_run_canonical_check", record_check
    )

    assert cli.main(["--root", str(repository), "check"]) == 0
    assert routed == [(str(repository / "source.py"),)]


def test_native_partial_commit_checks_only_its_pending_requirements(adopted_git_repo: Path) -> None:
    repository = adopted_git_repo
    unrelated = repository / "requirements-unrelated.in"
    unrelated.write_text("pytz==2026.1\n", encoding="utf-8")
    selected = repository / "requirements-pending.in"
    selected.write_text("packaging==26.3\n", encoding="utf-8")
    subprocess.run(("git", "add", unrelated.name, selected.name), cwd=repository, check=True)
    hook = repository / ".git/hooks/pre-commit"
    hook.write_text(
        f"#!{sys.executable}\n"
        "from sarj_standards.cli.main import main\n"
        f"raise SystemExit(main(['--root', {str(repository)!r}, 'check', '--staged']))\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)

    result = subprocess.run(
        (
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            f"core.hooksPath={hook.parent}",
            "commit",
            "--only",
            selected.name,
            "-qm",
            "partial commit",
        ),
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert subprocess.run(
        ("git", "diff", "--cached", "--name-only"), cwd=repository, check=True, capture_output=True, text=True
    ).stdout.splitlines() == [unrelated.name]


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
        eslint: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert eslint
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
        eslint: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert eslint
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
@pytest.mark.parametrize("fix", [False, True])
def test_staged_check_refuses_a_worktree_version_that_differs_from_the_index(
    adopted_git_repo: Path,
    capsys: pytest.CaptureFixture[str],
    worktree_state: str,
    fix: bool,
) -> None:
    source = adopted_git_repo / "source.py"
    source.write_text("value = 2\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.py"), cwd=adopted_git_repo, check=True)
    if worktree_state == "modified":
        source.write_text("value = 3\n", encoding="utf-8")
    else:
        source.unlink()

    status = cli.main(["--root", str(adopted_git_repo), "check", "--staged", *(["--fix"] if fix else [])])

    output = capsys.readouterr()
    assert status == 2
    assert "files with unstaged content" in output.err
    assert "source.py" in output.err


@pytest.mark.parametrize(
    "flags", [("--assume-unchanged",), ("--skip-worktree",), ("--assume-unchanged", "--skip-worktree")]
)
@pytest.mark.parametrize("dirty", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    ("command", "output_format"), [("check", "text"), ("check", "json"), ("check", "sarif"), ("fix", "text")]
)
def test_staged_routes_refuse_unverifiable_index_flags_before_fix_planning(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    flags: tuple[str, ...],
    command: str,
    output_format: str,
    dirty: bool,
    explicit: bool,
) -> None:
    source = adopted_git_repo / "hidden.py"
    _stage_hidden_index_source(adopted_git_repo, source.name, flags, dirty=dirty)
    original = source.read_bytes()
    index_before = _index_snapshot(adopted_git_repo)

    def unexpected_health(_root: Path, _paths: Iterable[str], *, args: _Args) -> int:  # ruff: ignore[unused-function-argument] -- match the public staged health callback keyword.
        pytest.fail("unverifiable staged sources must be refused before adoption health or fixes")

    def unexpected_commands(
        _root: Path,
        _paths: Iterable[str],
        *,
        trusted: bool = True,  # ruff: ignore[unused-function-argument] -- refusal callbacks retain the existing planner's keyword signature.
        eslint: bool = True,  # ruff: ignore[unused-function-argument] -- refusal callbacks retain the existing planner's keyword signature.
    ) -> list[lifecycle.Command]:
        pytest.fail("unverifiable staged sources must not reach external fix planning")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe refusal before the existing staged health boundary.
        cli, "_check_staged_adoption_health", unexpected_health
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a guard regression must not start native tools in this isolated Git fixture.
        lifecycle, "selected_format_commands", unexpected_commands
    )
    arguments = ["--root", str(adopted_git_repo), command, "--staged"]
    if command == "check":
        arguments.extend(["--fix", "--format", output_format])
    if explicit:
        arguments.extend(["--", source.name])
    capsys.readouterr()

    assert cli.main(arguments) == 2

    output = capsys.readouterr()
    if output_format in {"json", "sarif"}:
        assert json.loads(output.out)
        assert "unverifiable Git index flags" in output.out
        assert not output.err
    else:
        assert "unverifiable Git index flags" in output.err
    assert "assume-unchanged/skip-worktree" in output.out + output.err
    assert source.read_bytes() == original
    assert _index_snapshot(adopted_git_repo) == index_before


@pytest.mark.parametrize("name", ["--config.py", "line\nbreak.py", "[literal].py", ":(glob)*.py"])
@pytest.mark.parametrize("command", ["check", "fix"])
def test_staged_index_flag_reads_keep_special_filenames_literal(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str, command: str
) -> None:
    _stage_hidden_index_source(adopted_git_repo, name, ("--assume-unchanged", "--skip-worktree"), dirty=True)
    source = adopted_git_repo / name
    original = source.read_bytes()
    index_before = _index_snapshot(adopted_git_repo)

    def unexpected_commands(
        _root: Path,
        _paths: Iterable[str],
        *,
        trusted: bool = True,  # ruff: ignore[unused-function-argument] -- refusal callbacks retain the existing planner's keyword signature.
        eslint: bool = True,  # ruff: ignore[unused-function-argument] -- refusal callbacks retain the existing planner's keyword signature.
    ) -> list[lifecycle.Command]:
        pytest.fail("literal flagged paths must be refused before external fix planning")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate external tools while proving real Git filename handling through the public CLI.
        lifecycle, "selected_format_commands", unexpected_commands
    )
    arguments = ["--root", str(adopted_git_repo), command, "--staged"]
    if command == "check":
        arguments.append("--fix")
    arguments.extend(["--", name])
    capsys.readouterr()

    assert cli.main(arguments) == 2

    assert "unverifiable Git index flags" in capsys.readouterr().err
    assert source.read_bytes() == original
    assert _index_snapshot(adopted_git_repo) == index_before


@pytest.mark.parametrize(
    "flags", [("--assume-unchanged",), ("--skip-worktree",), ("--assume-unchanged", "--skip-worktree")]
)
@pytest.mark.parametrize("command", ["check", "fix"])
def test_explicit_staged_fixes_ignore_unrelated_hidden_index_flags(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...], command: str
) -> None:
    _stage_hidden_index_source(adopted_git_repo, "unrelated.py", flags, dirty=True)
    unrelated = adopted_git_repo / "unrelated.py"
    unrelated_before = unrelated.read_bytes()
    selected = adopted_git_repo / "[selected].py"
    original = b"# ========\nvalue = 2\n"
    selected.write_bytes(original)
    subprocess.run(("git", "--literal-pathspecs", "add", "--", selected.name), cwd=adopted_git_repo, check=True)
    index_before = _index_snapshot(adopted_git_repo)
    planned: list[tuple[str, ...]] = []

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == adopted_git_repo
        assert trusted == (command == "fix")
        assert eslint
        planned.append(tuple(paths))
        return []

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- retain the actual native safe fix while isolating every external formatter.
        lifecycle, "selected_format_commands", commands
    )
    arguments = ["--root", str(adopted_git_repo), command, "--staged"]
    if command == "check":
        arguments.append("--fix")
    arguments.extend(["--", selected.name])

    assert cli.main(arguments) == (1 if command == "check" else 0)

    assert b"========" not in selected.read_bytes()
    assert b"value = 2" in selected.read_bytes()
    assert planned == [(str(selected),)]
    assert unrelated.read_bytes() == unrelated_before
    assert _index_snapshot(adopted_git_repo) == index_before


@pytest.mark.parametrize("output_format", ["text", "json", "sarif"])
@pytest.mark.parametrize("failed_read", ["content-diff", "index-flags"])
def test_staged_index_read_failure_preserves_structured_input_errors(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    failed_read: str,
) -> None:
    source = adopted_git_repo / "source.py"
    original = b"# ========\nvalue = 2\n"
    source.write_bytes(original)
    subprocess.run(("git", "add", "--", source.name), cwd=adopted_git_repo, check=True)
    index_before = _index_snapshot(adopted_git_repo)
    executable = shutil.which("git")
    assert executable is not None
    binaries = adopted_git_repo / "fixture-bin"
    binaries.mkdir()
    wrapper = binaries / "git"
    failure_marker = adopted_git_repo / ".git/input-read-failed"
    failure = (
        'case " $* " in *" --cached "*|*" --staged "*) false ;; *" diff "*) true ;; *) false ;; esac'
        if failed_read == "content-diff"
        else '[ "$1" = "--literal-pathspecs" ] && [ "$2" = "ls-files" ]'
    )
    wrapper.write_text(
        f'#!/bin/sh\nif {failure}; then\n  printf "failed\\n" > {shlex.quote(str(failure_marker))}\n'
        f'  exit 2\nfi\nexec {shlex.quote(executable)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    capsys.readouterr()

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged", "--fix", "--format", output_format]) == 2
    assert failure_marker.read_bytes() == b"failed\n"

    output = capsys.readouterr()
    if output_format in {"json", "sarif"}:
        assert json.loads(output.out)
        assert "cannot read staged files" in output.out
        assert not output.err
    else:
        assert "cannot read staged files" in output.err
    assert source.read_bytes() == original
    assert _index_snapshot(adopted_git_repo) == index_before


def _stage_hidden_index_source(repository: Path, name: str, flags: tuple[str, ...], *, dirty: bool) -> None:
    source = repository / name
    source.write_bytes(b"# ========\nvalue = 2\n")
    subprocess.run(("git", "--literal-pathspecs", "add", "--", name), cwd=repository, check=True)
    for flag in flags:
        subprocess.run(("git", "--literal-pathspecs", "update-index", flag, "--", name), cwd=repository, check=True)
    if dirty:
        source.write_bytes(b"# ========\nvalue = 3\n")


@dataclass(frozen=True, slots=True)
class _IndexSnapshot:
    staged_entries: bytes
    flags: bytes


def _index_snapshot(repository: Path) -> _IndexSnapshot:
    return _IndexSnapshot(
        staged_entries=subprocess.run(
            ("git", "ls-files", "--stage", "-z"), cwd=repository, check=True, capture_output=True
        ).stdout,
        flags=subprocess.run(("git", "ls-files", "-v", "-z"), cwd=repository, check=True, capture_output=True).stdout,
    )


@pytest.mark.parametrize("output_format", ["text", "json", "sarif"])
def test_staged_check_applies_native_fixes_leaving_the_index_for_review(
    adopted_git_repo: Path, capsys: pytest.CaptureFixture[str], output_format: str
) -> None:
    source = adopted_git_repo / "cleanup.py"
    original = b"# ========\n"
    source.write_bytes(original)
    subprocess.run(("git", "add", "cleanup.py"), cwd=adopted_git_repo, check=True)
    unrelated = adopted_git_repo / "untracked.py"
    unrelated.write_bytes(b"# ========\n")

    assert (
        cli.main(
            [
                "--root",
                str(adopted_git_repo),
                "check",
                "--staged",
                "--fix",
                "--format",
                output_format,
            ]
        )
        == 1
    )
    assert source.read_bytes().strip() == b""
    output = capsys.readouterr()
    if output_format == "text":
        assert "Review and stage" in output.err
    else:
        assert json.loads(output.out)
        assert "fix.review-required" in output.out
    assert (
        subprocess.run(("git", "show", ":cleanup.py"), cwd=adopted_git_repo, check=True, capture_output=True).stdout
        == original
    )
    assert unrelated.read_bytes() == original


def test_staged_fixes_validate_output_options_before_changing_source(
    adopted_git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = adopted_git_repo / "cleanup.py"
    original = b"# ========\n"
    source.write_bytes(original)
    subprocess.run(("git", "add", source.name), cwd=adopted_git_repo, check=True)
    assert (
        cli.main(
            [
                "--root",
                str(adopted_git_repo),
                "check",
                "--staged",
                "--fix",
                "--format",
                "github",
                "--output",
                "report.txt",
            ]
        )
        == 2
    )
    assert "--output is supported only" in capsys.readouterr().err
    assert source.read_bytes() == original
    assert (
        subprocess.run(("git", "show", ":cleanup.py"), cwd=adopted_git_repo, check=True, capture_output=True).stdout
        == original
    )


def test_staged_fix_limits_changes_to_explicitly_selected_index_paths(adopted_git_repo: Path) -> None:
    first = adopted_git_repo / "first.py"
    second = adopted_git_repo / "second.py"
    first.write_bytes(b"# ========\n")
    second.write_bytes(b"# ========\n")
    subprocess.run(("git", "add", first.name, second.name), cwd=adopted_git_repo, check=True)
    second.write_bytes(b"# ========\n# user work\n")
    assert cli.main(["--root", str(adopted_git_repo), "fix", "--staged", "--", first.name]) == 0
    assert first.read_bytes().strip() == b""
    assert second.read_bytes() == b"# ========\n# user work\n"


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
        eslint: bool = True,
    ) -> int:
        assert jobs == 2
        assert python_type_check
        assert eslint
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

    def healthy_adoption(_root: Path, _paths: Iterable[str], *, args: _Args) -> int:  # ruff: ignore[unused-function-argument] -- callback keyword must match the CLI boundary.
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


@pytest.mark.parametrize("command", ["check", "fix"])
@pytest.mark.parametrize("selection", ["deletion-only", "mixed", "explicit-deleted", "explicit-mixed"])
def test_staged_fixes_preserve_untracked_copies_of_index_deleted_files(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, command: str, selection: str
) -> None:
    repository = adopted_git_repo
    removed = repository / "source.py"
    subprocess.run(("git", "rm", "--cached", removed.name), cwd=repository, check=True, capture_output=True)
    original = b"# ========\n# retained user work\n"
    removed.write_bytes(original)
    unrelated = repository / "untracked.py"
    unrelated.write_bytes(original)
    cleanup = repository / "cleanup.py"
    mixed = selection in {"mixed", "explicit-mixed"}
    if mixed:
        cleanup.write_bytes(b"# ========\n")
        subprocess.run(("git", "add", cleanup.name), cwd=repository, check=True)
    index_before = subprocess.run(
        ("git", "ls-files", "--stage", "-z"), cwd=repository, check=True, capture_output=True
    ).stdout
    planned: list[tuple[str, ...]] = []
    checked: list[tuple[str, ...]] = []

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == repository
        assert trusted == (command == "fix")
        assert eslint
        planned.append(tuple(paths))
        return []

    def record_check(_root: Path, paths: Sequence[str] | None, **options: bool | int) -> int:
        assert options["staged"]
        checked.append(tuple(paths or ()))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- upstream tools are outside this native Git selection and source-fix regression.
        lifecycle, "selected_format_commands", commands
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- preserve the canonical gate boundary without launching project verification.
        cli, "_run_canonical_check", record_check
    )
    arguments = ["--root", str(repository), command, "--staged"]
    if command == "check":
        arguments.append("--fix")
    if selection.startswith("explicit"):
        arguments.extend(["--", removed.name, *([cleanup.name] if mixed else [])])

    assert cli.main(arguments) == (1 if command == "check" and mixed else 0)
    assert removed.read_bytes() == unrelated.read_bytes() == original
    assert planned == ([(str(cleanup),)] if mixed else [()] if command == "check" else [])
    assert checked == ([()] if command == "check" and not mixed else [])
    if mixed:
        assert cleanup.read_bytes().strip() == b""
    assert (
        subprocess.run(("git", "ls-files", "--stage", "-z"), cwd=repository, check=True, capture_output=True).stdout
        == index_before
    )
    assert (
        subprocess.run(
            ("git", "diff", "--cached", "--name-status", "-z", "--", removed.name),
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout
        == b"D\0source.py\0"
    )


@pytest.mark.parametrize("name", ["package.json", "removed.ts"])
def test_deleted_staged_metadata_still_triggers_repository_policy(
    adopted_git_repo: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    path = adopted_git_repo / name
    original = b"{}\n"
    path.write_bytes(original)
    subprocess.run(("git", "add", name), cwd=adopted_git_repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "metadata"),
        cwd=adopted_git_repo,
        check=True,
        env={},
    )
    subprocess.run(("git", "rm", "--cached", name), cwd=adopted_git_repo, check=True, capture_output=True)
    planned: list[tuple[str, ...]] = []
    routed: list[tuple[tuple[str, ...], bool | int, bool | int]] = []

    def commands(
        root: Path, paths: Iterable[str], *, trusted: bool = True, eslint: bool = True
    ) -> list[lifecycle.Command]:
        assert root == adopted_git_repo
        assert not trusted
        assert eslint
        planned.append(tuple(paths))
        return []

    def record_check(root: Path, paths: Sequence[str] | None, **options: bool | int) -> int:
        assert root == adopted_git_repo
        routed.append((tuple(paths or ()), options["staged"], options["react_doctor_triggered"]))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- upstream tools are outside this native deleted-metadata routing regression.
        lifecycle, "selected_format_commands", commands
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe canonical metadata routing without launching project verification.
        cli, "_run_canonical_check", record_check
    )

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged", "--fix"]) == 0
    assert planned == [()]
    assert routed == [((), True, True)]
    assert (
        subprocess.run(
            ("git", "diff", "--cached", "--name-only", "-z"),
            cwd=adopted_git_repo,
            check=True,
            capture_output=True,
        ).stdout
        == name.encode() + b"\0"
    )
    assert path.read_bytes() == original


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


@dataclass(frozen=True)
class _NumstatReply:
    data: bytes
    status: int
    binary_data: bytes
    binary_status: int


@dataclass(frozen=True)
class _NumstatCase:
    reply: _NumstatReply
    status: int
    error: str
    binary_calls: int
    flag_read: bool


def _configure_numstat_protocol_git(repository: Path, monkeypatch: pytest.MonkeyPatch, reply: _NumstatReply) -> Path:
    executable = shutil.which("git")
    assert executable is not None
    binaries = repository / ".git/protocol-bin"
    binaries.mkdir()
    markers = repository / ".git/protocol-markers"
    markers.mkdir()
    script = binaries / "git-protocol.py"
    script.write_text(
        "import os, sys\nfrom pathlib import Path\n"
        f"markers = Path({str(markers)!r})\n"
        "arguments = sys.argv[1:]\n"
        "if 'diff' in arguments and '--numstat' in arguments:\n"
        "    with (markers / 'numstat').open('ab') as stream:\n"
        "        stream.write(b'x')\n"
        f"    sys.stdout.buffer.write({reply.data!r})\n"
        f"    raise SystemExit({reply.status})\n"
        "if 'diff' in arguments and '--patch' in arguments:\n"
        "    with (markers / 'binary').open('ab') as stream:\n"
        "        stream.write(b'x')\n"
        f"    sys.stdout.buffer.write({reply.binary_data!r})\n"
        f"    raise SystemExit({reply.binary_status})\n"
        "if 'ls-files' in arguments and '-v' in arguments:\n"
        "    with (markers / 'flags').open('ab') as stream:\n"
        "        stream.write(b'x')\n"
        "environment = dict(os.environ)\n"
        "environment.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_SYSTEM': '/dev/null', "
        "'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_ATTR_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'})\n"
        f"os.execve({executable!r}, [{executable!r}, *arguments], environment)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        (binaries / "git.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        wrapper = binaries / "git"
        wrapper.write_text(f"#!{sys.executable}\n" + script.read_text(encoding="utf-8"), encoding="utf-8")
        wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    return markers


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(_NumstatCase(_NumstatReply(b"", 0, b"", 1), 0, "", 0, flag_read=True), id="empty"),
        pytest.param(
            _NumstatCase(_NumstatReply(b"", 1, b"", 1), 0, "", 0, flag_read=True), id="stat-only-empty-exit-one"
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"1\t1\trequirements-selected.in\0", 1, b"", 1),
                2,
                "files with unstaged content",
                0,
                flag_read=True,
            ),
            id="text-change",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"0\t0\trequirements-selected.in\0", 1, b"", 1),
                2,
                "files with unstaged content",
                0,
                flag_read=True,
            ),
            id="zero-zero-mode-metadata",
        ),
        pytest.param(
            _NumstatCase(_NumstatReply(b"-\t-\trequirements-selected.in\0", 1, b"", 1), 0, "", 1, flag_read=True),
            id="binary-canonical-empty-patch-exit-one",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"-\t-\trequirements-selected.in\0", 1, b"Binary files differ\n", 1),
                2,
                "files with unstaged content",
                1,
                flag_read=True,
            ),
            id="binary-different",
        ),
        pytest.param(
            _NumstatCase(_NumstatReply(b"-\t-\tunselected.bin\0", 1, b"must not run", 128), 0, "", 0, flag_read=True),
            id="unselected-binary-not-refined",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"1\t1\tunselected\ttab\nrequirements-selected.in\0", 1, b"", 1), 0, "", 0, flag_read=True
            ),
            id="literal-tabs-newline-preserved",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"1\t1\tunselected-\xff/requirements-selected.in\0", 1, b"", 1), 0, "", 0, flag_read=True
            ),
            id="native-nonutf8-path",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"-\t-\trequirements-selected.in\0-\t-\trequirements-selected.in\0", 1, b"", 1),
                0,
                "",
                1,
                flag_read=True,
            ),
            id="duplicate-binary-refined-once",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"-\t-\trequirements-selected.in\x000\t0\trequirements-selected.in\0", 1, b"", 1),
                2,
                "files with unstaged content",
                0,
                flag_read=True,
            ),
            id="mode-metadata-not-hidden-by-binary-duplicate",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"1\t1\trequirements-selected.in", 1, b"", 1),
                2,
                "cannot read staged files",
                0,
                flag_read=False,
            ),
            id="truncated-record",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"requirements-selected.in\0", 1, b"", 1),
                2,
                "cannot read staged files",
                0,
                flag_read=False,
            ),
            id="wrong-output-metadata",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"-\t1\trequirements-selected.in\0", 1, b"", 1),
                2,
                "cannot read staged files",
                0,
                flag_read=False,
            ),
            id="mixed-binary-numeric-metadata",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"x\t1\trequirements-selected.in\0", 1, b"", 1),
                2,
                "cannot read staged files",
                0,
                flag_read=False,
            ),
            id="nonnumeric-metadata",
        ),
        pytest.param(
            _NumstatCase(
                _NumstatReply(b"0\t0\t\0old.in\0new.in\0", 1, b"", 1), 2, "cannot read staged files", 0, flag_read=False
            ),
            id="unexpected-rename-framing",
        ),
        pytest.param(
            _NumstatCase(_NumstatReply(b"\0", 1, b"", 1), 2, "cannot read staged files", 0, flag_read=False),
            id="empty-path-record",
        ),
    ],
)
def test_staged_numstat_protocol_preserves_paths_and_read_errors(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: _NumstatCase,
) -> None:
    repository = adopted_git_repo
    selected = repository / "requirements-selected.in"
    selected.write_bytes(b"packaging==26.3\n")
    subprocess.run(("git", "add", selected.name), cwd=repository, check=True)
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    pending_index.write_bytes(ordinary_index.read_bytes())
    markers = _configure_numstat_protocol_git(repository, monkeypatch, case.reply)
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    working_before = selected.read_bytes()
    capsys.readouterr()

    assert cli.main(["--root", str(repository), "check", "--staged"]) == case.status

    output = capsys.readouterr()
    if case.error:
        assert case.error in output.err
        assert output.err.count(selected.name) <= 1
    else:
        assert not output.err
    binary_marker = markers / "binary"
    observed = binary_marker.read_bytes() if binary_marker.exists() else b""
    assert observed == b"x" * case.binary_calls
    assert (markers / "numstat").exists()
    assert (markers / "flags").exists() is case.flag_read
    assert selected.read_bytes() == working_before
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize(
    ("arguments", "output_format", "case"),
    [
        *[
            pytest.param(
                ("check", "--fix"),
                output_format,
                _NumstatCase(
                    _NumstatReply(b"-\t-\tsource.py\0x\t1\tother.py\0", 1, b"must not run", 128),
                    2,
                    "cannot read staged files",
                    0,
                    flag_read=False,
                ),
                id=f"malformed-before-fixes-{output_format}",
            )
            for output_format in ("text", "json", "sarif")
        ],
        *[
            pytest.param(
                ("check",),
                output_format,
                _NumstatCase(
                    _NumstatReply(b"not numstat", 128, b"must not run", 128),
                    2,
                    "cannot read staged files",
                    0,
                    flag_read=False,
                ),
                id=f"fatal-git-before-decoding-{output_format}",
            )
            for output_format in ("text", "json", "sarif")
        ],
        pytest.param(
            ("fix",),
            "text",
            _NumstatCase(
                _NumstatReply(b"-\t-\tsource.py\0", 1, b"nonempty does not override fatal status", 128),
                2,
                "cannot read staged files",
                1,
                flag_read=False,
            ),
            id="fatal-binary-before-fix-mutation",
        ),
    ],
)
def test_staged_native_input_errors_keep_error_contract_before_fixes(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    arguments: tuple[str, ...],
    output_format: str,
    case: _NumstatCase,
) -> None:
    repository = adopted_git_repo
    source = repository / "source.py"
    source.write_bytes(b"# ========\nvalue= ( 1 )\n")
    subprocess.run(("git", "add", source.name), cwd=repository, check=True)
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    pending_index.write_bytes(ordinary_index.read_bytes())
    markers = _configure_numstat_protocol_git(repository, monkeypatch, case.reply)
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    working_before = source.read_bytes()
    options = [*arguments, "--staged"]
    if output_format != "text":
        options.extend(["--format", output_format])
    capsys.readouterr()

    assert cli.main(["--root", str(repository), *options]) == 2

    output = capsys.readouterr()
    assert case.error in output.out + output.err
    assert "files with unstaged content" not in output.out + output.err
    if output_format != "text":
        assert json.loads(output.out)
        assert not output.err
    binary_marker = markers / "binary"
    observed = binary_marker.read_bytes() if binary_marker.exists() else b""
    assert observed == b"x" * case.binary_calls
    assert (markers / "numstat").exists()
    assert not (markers / "flags").exists()
    if case.reply.status not in {0, 1} or (case.reply.binary_status not in {0, 1} and case.binary_calls):
        assert "exit status 128" in output.out + output.err
        assert "malformed numstat output" not in output.out + output.err
    else:
        assert "malformed numstat output" in output.out + output.err
    assert source.read_bytes() == working_before
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize("pending", [False, True], ids=["ordinary-index", "pending-index"])
@pytest.mark.parametrize("representation", ["natural-binary", "forced-binary-filter"])
@pytest.mark.parametrize(
    ("state", "filemode", "dirty"),
    [
        pytest.param("canonical", True, False, id="canonical-equivalent"),
        pytest.param("dirty", True, True, id="content-change"),
        pytest.param("mode", True, True, id="mode-change"),
        pytest.param("mode", False, False, id="filemode-disabled"),
    ],
)
def test_staged_binary_git_comparison_respects_content_mode_and_literal_selection(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pending: bool,
    representation: str,
    state: str,
    filemode: bool,
    dirty: bool,
) -> None:
    repository = adopted_git_repo
    source = repository / "binary[1].bin"
    neighbor = repository / "binary1.bin"
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(pending_index))
    subprocess.run(("git", "read-tree", "HEAD"), cwd=repository, check=True)
    if not pending:
        monkeypatch.delenv("GIT_INDEX_FILE")
    for key, value in (("core.autocrlf", "false"), ("core.filemode", "true")):
        subprocess.run(("git", "config", key, value), cwd=repository, check=True)
    empty_attributes = repository / ".git/empty-global-attributes"
    empty_attributes.write_bytes(b"")
    subprocess.run(("git", "config", "core.attributesFile", str(empty_attributes)), cwd=repository, check=True)
    external_marker = repository / ".git/binary-external-called"
    external = repository / ".git/binary-external.py"
    external.write_text(
        f"from pathlib import Path\nPath({str(external_marker)!r}).write_bytes(b'called')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "config", "diff.external", shlex.join((sys.executable, str(external)))), cwd=repository, check=True
    )
    subprocess.run(("git", "config", "diff.trustExitCode", "true"), cwd=repository, check=True)
    canonical = b"\0base\n" if representation == "natural-binary" else b"base\n"
    if representation == "forced-binary-filter":
        cleaner = repository / ".git/binary-clean.py"
        cleaner.write_text(
            "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'# local annotation\\n', b''))\n",
            encoding="utf-8",
        )
        subprocess.run(
            ("git", "config", "filter.binary_fixture.clean", shlex.join((sys.executable, str(cleaner)))),
            cwd=repository,
            check=True,
        )
        subprocess.run(("git", "config", "filter.binary_fixture.required", "true"), cwd=repository, check=True)
        with (repository / ".git/info/attributes").open("a", encoding="utf-8") as stream:
            stream.write("*.bin -diff filter=binary_fixture\n")
    source.write_bytes(canonical)
    neighbor.write_bytes(canonical)
    subprocess.run(("git", "add", "--", source.name, neighbor.name), cwd=repository, check=True)
    neighbor.write_bytes(b"\0unselected-change\n" if representation == "natural-binary" else b"unselected-change\n")
    if state == "dirty":
        source.write_bytes(b"\0changed\n" if representation == "natural-binary" else b"# local annotation\nchanged\n")
    elif representation == "forced-binary-filter":
        source.write_bytes(b"# local annotation\nbase\n")
    if state == "mode":
        subprocess.run(("git", "update-index", "--chmod=+x", "--", source.name), cwd=repository, check=True)
    if not filemode:
        subprocess.run(("git", "config", "core.filemode", "false"), cwd=repository, check=True)
    metadata = source.stat()
    os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 17_000_000_000))
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    source_before = source.read_bytes()
    neighbor_before = neighbor.read_bytes()

    if dirty:
        with pytest.raises(ValueError, match="files with unstaged content"):
            cli.staged_fix_paths(repository, [source.name])
    else:
        assert cli.staged_fix_paths(repository, [source.name]) == [str(source)]

    assert not external_marker.exists()
    assert source.read_bytes() == source_before
    assert neighbor.read_bytes() == neighbor_before
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before


@pytest.mark.parametrize(
    "state",
    [
        "canonical-selected-path",
        "dirty-selected-path",
        "selected-filter-failure",
        "empty-selection",
    ],
)
def test_staged_primary_git_comparison_limits_literal_selected_scope(adopted_git_repo: Path, state: str) -> None:
    repository = adopted_git_repo
    source = repository / "selected[1].py"
    neighbor = repository / "selected1.py"
    empty_attributes = repository / ".git/empty-scope-attributes"
    empty_attributes.write_bytes(b"")
    subprocess.run(("git", "config", "core.attributesFile", str(empty_attributes)), cwd=repository, check=True)
    source.write_bytes(b"value = 1\n")
    neighbor.write_bytes(b"value = 1\n")
    subprocess.run(("git", "add", "--", source.name, neighbor.name), cwd=repository, check=True)
    neighbor.write_bytes(b"value = 2\n")
    if state == "dirty-selected-path":
        source.write_bytes(b"value = 2\n")
    marker = repository / ".git/scope-filter-called"
    cleaner = repository / ".git/scope-filter.py"
    cleaner.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_bytes(b'called')\nraise SystemExit(17)\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "config", "filter.scope_fixture.clean", shlex.join((sys.executable, str(cleaner)))),
        cwd=repository,
        check=True,
    )
    subprocess.run(("git", "config", "filter.scope_fixture.required", "true"), cwd=repository, check=True)
    with (repository / ".git/info/attributes").open("a", encoding="utf-8") as stream:
        stream.write("selected1.py filter=scope_fixture\n")
    ordinary_index = repository / ".git/index"
    pending_index = repository / ".git/pending-index"
    pending_index.write_bytes(ordinary_index.read_bytes())
    ordinary_before = ordinary_index.read_bytes()
    pending_before = pending_index.read_bytes()
    source_before = source.read_bytes()
    neighbor_before = neighbor.read_bytes()

    match state:
        case "selected-filter-failure":
            with pytest.raises(subprocess.CalledProcessError) as failure:
                cli.staged_fix_paths(repository, [neighbor.name])
            assert failure.value.returncode == 128
            assert marker.read_bytes() == b"called"
        case "dirty-selected-path":
            with pytest.raises(ValueError, match="files with unstaged content"):
                cli.staged_fix_paths(repository, [source.name])
            assert not marker.exists()
        case _:
            requested = ["not-staged.py"] if state == "empty-selection" else [source.name]
            expected = [] if state == "empty-selection" else [str(source)]
            assert cli.staged_fix_paths(repository, requested) == expected
            assert not marker.exists()

    assert source.read_bytes() == source_before
    assert neighbor.read_bytes() == neighbor_before
    assert ordinary_index.read_bytes() == ordinary_before
    assert pending_index.read_bytes() == pending_before
