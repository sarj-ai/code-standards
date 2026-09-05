from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sarj_standards.libs.linting import runner


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class _LoadedTool(NamedTuple):
    checker: Callable[[list[str]], int]
    registry: Mapping[str, type[object]]


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


@pytest.mark.parametrize("name", ["routing.tftest.hcl", "routing.tftest.json"])
def test_terraform_test_files_route_to_iac(name: str, tmp_path: Path) -> None:
    source = tmp_path / name
    source.write_text("{}\n", encoding="utf-8")

    assert runner.group_paths([str(tmp_path)]).iac == [str(source)]


def test_shell_files_route_to_shellcheck_and_text(tmp_path: Path) -> None:
    shell = tmp_path / "release"
    shell.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    zsh = tmp_path / "interactive.zsh"
    zsh.write_text("#!/bin/zsh\nprint ok\n", encoding="utf-8")

    grouped = runner.group_paths([str(tmp_path)])

    assert grouped.shellcheck == [str(shell)]
    assert grouped.unsupported_shell == [str(zsh)]
    assert grouped.text == [str(zsh), str(shell)]


@pytest.mark.parametrize("filename", ["service.py", "service.pyi"], ids=("implementation", "stub"))
def test_python_sources_route_from_explicit_directory_and_staged_inputs(tmp_path: Path, filename: str) -> None:
    source = tmp_path / filename
    source.write_text("def parse(value: str) -> int: ...\n", encoding="utf-8")

    assert runner.group_paths([str(source)]).python == [str(source)]
    assert runner.group_paths([str(tmp_path)]).python == [str(source)]
    assert runner.accepts_hook_path(source, root=tmp_path)


@pytest.mark.parametrize("directory", ["vendor", ".venv", ".agents/skills/tool"], ids=("vendor", "venv", "skill"))
def test_stub_discovery_and_staged_routing_preserve_excluded_trees(tmp_path: Path, directory: str) -> None:
    source = tmp_path / directory / "service.pyi"
    source.parent.mkdir(parents=True)
    source.write_text("def parse(value: str) -> int: ...\n", encoding="utf-8")

    assert not runner.group_paths([str(tmp_path)]).python
    assert not runner.accepts_hook_path(source, root=tmp_path)


def test_generated_stub_is_not_explicitly_routed_or_staged(tmp_path: Path) -> None:
    source = tmp_path / "service.pyi"
    source.write_text("# AUTO-GENERATED; DO NOT EDIT\ndef parse(value: str) -> int: ...\n", encoding="utf-8")

    assert not runner.group_paths([str(source)]).python
    assert not runner.accepts_hook_path(source, root=tmp_path)


def test_stub_selects_native_python_checker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "service.pyi"
    source.write_text("def parse(value: str) -> int: ...\n", encoding="utf-8")
    seen: list[tuple[str, list[str]]] = []

    def load_tool(package: str) -> _LoadedTool:
        def checker(argv: list[str]) -> int:
            seen.append((package, argv))
            return 1

        return _LoadedTool(checker, {"example-rule": object})

    monkeypatch.setattr(runner, "_load_tool", load_tool)

    assert runner.run([str(source)]) == 1
    assert seen == [("sarj_python_lint", ["check", "--rule", "example-rule", "--", str(source)])]


def test_valid_stub_keeps_native_rule_stub_exceptions(tmp_path: Path) -> None:
    source = tmp_path / "service.pyi"
    source.write_text('__all__ = ["parse"]\n\ndef parse(value: str) -> int: ...\n', encoding="utf-8")

    assert runner.run([str(source)]) == 0


def test_directory_walk_prunes_ignored_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ignored_source = tmp_path / "node_modules" / "package" / "ignored.py"
    ignored_source.parent.mkdir(parents=True)
    ignored_source.touch()
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.touch()
    visited: list[str] = []
    real_walk = os.walk

    def recording_walk(
        top: Path,
        *,
        topdown: bool,
        followlinks: bool,
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        for root, dir_names, file_names in real_walk(
            top,
            topdown=topdown,
            followlinks=followlinks,
        ):
            visited.append(str(root))
            yield root, dir_names, file_names

    monkeypatch.setattr(os, "walk", recording_walk)

    assert runner.group_paths([str(tmp_path)]).python == [str(source)]
    assert not any("node_modules" in root for root in visited)


@pytest.mark.parametrize("agent_root", [".agents", ".claude"])
def test_skill_payloads_are_excluded_but_agent_tools_remain_owned(tmp_path: Path, agent_root: str) -> None:
    skill = tmp_path / agent_root / "skills" / "sarj-build" / "shared" / "helper.py"
    skill.parent.mkdir(parents=True)
    skill.write_text("raise RuntimeError\n", encoding="utf-8")
    tool = tmp_path / agent_root / "tools" / "render.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("VALUE = 1\n", encoding="utf-8")

    assert runner.group_paths([str(tmp_path)]).python == [str(tool)]
    assert runner.group_paths([str(tmp_path / agent_root)]).python == [str(tool)]
    assert runner.group_paths([str(skill)]).python == []
    assert runner.group_paths([str(skill.parents[1])]).python == []
    assert not runner.accepts_hook_path(skill)
    assert runner.accepts_hook_path(tool)


def test_directory_walk_rejects_oversized_discovered_files_truthfully(tmp_path: Path) -> None:
    large = tmp_path / "large.py"
    large.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    small = tmp_path / "small.py"
    small.touch()

    with pytest.raises(ValueError, match="2 MiB analysis limit"):
        runner.group_paths([str(tmp_path)])


def test_directory_walk_skips_verified_generated_large_source(tmp_path: Path) -> None:
    generated = tmp_path / "landbank.ts"
    generated.write_bytes(b"// AUTO-GENERATED by tools/seed.py; do not hand-edit.\n" + b"x" * (2 * 1024 * 1024))
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    assert runner.group_paths([str(tmp_path)]).typescript == [str(source)]


def test_directory_walk_skips_generated_names_and_backup_trees(tmp_path: Path) -> None:
    generated = tmp_path / "routeTree.gen.ts"
    generated.write_text("export const generated = true;\n", encoding="utf-8")
    backup = tmp_path / "_backups" / "restore.sql"
    backup.parent.mkdir()
    backup.write_text("SELECT 1;\n", encoding="utf-8")
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    grouped = runner.group_paths([str(tmp_path)])

    assert grouped.typescript == [str(source)]
    assert not grouped.sql


def test_hook_routing_skips_unsupported_and_conventionally_generated_paths(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    generated = tmp_path / "routeTree.gen.ts"
    config = tmp_path / "pyrightconfig.json"

    assert runner.accepts_hook_path(source)
    assert not runner.accepts_hook_path(generated)
    assert not runner.accepts_hook_path(config)


def test_directory_walk_preserves_oversized_markdown_for_artifact_rule(tmp_path: Path) -> None:
    large = tmp_path / "audit-report.md"
    large.write_bytes(b"# Findings\n" + b"word " * (110 * 1024))

    assert runner.group_paths([str(tmp_path)]).text == [str(large)]


def test_directory_walk_prunes_playwright_mcp_artifacts(tmp_path: Path) -> None:
    generated = tmp_path / ".playwright-mcp" / "page-2026-08-04.yml"
    generated.parent.mkdir()
    generated.write_text("generated: true\n")
    source = tmp_path / "config.yml"
    source.write_text("maintained: true\n")

    assert runner.group_paths([str(tmp_path)]).iac == [str(source)]


def test_directory_walk_skips_secret_env_files_but_explicit_inputs_remain_checkable(tmp_path: Path) -> None:
    secret = tmp_path / ".env.mcp"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")
    example = tmp_path / ".env.example"
    example.write_text("TOKEN=\n", encoding="utf-8")

    assert runner.group_paths([str(tmp_path)]).text == [str(example)]
    assert runner.group_paths([str(secret)]).text == [str(secret)]


@pytest.mark.parametrize(
    ("name", "limit_mib"),
    [("large.py", 2), ("audit-report.md", 16)],
    ids=("source", "markdown"),
)
def test_explicit_oversized_file_is_rejected_truthfully(tmp_path: Path, name: str, limit_mib: int) -> None:
    large = tmp_path / name
    large.write_bytes(b"x" * (limit_mib * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match=rf"{limit_mib} MiB analysis limit"):
        runner.group_paths([str(large)])


def test_overlapping_inputs_route_each_file_once(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    source = package / "app.py"
    source.touch()

    grouped = runner.group_paths([str(package), str(tmp_path), str(source), str(tmp_path)])

    assert grouped.python == [str(tmp_path / "package" / "app.py")]


def test_directory_walk_stats_only_supported_file_types(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.py"
    source.touch()
    unsupported = tmp_path / "image.png"
    unsupported.touch()
    real_stat = os.stat
    stat_paths: list[str] = []

    def recording_stat(path: os.PathLike[str] | str, *args: object, **kwargs: object) -> os.stat_result:
        stat_paths.append(os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", recording_stat)

    assert runner.group_paths([str(tmp_path)]).python == [str(source)]
    assert str(unsupported) not in stat_paths


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


def test_mobile_sources_are_grouped_for_staged_analyzers(tmp_path: Path) -> None:
    swift = tmp_path / "AccountView.swift"
    kotlin = tmp_path / "AccountView.kt"
    gradle_script = tmp_path / "build.gradle.kts"
    for source in (swift, kotlin, gradle_script):
        source.touch()

    grouped = runner.group_paths([str(swift), str(kotlin), str(gradle_script)])

    assert grouped.swift == [str(swift)]
    assert grouped.kotlin == [str(kotlin), str(gradle_script)]
    assert runner.accepts_hook_path(swift)
    assert runner.accepts_hook_path(kotlin)
    assert runner.accepts_hook_path(gradle_script)


@pytest.mark.parametrize(
    "name",
    ["Model.generated.swift", "Model.gen.kt", "BuildConfig.generated.kts"],
)
def test_generated_mobile_sources_are_not_routed_or_hooked(name: str, tmp_path: Path) -> None:
    source = tmp_path / name
    source.touch()

    assert runner.group_paths([str(source)]) == runner.GroupedPaths()
    assert not runner.accepts_hook_path(source)


@pytest.mark.parametrize("relative", ["build/generated/Model.kt", "Pods/SDK/Model.swift", "vendor/Model.kt"])
def test_mobile_sources_in_ignored_directories_are_explicit_only_and_not_hooked(relative: str, tmp_path: Path) -> None:
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("// generated or vendored\n", encoding="utf-8")
    grouped = runner.group_paths([str(source)])
    selected = grouped.kotlin if source.suffix == ".kt" else grouped.swift
    assert selected == [str(source)]
    assert not runner.accepts_hook_path(source, root=tmp_path)


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
        [sys.executable, "-m", "sarj_standards", "check", "missing.py"],
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
    ) -> _LoadedTool:
        return _LoadedTool(fake_checker, {"example-rule": object})

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--baseline=.evil.py").touch()

    assert runner.run(["--baseline=.evil.py"]) == 0
    assert argv_seen[-2:] == ["--", "--baseline=.evil.py"]


def test_run_imports_only_registries_with_routed_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    loaded: list[str] = []

    def fake_load_tool(
        package: str,
    ) -> _LoadedTool:
        def checker(_argv: list[str]) -> int:
            return 0

        loaded.append(package)
        return _LoadedTool(checker, {"example-rule": object})

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    migration = tmp_path / "migration.sql"
    migration.touch()

    assert runner.run([str(migration)]) == 0
    assert loaded == ["sarj_sql_lint"]


def test_noise_only_imports_sql_registry_for_comment_cruft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    loaded: list[str] = []

    def fake_load(
        package: str,
    ) -> _LoadedTool:
        loaded.append(package)

        def checker(_argv: list[str]) -> int:
            return 0

        return _LoadedTool(checker, {"no-comment-cruft": object})

    monkeypatch.setattr(
        runner,
        "_load_tool",
        fake_load,
    )
    migration = tmp_path / "migration.sql"
    migration.touch()

    assert runner.run([str(migration)], noise_only=True) == 0
    assert loaded == ["sarj_sql_lint"]


def test_python_baseline_is_forwarded_only_to_python_checker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv_by_package: dict[str, list[str]] = {}

    def fake_load_tool(
        package: str,
    ) -> _LoadedTool:
        def checker(argv: list[str]) -> int:
            argv_by_package[package] = argv
            return 0

        return _LoadedTool(checker, {"example-rule": object})

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


def test_create_python_baseline_uses_all_python_rules_and_update_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv_seen: list[str] = []

    def fake_load_tool(
        _package: str,
    ) -> _LoadedTool:
        def checker(argv: list[str]) -> int:
            argv_seen.extend(argv)
            return 0

        return _LoadedTool(checker, {"rule-b": object, "rule-a": object})

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    source = tmp_path / "app.py"
    source.touch()

    assert runner.create_python_baseline([str(source)], str(tmp_path / "baseline.json")) == 0
    assert argv_seen[:7] == [
        "check",
        "--rule",
        "rule-a",
        "--rule",
        "rule-b",
        "--update-baseline",
        str(tmp_path / "baseline.json"),
    ]


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
    ) -> _LoadedTool:
        return _LoadedTool(checker, {})

    monkeypatch.setattr(runner, "_load_tool", fake_load_tool)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "migration.sql").touch()
    assert runner.run(["migration.sql"], noise_only=True) == 0


def test_noise_only_selects_comment_and_docstring_rules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selected: list[set[str]] = []

    def fake_load_tool(
        package: str,
    ) -> _LoadedTool:
        def checker(_argv: list[str]) -> int:
            return 0

        match package:
            case "sarj_python_lint":
                registry = {
                    "no-comment-cruft": object,
                    "no-restated-comment": object,
                    "no-secret-in-log": object,
                }
            case "sarj_sql_lint":
                registry = {"no-comment-cruft": object, "idempotent-ddl": object}
            case "sarj_iac_lint":
                registry = {
                    "no-comment-cruft": object,
                    "no-restated-comment": object,
                    "require-deletion-protection": object,
                }
            case _:
                registry = {"idempotent-ddl": object}
        return _LoadedTool(checker, registry)

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
        {"no-comment-cruft"},
        {"no-comment-cruft", "no-restated-comment"},
    ]


def test_fresh_repo_runs_clean_file(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("VALUE = 1\n")
    environment = dict(os.environ)  # ruff: ignore[banned-api] -- make analyzer discovery match the test interpreter.
    environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "check", "example.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_directory_argument_cannot_false_green(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text("def test_truth() -> None:\n    assert True\n")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").symlink_to(sys.executable)
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "check", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "input escapes repository root" in proc.stderr
