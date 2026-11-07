from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.yaml_boundary import parse_yaml


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / ".github/scripts/fix-staged-oxlint.py"
_TYPESCRIPT = _ROOT / "packages/typescript"
_SOURCE = b"let value = 1;\nexport { value };\n"
_CONFIG = (
    "export default { plugins: ['eslint'], categories: { correctness: 'off' }, rules: { 'prefer-const': 'error' } };\n"
)


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(("git", "-C", str(root), *arguments), capture_output=True, check=True, timeout=30).stdout


def _repository(root: Path, *, excluded_paths: tuple[str, ...] = ()) -> None:
    _git(root, "init", "--quiet", "--template=")
    _git(root, "config", "user.name", "Standards Fixture")
    _git(root, "config", "user.email", "standards-fixture@example.invalid")
    (root / ".gitignore").write_text("node_modules\ndist\n", encoding="utf-8")
    # Like this repository, the adopted TypeScript project is the package that installs the tools.
    adopted = manifest.Manifest(
        manifest.adopted_version(), (), ".", "packages/typescript", hook_manager="none", excluded_paths=excluded_paths
    )
    (root / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")


def _helpers_project(root: Path, config: str = _CONFIG) -> Path:
    project = root / ".github/scripts"
    project.mkdir(parents=True)
    (project / "oxlint.config.mts").write_text(config, encoding="utf-8")
    package = root / "packages/typescript"
    package.mkdir(parents=True)
    shutil.copyfile(_TYPESCRIPT / "package.json", package / "package.json")
    (package / "node_modules").symlink_to(_TYPESCRIPT / "node_modules", target_is_directory=True)
    return project


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_SCRIPT)), cwd=root, capture_output=True, text=True, check=False, timeout=120
    )


def test_authored_hook_fixes_a_helper_with_the_package_installed_oxlint(tmp_path: Path) -> None:
    _repository(tmp_path)
    source = _helpers_project(tmp_path) / "source.mts"
    source.write_bytes(_SOURCE)
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert source.read_bytes() == b"const value = 1;\nexport { value };\n"
    assert "Review and stage" in result.stderr
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert not (tmp_path / "packages/typescript/dist").exists()


def test_authored_hook_passes_a_clean_source_unchanged(tmp_path: Path) -> None:
    _repository(tmp_path)
    source = _helpers_project(tmp_path) / "source.mts"
    source.write_bytes(b"const value = 1;\nexport { value };\n")
    _git(tmp_path, "add", "--all")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == b"const value = 1;\nexport { value };\n"


def test_authored_hook_blocks_the_commit_when_the_config_fails_to_load(tmp_path: Path) -> None:
    _repository(tmp_path)
    source = _helpers_project(tmp_path, "throw new Error('deterministic fixture failure');\n") / "source.mts"
    source.write_bytes(_SOURCE)
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "deterministic fixture failure" in result.stdout + result.stderr
    assert source.read_bytes() == _SOURCE
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before


@pytest.mark.parametrize("selection", ["empty", "deleted", "excluded"])
def test_authored_hook_never_widens_an_empty_source_selection(tmp_path: Path, selection: str) -> None:
    _repository(tmp_path, excluded_paths=("source.ts",) if selection == "excluded" else ())
    source = tmp_path / "source.ts"
    source.write_bytes(_SOURCE)
    if selection == "deleted":
        _git(tmp_path, "add", "--all")
        _git(tmp_path, "commit", "--quiet", "--message", "fixture")
        _git(tmp_path, "rm", "--quiet", "--", "source.ts")
        source.write_bytes(_SOURCE)
    elif selection == "excluded":
        _git(tmp_path, "add", "--", source.name)
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == _SOURCE
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert not (tmp_path / "packages").exists()


def test_authored_hook_refuses_unowned_selected_sources_before_execution(tmp_path: Path) -> None:
    _repository(tmp_path)
    source = tmp_path / "unowned.ts"
    source.write_bytes(_SOURCE)
    _git(tmp_path, "add", "--all")

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "no owning authored Oxlint project" in result.stderr
    assert source.read_bytes() == _SOURCE


def test_authored_hook_stops_on_partially_staged_inputs_before_any_fix(tmp_path: Path) -> None:
    _repository(tmp_path)
    source = _helpers_project(tmp_path) / "source.mts"
    source.write_bytes(_SOURCE)
    other = tmp_path / "other.py"
    other.write_text("VALUE: int = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "--all")
    other.write_text("VALUE: int = 2\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "unstaged content or unverifiable Git index flags" in result.stderr
    assert source.read_bytes() == _SOURCE


def test_lefthook_runs_the_authored_oxlint_hook() -> None:
    document = manifest.as_table(parse_yaml((_ROOT / "lefthook.yml").read_text(encoding="utf-8")))
    commands = manifest.table_field(manifest.table_field(document, "pre-commit"), "commands")
    entry = manifest.text_field(manifest.table_field(commands, "authored-oxlint-fixes"), "run")

    assert (
        entry == "uv run --no-config --project packages/standards --frozen python .github/scripts/fix-staged-oxlint.py"
    )
