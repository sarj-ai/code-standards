"""`init` has to speak the npm client the repo actually uses, or it writes a no-op.

The shipped ESLint peer set does not install without an override -- the config's
unicorn floor needs `eslint >= 10.4` while the newest `eslint-plugin-react` peers
`eslint <= ^9.7` -- and only npm reads a top-level `overrides` key. pnpm reads
`pnpm.overrides`, Yarn reads `resolutions`, and both ignore npm's spelling in
silence. Writing npm's block into a pnpm or Yarn repo therefore fails exactly as
writing nothing would, except `package.json` now looks fixed. Two of the three
TypeScript layouts measured are not npm.
"""

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
    return subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", *args],
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
def test_the_lockfile_names_the_client(
    tmp_path: Path, lockfile: str, expected: PackageManager
) -> None:
    assert packagemanager.detect(_project(tmp_path, lockfile)) == expected


def test_a_repo_with_no_lockfile_is_assumed_to_be_npm(tmp_path: Path) -> None:
    _ = (tmp_path / "package.json").write_text('{"name": "web"}\n', encoding="utf-8")
    assert packagemanager.detect(tmp_path) == PackageManager.NPM


def test_the_packagemanager_field_beats_a_stray_lockfile(tmp_path: Path) -> None:
    """Corepack enforces the field, so a repo declaring Yarn cannot be installed with npm."""
    root = _project(
        tmp_path, "package-lock.json", {"name": "web", "packageManager": "yarn@4.15.0"}
    )
    assert packagemanager.detect(root) == PackageManager.YARN


def test_npm_keeps_the_nested_form() -> None:
    overrides = packagemanager.overrides_for(PackageManager.NPM)
    assert overrides.key_path == ("overrides",)
    assert overrides.entries == manifest.eslint_overrides()


def test_pnpm_gets_a_flat_selector_under_its_own_key() -> None:
    overrides = packagemanager.overrides_for(PackageManager.PNPM)
    assert overrides.key_path == ("pnpm", "overrides")
    assert "eslint-plugin-react>eslint" in overrides.entries


def test_yarn_gets_a_path_selector_with_the_version_resolved() -> None:
    """Yarn has no `$dep` indirection; a literal `$eslint` is a range it cannot parse."""
    overrides = packagemanager.overrides_for(PackageManager.YARN)
    assert overrides.key_path == ("resolutions",)
    assert overrides.entries == {
        "eslint-plugin-react/eslint": manifest.eslint_peers()["eslint"]
    }
    assert "$" not in json.dumps(overrides.as_document())


@pytest.mark.parametrize(
    ("client", "prefix"),
    [
        (PackageManager.NPM, "npm install -D --save-exact"),
        (PackageManager.PNPM, "pnpm add -D --save-exact"),
        (PackageManager.YARN, "yarn add -D --exact"),
        (PackageManager.BUN, "bun add -d --exact"),
    ],
)
def test_the_install_command_is_the_one_that_client_understands(
    client: PackageManager, prefix: str
) -> None:
    command = packagemanager.install_command(client)
    assert command.startswith(prefix)
    for name, pin in manifest.eslint_peers().items():
        assert f"{name}@{pin}" in command


def test_init_writes_pnpm_overrides_into_a_pnpm_repo(tmp_path: Path) -> None:
    _ = _project(tmp_path, "pnpm-lock.yaml")
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by pnpm"
    pnpm = manifest.table_field(written, "pnpm")
    assert "eslint-plugin-react>eslint" in manifest.table_field(pnpm, "overrides")
    assert "pnpm add -D --save-exact" in proc.stdout


def test_init_writes_resolutions_into_a_yarn_repo(tmp_path: Path) -> None:
    _ = _project(tmp_path, "yarn.lock", {"name": "web", "packageManager": "yarn@4.15.0"})
    proc = _cli("init", "--dest", str(tmp_path))
    assert proc.returncode == 0, proc.stderr

    parsed: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] — untyped stdlib boundary
    written = manifest.as_table(parsed)
    assert "overrides" not in written, "a bare `overrides` key is ignored by Yarn"
    resolutions = manifest.table_field(written, "resolutions")
    assert resolutions["eslint-plugin-react/eslint"] == manifest.eslint_peers()["eslint"]
    assert "yarn add -D --exact" in proc.stdout


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
    assert "already carries the pnpm peer overrides" in second.stdout


def test_the_project_root_is_the_lockfiles_directory_not_the_topmost_package_json(
    tmp_path: Path,
) -> None:
    """A root package.json can declare nothing but `packageManager`.

    Placing the config beside the topmost `package.json` puts it in a directory
    that will never have a `node_modules`, and a flat config is not searched for
    upward -- so the config loads for nobody while the tool reports success.
    """
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
