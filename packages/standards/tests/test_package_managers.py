from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import lifecycle, manifest, packagemanager, scaffold
from sarj_standards.libs.adoption.packagemanager import PackageManager, YarnVariant


if TYPE_CHECKING:
    from pathlib import Path


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    command = list(args)
    if command and command[0] == "init":
        command[0] = "setup"
    if command and command[0] == "setup" and "--no-install" not in command:
        command.append("--no-install")
    if "--dest" in command:
        index = command.index("--dest")
        root = command[index + 1]
        del command[index : index + 2]
        command[0:0] = ["--root", root]
    return subprocess.run(
        [sys.executable, "-m", "sarj_standards", *command],
        capture_output=True,
        text=True,
        check=False,
    )


def _project(root: Path, lockfile: str, package_json: dict[str, object] | None = None) -> Path:
    _ = (root / "package.json").write_text(
        json.dumps(package_json or {"name": "web"}, indent=2) + "\n", encoding="utf-8"
    )
    _ = (root / lockfile).write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("lockfile", "expected"),
    [
        ("pnpm-lock.yaml", PackageManager.PNPM),
        ("yarn.lock", PackageManager.YARN),
        ("bun.lock", PackageManager.BUN),
        ("bun.lockb", PackageManager.BUN),
        ("package-lock.json", PackageManager.NPM),
    ],
)
def test_the_lockfile_names_the_client(tmp_path: Path, lockfile: str, expected: PackageManager) -> None:
    assert packagemanager.detect(_project(tmp_path, lockfile)) == expected


def test_a_repo_with_no_lockfile_is_assumed_to_be_npm(tmp_path: Path) -> None:
    _ = (tmp_path / "package.json").write_text('{"name": "web"}\n', encoding="utf-8")
    assert packagemanager.detect(tmp_path) == PackageManager.NPM


def test_the_packagemanager_field_beats_a_stray_lockfile(tmp_path: Path) -> None:
    root = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "yarn@4.15.0"})
    assert packagemanager.detect(root) == PackageManager.YARN


def test_an_unsupported_declared_package_manager_fails_closed(tmp_path: Path) -> None:
    root = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "deno@2.4.0"})

    with pytest.raises(ValueError, match=r"unsupported packageManager 'deno@2\.4\.0'"):
        packagemanager.detect(root)

    proc = _cli("init", "--dest", str(root))
    assert proc.returncode == 2
    assert "supported managers: npm, pnpm, yarn, bun" in proc.stderr


def test_npm_keeps_the_nested_form_with_resolved_root_references() -> None:
    overrides = packagemanager.overrides_for(PackageManager.NPM)
    assert overrides.key_path == ("overrides",)
    assert overrides.entries["eslint-plugin-react"] == {"eslint": manifest.eslint_peers()["eslint"]}
    assert "$" not in json.dumps(overrides.as_document())


def test_pnpm_gets_a_flat_selector_for_its_workspace_policy() -> None:
    overrides = packagemanager.overrides_for(PackageManager.PNPM)
    assert overrides.key_path == ("overrides",)
    assert "eslint-plugin-react>eslint" in overrides.entries


def test_yarn_gets_resolved_overrides_and_one_tested_typescript_eslint_identity() -> None:
    overrides = packagemanager.overrides_for(PackageManager.YARN)
    assert overrides.key_path == ("resolutions",)
    expected_identity = {
        name: version
        for name, version in manifest.eslint_age_gate_preapprovals().items()
        if name == "typescript-eslint" or name.startswith("@typescript-eslint/")
    }
    assert overrides.entries == {
        "eslint-plugin-react/eslint": manifest.eslint_peers()["eslint"],
        **expected_identity,
    }
    assert "$" not in json.dumps(overrides.as_document())


def test_bun_gets_a_flat_eslint_override_it_actually_honors() -> None:
    overrides = packagemanager.overrides_for(PackageManager.BUN)
    assert overrides.key_path == ("overrides",)
    assert overrides.entries == {"eslint": manifest.eslint_peers()["eslint"]}


@pytest.mark.parametrize(
    ("client", "prefix"),
    [
        (PackageManager.NPM, "npm install --ignore-scripts"),
        (PackageManager.PNPM, "pnpm install --no-frozen-lockfile --ignore-scripts"),
        (PackageManager.YARN, "yarn install --ignore-scripts"),
        (PackageManager.BUN, "bun install --ignore-scripts"),
    ],
)
def test_the_install_command_is_the_one_that_client_understands(client: PackageManager, prefix: str) -> None:
    command = packagemanager.install_command(client)
    assert command.startswith(prefix)
    assert " add " not in command


@pytest.mark.parametrize("client", list(PackageManager))
def test_install_argv_matches_the_printed_script_free_command(client: PackageManager) -> None:
    argv = packagemanager.install_argv(client)
    assert argv == tuple(packagemanager.install_command(client).split())
    assert all("@sarj" not in part for part in argv)


def test_lint_execution_can_never_install_from_the_network() -> None:
    assert packagemanager.exec_argv(PackageManager.NPM, "eslint", "--", "app.ts") == (
        "npm",
        "exec",
        "--offline",
        "--",
        "eslint",
        "--",
        "app.ts",
    )
    assert packagemanager.exec_argv(PackageManager.BUN, "eslint", "--", "app.ts") == (
        "bunx",
        "--bun",
        "--no-install",
        "eslint",
        "--",
        "app.ts",
    )
    assert packagemanager.exec_argv(PackageManager.PNPM, "eslint", "--", "app.ts") == (
        "pnpm",
        "exec",
        "eslint",
        "--",
        "app.ts",
    )


@pytest.mark.parametrize(
    ("package_json", "expected"),
    [
        pytest.param({"name": "web", "packageManager": "yarn@1.22.19"}, YarnVariant.CLASSIC, id="declared-classic"),
        pytest.param({"name": "web", "packageManager": "yarn@4.15.0"}, YarnVariant.BERRY, id="declared-berry"),
        pytest.param({"name": "web"}, YarnVariant.CLASSIC, id="bare-lockfile"),
    ],
)
def test_yarn_dialect_follows_the_declared_package_manager(
    tmp_path: Path, package_json: dict[str, object], expected: YarnVariant
) -> None:
    root = _project(tmp_path, "yarn.lock", package_json)

    assert packagemanager.yarn_variant(root) is expected


def test_a_yarnrc_yml_marks_a_berry_checkout_without_a_declaration(tmp_path: Path) -> None:
    root = _project(tmp_path, "yarn.lock")
    _ = (root / ".yarnrc.yml").write_text("nodeLinker: node-modules\n", encoding="utf-8")

    assert packagemanager.yarn_variant(root) is YarnVariant.BERRY


def test_each_yarn_dialect_gets_flags_it_actually_enforces() -> None:
    classic = packagemanager.install_command(PackageManager.YARN, yarn=YarnVariant.CLASSIC)
    berry = packagemanager.install_command(PackageManager.YARN, yarn=YarnVariant.BERRY)

    assert classic == "yarn install --ignore-scripts"
    assert berry == "yarn install --no-immutable --mode=skip-build"
    assert packagemanager.install_argv(PackageManager.YARN, yarn=YarnVariant.BERRY) == tuple(berry.split())


def test_only_the_berry_note_mentions_berry_only_configuration() -> None:
    classic = packagemanager.install_note(PackageManager.YARN, yarn=YarnVariant.CLASSIC)
    berry = packagemanager.install_note(PackageManager.YARN, yarn=YarnVariant.BERRY)

    assert classic is not None
    assert berry is not None
    assert "resolutions" in classic
    assert "npmMinimalAgeGate" not in classic
    assert "npmMinimalAgeGate" in berry


def test_ci_workflow_speaks_the_detected_yarn_dialect(tmp_path: Path) -> None:
    _ = _project(tmp_path, "yarn.lock")

    classic = scaffold.github_ci_workflow(tmp_path)
    _ = (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "packageManager": "yarn@4.15.0"}) + "\n", encoding="utf-8"
    )
    berry = scaffold.github_ci_workflow(tmp_path)

    assert "yarn install --frozen-lockfile" in classic
    assert "--immutable" not in classic
    assert "yarn install --immutable" in berry


def test_ci_installs_nested_javascript_project_from_its_install_root(tmp_path: Path) -> None:
    web = tmp_path / "services" / "web"
    web.mkdir(parents=True)
    _ = (web / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    _ = (web / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "run: npm ci --no-audit --no-fund" in workflow
    assert "npm install --global" not in workflow
    assert 'working-directory: "services/web"' in workflow


def test_ci_yaml_quotes_a_nested_install_root_with_shell_metacharacters(tmp_path: Path) -> None:
    web = tmp_path / "services" / "web # production"
    web.mkdir(parents=True)
    _ = (web / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    _ = (web / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert 'working-directory: "services/web # production"' in workflow


@pytest.mark.parametrize(
    "declaration",
    [
        pytest.param("npm@12.0.2", id="version"),
        pytest.param("npm@12.0.2+sha512.abcdef", id="version-with-integrity"),
    ],
)
def test_ci_activates_the_exact_declared_npm_version(tmp_path: Path, declaration: str) -> None:
    _ = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": declaration})

    workflow = scaffold.github_ci_workflow(tmp_path)

    activation = "run: npm install --global npm@12.0.2 --ignore-scripts"
    assert activation in workflow
    assert workflow.index(activation) < workflow.index("run: npm ci")


def test_ci_rejects_a_non_exact_declared_npm_version(tmp_path: Path) -> None:
    _ = _project(tmp_path, "package-lock.json", {"name": "web", "packageManager": "npm@latest"})

    with pytest.raises(ValueError, match="must pin an exact semantic version"):
        scaffold.github_ci_workflow(tmp_path)


def test_ci_bootstraps_bun_without_unneeded_node_or_corepack(tmp_path: Path) -> None:
    _ = _project(tmp_path, "bun.lock")

    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "oven-sh/setup-bun@v2" in workflow
    assert "actions/setup-node" not in workflow
    assert "corepack enable" not in workflow
    assert "run: bun install --frozen-lockfile" in workflow


def test_ci_only_runs_locked_uv_sync_for_a_uv_project(tmp_path: Path) -> None:
    _ = (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\nversion="0.1.0"\n', encoding="utf-8")

    unlocked = scaffold.github_ci_workflow(tmp_path)
    _ = (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    locked = scaffold.github_ci_workflow(tmp_path)

    assert "uv sync" not in unlocked
    assert "run: uv sync --locked" in locked


def test_ci_emits_first_class_github_annotations(tmp_path: Path) -> None:
    workflow = scaffold.github_ci_workflow(tmp_path)

    assert "check --trust-repository-code --format github" in workflow


def test_init_speaks_classic_yarn_when_only_the_lockfile_names_it(tmp_path: Path) -> None:
    _ = _project(tmp_path, "yarn.lock")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert "yarn install --ignore-scripts" in proc.stdout
    assert "--mode=skip-build" not in proc.stdout
    assert "npmMinimalAgeGate" not in proc.stdout


def test_lifecycle_install_preserves_the_yarn_dialect(tmp_path: Path) -> None:
    ecosystems = scaffold.Ecosystems(
        False,
        True,
        typescript_root=tmp_path,
        typescript_install_root=tmp_path,
        client=PackageManager.YARN,
        yarn=YarnVariant.BERRY,
    )

    commands = lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none")

    assert commands[0].argv == ("yarn", "install", "--no-immutable", "--mode=skip-build")


def test_pnpm_workspace_install_targets_the_workspace_root() -> None:
    assert "--ignore-workspace" not in packagemanager.install_argv(PackageManager.PNPM, workspace=True)
    assert "--ignore-workspace" in packagemanager.install_argv(PackageManager.PNPM)


def test_conflicting_lockfiles_fail_instead_of_selecting_by_accident(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    _ = (tmp_path / "yarn.lock").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting package-manager lockfiles"):
        packagemanager.detect(tmp_path)


def test_init_writes_pnpm_overrides_into_workspace_yaml_for_a_standalone_repo(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by pnpm"
    assert "pnpm" not in written, "pnpm 11 ignores package.json#pnpm.overrides"
    workspace = (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert '"eslint-plugin-react>eslint"' in workspace
    assert "pnpm install --no-frozen-lockfile --ignore-scripts" in proc.stdout
    assert "--ignore-workspace" not in proc.stdout


def test_pnpm_11_workspace_overrides_are_merged_in_the_workspace_yaml(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    workspace = tmp_path / "pnpm-workspace.yaml"
    workspace.write_text("overrides:\n  rollup@<4: '>=4'\n\nallowBuilds:\n  esbuild: true\n", encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    text = workspace.read_text(encoding="utf-8")
    assert '"eslint-plugin-react>eslint"' in text
    assert "rollup@<4" in text
    assert "allowBuilds" in text
    package: dict[str, object] = json.loads(  # pyright: ignore[reportAny]
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    assert "pnpm" not in package


@pytest.mark.parametrize(
    "flow",
    ["overrides: {}\n", 'overrides: {"rollup": ">=4"}\n', '"overrides": {}\n'],
)
def test_pnpm_workspace_flow_overrides_fail_without_duplicate_keys(tmp_path: Path, flow: str) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    workspace = tmp_path / "pnpm-workspace.yaml"
    workspace.write_text(flow, encoding="utf-8")

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 2
    assert "flow-style `overrides` is unsupported" in proc.stderr
    assert workspace.read_text(encoding="utf-8") == flow


def test_init_writes_resolutions_into_a_yarn_repo(tmp_path: Path) -> None:
    _ = _project(tmp_path, "yarn.lock", {"name": "web", "packageManager": "yarn@4.15.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by Yarn"
    resolutions = manifest.table_field(written, "resolutions")
    assert resolutions["eslint-plugin-react/eslint"] == manifest.eslint_peers()["eslint"]
    expected_identity = {
        name: version
        for name, version in manifest.eslint_age_gate_preapprovals().items()
        if name == "typescript-eslint" or name.startswith("@typescript-eslint/")
    }
    assert {name: resolutions[name] for name in expected_identity} == expected_identity
    assert "yarn install --no-immutable --mode=skip-build" in proc.stdout


def test_init_pins_nested_yarn_eslint_configs_to_the_canonical_plugin_identity(tmp_path: Path) -> None:
    child = tmp_path / "packages" / "client"
    child.mkdir(parents=True)
    _ = _project(
        tmp_path,
        "yarn.lock",
        {
            "name": "web",
            "packageManager": "yarn@4.15.0",
            "workspaces": ["packages/*"],
        },
    )
    child_package = {
        "name": "client",
        "devDependencies": {
            "@typescript-eslint/parser": "^8.67.0",
            "typescript-eslint": "^8.67.0",
        },
    }
    (child / "package.json").write_text(json.dumps(child_package), encoding="utf-8")
    (child / "eslint.config.js").write_text(
        'import strict from "../../eslint.strict.mjs";\n'
        'import tseslint from "typescript-eslint";\n'
        "export default [...strict, ...tseslint.configs.strictTypeChecked];\n",
        encoding="utf-8",
    )

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    root: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    resolutions = manifest.table_field(manifest.as_table(root), "resolutions")
    approvals = manifest.eslint_age_gate_preapprovals()
    assert resolutions["typescript-eslint"] == approvals["typescript-eslint"]
    assert resolutions["@typescript-eslint/parser"] == approvals["@typescript-eslint/parser"]
    assert json.loads((child / "package.json").read_text(encoding="utf-8")) == child_package


def test_init_writes_bun_override_without_npm_nested_syntax(tmp_path: Path) -> None:
    _ = _project(tmp_path, "bun.lock", {"name": "web", "packageManager": "bun@1.2.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads(  # pyright: ignore[reportAny]
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides == {"eslint": manifest.eslint_peers()["eslint"]}


def test_npm_repairs_a_scalar_direct_peer_override_and_preserves_child_overrides(tmp_path: Path) -> None:
    _ = _project(
        tmp_path,
        "package-lock.json",
        {"name": "web", "overrides": {"eslint-plugin-react": "7.37.4"}},
    )

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    react = manifest.table_field(overrides, "eslint-plugin-react")
    assert react["."] == "$eslint-plugin-react"
    assert react["eslint"] == manifest.eslint_peers()["eslint"]


def test_npm_direct_peer_override_tracks_the_exact_pin_without_escaping_unicode(tmp_path: Path) -> None:
    _ = _project(
        tmp_path,
        "package-lock.json",
        {
            "name": "web",
            "description": "Customer dashboard — browser client",
            "devDependencies": {"typescript": "6.0.3"},
            "overrides": {"typescript": "^6.0.3"},
        },
    )

    proc = _cli("init", "--dest", str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    package_text = (tmp_path / "package.json").read_text(encoding="utf-8")
    parsed: object = json.loads(package_text)  # pyright: ignore[reportAny]
    package = manifest.as_table(parsed)
    assert manifest.table_field(package, "devDependencies")["typescript"] == "6.0.3"
    assert manifest.table_field(package, "overrides")["typescript"] == "$typescript"
    assert package["description"] == "Customer dashboard — browser client"
    assert "—" in package_text
    assert r"\u2014" not in package_text


def test_pnpm_workspace_policy_keeps_unrelated_package_json_pnpm_settings(tmp_path: Path) -> None:
    _ = _project(
        tmp_path,
        "pnpm-lock.yaml",
        {"name": "web", "pnpm": {"onlyBuiltDependencies": ["esbuild"]}},
    )
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    pnpm = manifest.table_field(manifest.as_table(parsed), "pnpm")
    assert pnpm["onlyBuiltDependencies"] == ["esbuild"]
    assert "overrides" not in pnpm
    assert '"eslint-plugin-react>eslint"' in (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")


def test_a_second_init_on_a_pnpm_repo_changes_nothing(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    before_package = (tmp_path / "package.json").read_text(encoding="utf-8")
    before_workspace = (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    second = _cli("init", "--dest", str(tmp_path))
    assert second.returncode == 0
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == before_package
    assert (tmp_path / "pnpm-workspace.yaml").read_text(encoding="utf-8") == before_workspace
    assert "already pins the tested ESLint peers and pnpm overrides" in second.stdout


def test_doctor_rejects_obsolete_package_json_pnpm_overrides(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    (tmp_path / "pnpm-workspace.yaml").unlink()

    proc = _cli("doctor", "--dest", str(tmp_path))

    assert proc.returncode != 0
    assert "required pnpm 11 workspace policy is missing" in proc.stdout
    assert "pnpm-workspace.yaml" in proc.stdout


def test_the_project_root_is_the_lockfiles_directory_not_the_topmost_package_json(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "package.json").write_text('{"packageManager": "yarn@4.15.0"}\n')
    (tmp_path / "typescript").mkdir()
    _ = _project(tmp_path / "typescript", "yarn.lock")

    found = scaffold.detect(tmp_path)
    assert found.typescript_root == tmp_path / "typescript"
    assert found.client == PackageManager.YARN


def test_ecosystem_detection_ignores_package_metadata_inside_tool_caches(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "service"\nversion = "0.1.0"\n')
    cached = tmp_path / ".uv-cache" / "archive-v0" / "basedpyright"
    cached.mkdir(parents=True)
    (cached / "package.json").write_text('{"name":"cached-tool"}\n', encoding="utf-8")

    found = scaffold.detect(tmp_path)

    assert found.python_root == tmp_path
    assert found.typescript_root is None


def test_an_explicit_dest_overrides_detection(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    _ = _project(tmp_path / "frontend", "package-lock.json")
    (tmp_path / "other").mkdir()
    _ = _project(tmp_path / "other", "pnpm-lock.yaml")

    found = scaffold.detect(tmp_path, typescript_dest="other")
    assert found.typescript_root == tmp_path / "other"
    assert found.client == PackageManager.PNPM


def test_nested_lockfile_beats_an_unrelated_root_package_json(tmp_path: Path) -> None:
    _ = (tmp_path / "package.json").write_text('{"name": "tooling"}\n', encoding="utf-8")
    project = tmp_path / "typescript"
    project.mkdir()
    _project(project, "yarn.lock")

    found = scaffold.detect(tmp_path)

    assert found.typescript_root == project
    assert found.typescript_install_root == project
    assert found.client is PackageManager.YARN


def test_nested_pnpm_preview_matches_the_applied_install_guidance(tmp_path: Path) -> None:
    _ = (tmp_path / "package.json").write_text('{"name": "tooling"}\n', encoding="utf-8")
    project = tmp_path / "typescript"
    project.mkdir()
    _project(project, "pnpm-lock.yaml", {"name": "web", "packageManager": "pnpm@10.0.0"})

    preview = _cli("init", "--dest", str(tmp_path), "--dry-run")
    applied = _cli("init", "--dest", str(tmp_path))

    assert preview.returncode == 0, preview.stderr
    assert applied.returncode == 0, applied.stderr
    expected = "pnpm install --no-frozen-lockfile --ignore-scripts"
    assert expected in preview.stdout
    assert expected in applied.stdout
    assert "pnpm add -w" not in preview.stdout
    assert "pnpm add -w" not in applied.stdout
