from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import lifecycle


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
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

    def unexpected_health(_root: Path, _paths: object, *, args: object) -> int:  # ruff: ignore[unused-function-argument] -- match the public staged health callback keyword.
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
def test_staged_index_flag_read_failure_preserves_structured_input_errors(
    adopted_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
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
    wrapper.write_text(
        '#!/bin/sh\nif [ "$1" = "--literal-pathspecs" ] && [ "$2" = "ls-files" ]; then\n  exit 2\nfi\n'
        f'exec {shlex.quote(executable)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    capsys.readouterr()

    assert cli.main(["--root", str(adopted_git_repo), "check", "--staged", "--fix", "--format", output_format]) == 2

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
