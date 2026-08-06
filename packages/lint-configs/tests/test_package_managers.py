"""`init` has to speak the npm client the repo actually uses, or it writes a no-op."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import manifest, packagemanager, scaffold
from sarj_lint_configs.packagemanager import PackageManager


if TYPE_CHECKING:
    from pathlib import Path


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    command = list(args)
    if command and command[0] == "init" and "--no-install" not in command:
        command.append("--no-install")
    return subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", *command],
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
    """Corepack enforces the field, so a repo declaring Yarn cannot be installed with npm."""
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


def test_pnpm_gets_a_flat_selector_under_its_own_key() -> None:
    overrides = packagemanager.overrides_for(PackageManager.PNPM)
    assert overrides.key_path == ("pnpm", "overrides")
    assert "eslint-plugin-react>eslint" in overrides.entries


def test_yarn_gets_a_path_selector_with_the_version_resolved() -> None:
    """Yarn has no `$dep` indirection; a literal `$eslint` is a range it cannot parse."""
    overrides = packagemanager.overrides_for(PackageManager.YARN)
    assert overrides.key_path == ("resolutions",)
    assert overrides.entries == {"eslint-plugin-react/eslint": manifest.eslint_peers()["eslint"]}
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
        (PackageManager.YARN, "yarn install --mode=skip-builds"),
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


def test_pnpm_workspace_install_targets_the_workspace_root() -> None:
    assert packagemanager.install_argv(PackageManager.PNPM, workspace=True) == packagemanager.install_argv(
        PackageManager.PNPM
    )


def test_conflicting_lockfiles_fail_instead_of_selecting_by_accident(tmp_path: Path) -> None:
    _project(tmp_path, "pnpm-lock.yaml")
    _ = (tmp_path / "yarn.lock").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting package-manager lockfiles"):
        packagemanager.detect(tmp_path)


def test_init_writes_pnpm_overrides_into_a_pnpm_repo(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by pnpm"
    pnpm = manifest.table_field(written, "pnpm")
    assert "eslint-plugin-react>eslint" in manifest.table_field(pnpm, "overrides")
    assert "pnpm install --no-frozen-lockfile --ignore-scripts" in proc.stdout


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
    assert "yarn install --mode=skip-builds" in proc.stdout


def test_init_writes_bun_override_without_npm_nested_syntax(tmp_path: Path) -> None:
    _ = _project(tmp_path, "bun.lock", {"name": "web", "packageManager": "bun@1.2.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads(  # pyright: ignore[reportAny]
        (tmp_path / "package.json").read_text(encoding="utf-8")
    )
    overrides = manifest.table_field(manifest.as_table(parsed), "overrides")
    assert overrides == {"eslint": manifest.eslint_peers()["eslint"]}


def test_npm_preserves_a_scalar_parent_override_under_dot(tmp_path: Path) -> None:
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
    assert react["."] == "7.37.4"
    assert react["eslint"] == manifest.eslint_peers()["eslint"]


def test_merging_pnpm_overrides_keeps_the_rest_of_the_pnpm_table(tmp_path: Path) -> None:
    _ = _project(
        tmp_path,
        "pnpm-lock.yaml",
        {"name": "web", "pnpm": {"onlyBuiltDependencies": ["esbuild"]}},
    )
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    pnpm = manifest.table_field(manifest.as_table(parsed), "pnpm")
    assert pnpm["onlyBuiltDependencies"] == ["esbuild"]
    assert "eslint-plugin-react>eslint" in manifest.table_field(pnpm, "overrides")


def test_a_second_init_on_a_pnpm_repo_changes_nothing(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    assert _cli("init", "--dest", str(tmp_path)).returncode == 0
    before = (tmp_path / "package.json").read_text(encoding="utf-8")

    second = _cli("init", "--dest", str(tmp_path))
    assert second.returncode == 0
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == before
    assert "already pins the tested ESLint peers and pnpm overrides" in second.stdout


def test_the_project_root_is_the_lockfiles_directory_not_the_topmost_package_json(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / "package.json").write_text('{"packageManager": "yarn@4.15.0"}\n')
    (tmp_path / "typescript").mkdir()
    _ = _project(tmp_path / "typescript", "yarn.lock")

    found = scaffold.detect(tmp_path)
    assert found.typescript_root == tmp_path / "typescript"
    assert found.client == PackageManager.YARN


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
