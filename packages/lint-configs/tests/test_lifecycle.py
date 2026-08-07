from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.adoption import lifecycle, manifest, scaffold
from sarj_lint_configs.libs.adoption.packagemanager import PackageManager


if TYPE_CHECKING:
    from pathlib import Path


def _project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n", encoding="utf-8")
    (project / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    return project


def test_verification_uses_each_configured_python_project_environment(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='umbrella'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"extends": ".pyright-strict.json"}), encoding="utf-8")
    first = _project(tmp_path, "packages/first")
    second = _project(tmp_path, "packages/second")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert [command.cwd for command in commands] == [first, first, second, second]
    assert all(command.argv[:3] == ("uv", "run", "--project") for command in commands)
    assert {command.label for command in commands} == {"Ruff", "BasedPyright"}


def test_scoped_root_pyright_config_keeps_the_root_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    _ = _project(tmp_path, "packages/child")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert tmp_path in {command.cwd for command in commands}


def test_python_install_exact_pins_override_consumer_release_age_cutoffs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        manifest,
        "installed_versions",
        lambda: {"sarj-lint-configs": "1.2.3", "sarj-python-lint": "4.5.6"},
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    (command,) = lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none")

    assert command.argv == (
        "uv",
        "add",
        "--dev",
        "--exclude-newer-package",
        "sarj-lint-configs=2099-12-31",
        "--exclude-newer-package",
        "sarj-python-lint=2099-12-31",
        "sarj-lint-configs==1.2.3",
        "sarj-python-lint==4.5.6",
    )


def test_staged_eslint_uses_detected_project_cwd_and_package_manager(tmp_path: Path) -> None:
    project = tmp_path / "web"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@10.0.0"}),
        encoding="utf-8",
    )
    source = project / "src"
    source.mkdir()
    first = source / "name with spaces.ts"
    second = source / "component.tsx"
    first.write_text("export const value = 1;\n", encoding="utf-8")
    second.write_text("export const Component = () => null;\n", encoding="utf-8")

    commands = lifecycle.staged_eslint_commands(
        tmp_path,
        [str(second), "web/src/name with spaces.ts", str(first)],
    )

    assert len(commands) == 1
    assert commands[0].cwd == project
    assert commands[0].argv == (
        "pnpm",
        "exec",
        "eslint",
        "--",
        "src/component.tsx",
        "src/name with spaces.ts",
    )


def test_staged_eslint_omits_deletions_symlinks_and_unrelated_paths(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    source = tmp_path / "source.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    symlink = tmp_path / "linked.ts"
    symlink.symlink_to(source)
    outside = tmp_path.parent / "outside.ts"
    outside.write_text("export const outside = 1;\n", encoding="utf-8")

    commands = lifecycle.staged_eslint_commands(
        tmp_path,
        ["deleted.ts", "README.md", str(symlink), str(outside), "source.ts"],
    )

    assert len(commands) == 1
    assert commands[0].argv == ("npx", "--no-install", "eslint", "--", "source.ts")
    assert lifecycle.staged_eslint_commands(tmp_path, [str(symlink)]) == []


def test_staged_eslint_skips_detection_when_no_javascript_or_typescript_exists(tmp_path: Path) -> None:
    # Keep Markdown-only commits fast: ecosystem discovery can walk a large repository.
    markdown = tmp_path / "README.md"
    markdown.write_text("# Project\n", encoding="utf-8")

    commands = lifecycle.staged_eslint_commands(tmp_path, [str(markdown)])

    assert commands == []


def test_selected_eslint_accepts_source_directories_and_ignores_generated_trees(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "component.ts").write_text("export const value = 1;\n", encoding="utf-8")
    generated = tmp_path / "build"
    generated.mkdir()
    (generated / "ignored.ts").write_text("invalid !!\n", encoding="utf-8")

    commands = lifecycle.selected_eslint_commands(tmp_path, ["src", "build"])

    assert len(commands) == 1
    assert commands[0].argv == ("npx", "--no-install", "eslint", "--", "src")


def test_selected_eslint_partitions_sibling_projects_without_dropping_files(tmp_path: Path) -> None:
    selected: list[str] = []
    for name in ("a", "b"):
        project = tmp_path / name
        project.mkdir()
        (project / "package.json").write_text("{}\n", encoding="utf-8")
        (project / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
        source = project / "app.ts"
        source.write_text("export const value = 1;\n", encoding="utf-8")
        selected.append(str(source))

    commands = lifecycle.selected_eslint_commands(tmp_path, selected, label="analysis")

    assert [command.cwd for command in commands] == [tmp_path / "a", tmp_path / "b"]
    assert all(command.argv[-1] == "app.ts" for command in commands)


@pytest.mark.parametrize("root_has_package", [False, True])
def test_selected_eslint_keeps_a_directory_with_its_nested_project_owner(
    tmp_path: Path, *, root_has_package: bool
) -> None:
    if root_has_package:
        (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    (project / "package.json").write_text("{}\n", encoding="utf-8")
    (project / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (project / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    (project / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")

    commands = lifecycle.selected_eslint_commands(tmp_path, ["."], label="analysis")

    assert len(commands) == 1
    assert commands[0].cwd == project
    assert commands[0].argv[:4] == ("npx", "--no-install", "eslint", "--")
    assert set(commands[0].argv[4:]) == {"app.ts", "eslint.config.mjs"}


def test_staged_eslint_supports_every_eslint_module_suffix(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    names = [f"module{suffix}" for suffix in (".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx")]
    for name in names:
        (tmp_path / name).write_text("export const value = 1;\n", encoding="utf-8")

    commands = lifecycle.staged_eslint_commands(tmp_path, names)

    assert commands[0].argv == ("npx", "--no-install", "eslint", "--", *names)


def test_staged_eslint_uses_npm_by_default(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    source = tmp_path / "source.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    command = lifecycle.staged_eslint_commands(tmp_path, ["source.ts"])[0]

    assert scaffold.detect(tmp_path).client is PackageManager.NPM
    assert command.argv[:3] == ("npx", "--no-install", "eslint")
