from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_standards.libs.adoption import lifecycle, manifest, scaffold
from sarj_standards.libs.adoption.packagemanager import PackageManager


def _project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n", encoding="utf-8")
    (project / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    return project


def test_verification_uses_isolated_tool_binaries_in_each_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='umbrella'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"extends": ".pyright-strict.json"}), encoding="utf-8")
    first = _project(tmp_path, "packages/first")
    second = _project(tmp_path, "packages/second")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert [command.cwd for command in commands] == [first, first, second, second]
    assert {Path(command.argv[0]).stem for command in commands} == {"ruff", "basedpyright"}
    assert {command.label for command in commands} == {"Ruff", "BasedPyright"}


def test_scoped_root_pyright_config_keeps_the_root_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    _ = _project(tmp_path, "packages/child")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert tmp_path in {command.cwd for command in commands}


def test_fix_uses_the_isolated_ruff_without_requiring_a_consumer_lockfile(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.format_commands(ecosystems)

    assert [command.label for command in commands] == ["Ruff format", "Ruff fixes"]
    assert {Path(command.argv[0]).stem for command in commands} == {"ruff"}
    assert commands[0].argv[1:] == ("format", ".")
    assert commands[1].argv[1:] == ("check", "--fix", ".")
    assert all("--frozen" not in command.argv for command in commands)


def test_selected_fix_routes_only_the_requested_python_and_typescript_files(tmp_path: Path) -> None:
    python_file = tmp_path / "service.py"
    python_file.write_text("value=1\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    typescript_file = tmp_path / "view.ts"
    typescript_file.write_text("export const value = 1;\n", encoding="utf-8")

    commands = lifecycle.selected_format_commands(tmp_path, (str(python_file), str(typescript_file)))

    assert [command.label for command in commands[:2]] == ["Ruff format", "Ruff fixes"]
    assert commands[0].argv[-1] == "service.py"
    assert commands[1].argv[-1] == "service.py"
    assert commands[2].argv[-3:] == ("--fix", "--", "view.ts")


def test_setup_never_mutates_the_consumer_dependency_environment(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "old-python-app"\nrequires-python = ">=3.10"\n'
        '\n[dependency-groups]\ndev = ["sarj-standards==1.2.3"]\n',
        encoding="utf-8",
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    assert lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none") == []


def test_setup_does_not_install_standards_into_a_consumer_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "old-python-app"\nrequires-python = ">=3.10"\n', encoding="utf-8"
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    assert lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none") == []


@pytest.mark.parametrize("python", [True, False])
def test_precommit_install_is_explicitly_scoped_to_commit_stage(tmp_path: Path, python: bool) -> None:
    (tmp_path / ".git").mkdir()
    ecosystems = scaffold.Ecosystems(python, not python, python_root=tmp_path if python else None)

    command = lifecycle.install_commands(tmp_path, ecosystems)[-1]

    assert command.argv[-4:] == ("pre-commit", "install", "--hook-type", "pre-commit")


def test_precommit_install_skips_linked_worktree_gitfile(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/fixture\n", encoding="utf-8")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    assert lifecycle.install_commands(tmp_path, ecosystems) == []


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
    assert commands[0].argv == ("npm", "exec", "--offline", "--", "eslint", "--", "source.ts")
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
    assert commands[0].argv == ("npm", "exec", "--offline", "--", "eslint", "--", "src")


@pytest.mark.parametrize("agent_root", [".agents", ".claude"])
def test_selected_eslint_excludes_skill_payloads_but_keeps_agent_tools(tmp_path: Path, agent_root: str) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    skill = tmp_path / agent_root / "skills" / "sarj-build" / "shared" / "helper.ts"
    skill.parent.mkdir(parents=True)
    skill.write_text("export const template = true;\n", encoding="utf-8")
    tool = tmp_path / agent_root / "tools" / "render.ts"
    tool.parent.mkdir(parents=True)
    tool.write_text("export const render = true;\n", encoding="utf-8")

    directory_selection = lifecycle.select_eslint_commands(tmp_path, ["."], label="analysis")
    explicit_selection = lifecycle.select_eslint_commands(tmp_path, [str(skill), str(tool)], label="analysis")

    assert len(directory_selection.commands) == 1
    assert directory_selection.commands[0].argv[-1] == f"{agent_root}/tools/render.ts"
    assert directory_selection.unowned_count == 0
    assert len(explicit_selection.commands) == 1
    assert explicit_selection.commands[0].argv[-1] == f"{agent_root}/tools/render.ts"
    assert explicit_selection.unowned_count == 0


def test_selected_eslint_excludes_nested_skill_payloads(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    skill = tmp_path / "workspace" / "sample" / ".agents" / "skills" / "shared" / "template.ts"
    skill.parent.mkdir(parents=True)
    skill.write_text("export const template = true;\n", encoding="utf-8")
    source = tmp_path / "workspace" / "sample" / "app.ts"
    source.write_text("export const app = true;\n", encoding="utf-8")

    directory_selection = lifecycle.select_eslint_commands(tmp_path, ["."], label="analysis")
    explicit_selection = lifecycle.select_eslint_commands(tmp_path, [str(skill)], label="analysis")

    assert len(directory_selection.commands) == 1
    assert directory_selection.commands[0].argv[-1] == "workspace/sample/app.ts"
    assert explicit_selection == lifecycle.EslintSelection((), 0)


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


def test_eslint_selection_keeps_owned_projects_when_other_files_are_unowned(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    (project / "package.json").write_text("{}\n", encoding="utf-8")
    (project / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    owned = project / "app.ts"
    owned.write_text("export const value = 1;\n", encoding="utf-8")
    unowned = tmp_path / "tool.ts"
    unowned.write_text("export const tool = 1;\n", encoding="utf-8")

    selection = lifecycle.select_eslint_commands(
        tmp_path,
        [str(owned), str(unowned)],
        label="analysis",
    )

    assert len(selection.commands) == 1
    assert selection.commands[0].cwd == project
    assert selection.unowned_count == 1


def test_eslint_selection_routes_root_scripts_to_the_adopted_nested_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"root"}\n', encoding="utf-8")
    project = tmp_path / "typescript"
    project.mkdir()
    (project / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    (project / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (project / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = scripts / "release.mjs"
    source.write_text("export const release = true;\n", encoding="utf-8")
    adopted = manifest.Manifest(
        "5.6.8",
        ("eslint", "markdownlint", "taplo", "yamllint"),
        ".",
        "typescript",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    selection = lifecycle.select_eslint_commands(tmp_path, [str(source)], label="analysis")

    assert selection.unowned_count == 0
    assert len(selection.commands) == 1
    assert selection.commands[0].cwd == project
    assert selection.commands[0].argv == (
        "npm",
        "exec",
        "--offline",
        "--",
        "eslint",
        "--config",
        "eslint.config.mjs",
        "--",
        "../scripts/release.mjs",
    )


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
    assert commands[0].argv[:7] == ("npm", "exec", "--offline", "--", "eslint", "--config", "eslint.config.mjs")
    assert set(commands[0].argv[8:]) == {"app.ts", "eslint.config.mjs"}


def test_staged_eslint_supports_every_eslint_module_suffix(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    names = [f"module{suffix}" for suffix in (".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx")]
    for name in names:
        (tmp_path / name).write_text("export const value = 1;\n", encoding="utf-8")

    commands = lifecycle.staged_eslint_commands(tmp_path, names)

    assert commands[0].argv == ("npm", "exec", "--offline", "--", "eslint", "--", *names)


def test_staged_eslint_uses_npm_by_default(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    source = tmp_path / "source.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    command = lifecycle.staged_eslint_commands(tmp_path, ["source.ts"])[0]

    assert scaffold.detect(tmp_path).client is PackageManager.NPM
    assert command.argv[:5] == ("npm", "exec", "--offline", "--", "eslint")
