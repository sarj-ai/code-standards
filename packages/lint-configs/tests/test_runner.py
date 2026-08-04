"""Unit and fresh-repository tests for the all-rules command."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import runner


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path


def test_directories_expand_by_suffix_and_skip_generated_trees(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('"""Application."""\n')
    (tmp_path / "migration.sql").write_text("SELECT 1;\n")
    (tmp_path / "main.tf").write_text("terraform {}\n")
    cache = tmp_path / ".uv-cache" / "archive"
    cache.mkdir(parents=True)
    (cache / "bundled.py").write_text("raise RuntimeError\n")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").symlink_to(sys.executable)

    grouped = runner.group_paths([str(tmp_path)])
    assert grouped == runner.GroupedPaths(
        python=[str(tmp_path / "app.py")],
        sql=[str(tmp_path / "migration.sql")],
        iac=[str(tmp_path / "main.tf")],
        text=[],
    )


def test_ignored_ancestor_name_does_not_hide_requested_tree(tmp_path: Path) -> None:
    project = tmp_path / "vendor" / "project"
    project.mkdir(parents=True)
    source = project / "app.py"
    source.touch()

    assert runner.group_paths([str(project)]).python == [str(source)]


def test_mixed_files_are_grouped_by_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("app.py", "migration.SQL", "main.tf", "values.yaml", "README.md"):
        (tmp_path / name).touch()
    grouped = runner.group_paths(["app.py", "migration.SQL", "main.tf", "values.yaml", "README.md"])
    assert grouped == runner.GroupedPaths(
        python=["app.py"],
        sql=["migration.SQL"],
        iac=["main.tf", "values.yaml"],
        text=["values.yaml", "README.md"],
    )


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text('"""Target."""\n')
    link = tmp_path / "link.py"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="refusing symlink input"):
        runner.group_paths([str(link)])


def test_symlinks_inside_a_requested_tree_are_skipped(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text('"""Target."""\n')
    (tmp_path / "linked.py").symlink_to(target)

    assert runner.group_paths([str(tmp_path)]).python == [str(target)]


def test_missing_input_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="input does not exist"):
        runner.group_paths([str(tmp_path / "missing.py")])


def test_missing_cli_input_fails_without_traceback(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "check", "missing.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "input does not exist" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_checker_file_list_is_protected_from_option_injection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv_seen: list[str] = []

    def fake_checker(argv: list[str]) -> int:
        argv_seen.extend(argv)
        return 0

    def fake_load_tool(
        _package: str,
    ) -> tuple[Callable[[list[str]], int], Mapping[str, type[object]]]:
        return fake_checker, {"example-rule": object}

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--baseline=.evil.py").touch()

    assert runner.run(["--baseline=.evil.py"]) == 0
    assert argv_seen[-2:] == ["--", "--baseline=.evil.py"]


def test_python_baseline_is_forwarded_only_to_python_checker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv_by_package: dict[str, list[str]] = {}

    def fake_load_tool(
        package: str,
    ) -> tuple[Callable[[list[str]], int], Mapping[str, type[object]]]:
        def checker(argv: list[str]) -> int:
            argv_by_package[package] = argv
            return 0

        return checker, {"example-rule": object}

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.chdir(tmp_path)
    for name in ("app.py", "migration.sql", "main.tf"):
        (tmp_path / name).touch()

    assert (
        runner.run(
            ["app.py", "migration.sql", "main.tf"],
            python_baseline="python/sarj-standards-baseline.json",
        )
        == 0
    )
    assert argv_by_package["sarj_python_lint"][-4:] == [
        "--baseline",
        "python/sarj-standards-baseline.json",
        "--",
        "app.py",
    ]
    assert "--baseline" not in argv_by_package["sarj_sql_lint"]
    assert "--baseline" not in argv_by_package["sarj_iac_lint"]


def test_highest_status_is_propagated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    statuses = iter((1, 2, 0))

    def fake_run(
        _checker: Callable[[list[str]], int],
        _registry: Mapping[str, type[object]],
        _files: Sequence[str],
        *,
        extra_args: Sequence[str] = (),
    ) -> int:
        _ = extra_args
        return next(statuses)

    def clean_text(_files: Sequence[str]) -> int:
        return 0

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner.textlint, "run", clean_text)
    monkeypatch.chdir(tmp_path)
    for name in ("app.py", "migration.sql", "main.tf"):
        (tmp_path / name).touch()
    assert runner.run(["app.py", "migration.sql", "main.tf"]) == 2


def test_empty_rule_selection_skips_checker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def checker(_argv: list[str]) -> int:
        pytest.fail("checker must not run without selected rules")

    def fake_load_tool(
        _package: str,
    ) -> tuple[Callable[[list[str]], int], Mapping[str, type[object]]]:
        return checker, {}

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "migration.sql").touch()
    assert runner.run(["migration.sql"], noise_only=True) == 0


def test_noise_only_selects_comment_and_docstring_rules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selected: list[set[str]] = []

    def fake_load_tool(
        package: str,
    ) -> tuple[Callable[[list[str]], int], Mapping[str, type[object]]]:
        if package == "sarj_python_lint":
            registry = {
                "no-comment-cruft": object,
                "no-restated-comment": object,
                "no-secret-in-log": object,
            }
        elif package == "sarj_iac_lint":
            registry = {"no-comment-cruft": object, "require-deletion-protection": object}
        else:
            registry = {"idempotent-ddl": object}
        return lambda _argv: 0, registry

    def capture_rules(
        _checker: Callable[[list[str]], int],
        registry: Mapping[str, type[object]],
        _files: Sequence[str],
        *,
        extra_args: Sequence[str] = (),
    ) -> int:
        _ = extra_args
        selected.append(set(registry))
        return 0

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.setattr(runner, "_run", capture_rules)
    monkeypatch.chdir(tmp_path)
    for name in ("app.py", "migration.sql", "main.tf"):
        (tmp_path / name).touch()

    assert runner.run(["app.py", "migration.sql", "main.tf"], noise_only=True) == 0
    assert selected == [
        {"no-comment-cruft", "no-restated-comment"},
        set(),
        {"no-comment-cruft"},
    ]


def test_fresh_repo_runs_clean_file(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text('"""Example module."""\n\nVALUE = 1\n')
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "check", "example.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_directory_argument_cannot_false_green(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text("def test_truth() -> None:\n    assert True\n")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").symlink_to(sys.executable)
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "check", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "SARJ" in proc.stdout
