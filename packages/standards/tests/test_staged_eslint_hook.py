from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sarj_standards.libs.adoption import lifecycle, manifest
from sarj_standards.libs.repository import hooks
from sarj_standards.libs.yaml_boundary import parse_yaml


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / ".github/scripts/fix-staged-eslint.py"
_TYPESCRIPT = _ROOT / "packages/typescript"
_SOURCE = b"let value = 1;\nexport { value };\n"


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(("git", "-C", str(root), *arguments), capture_output=True, check=True, timeout=30).stdout


def _repository(root: Path) -> None:
    _git(root, "init", "--quiet", "--template=")
    _git(root, "config", "user.name", "Standards Fixture")
    _git(root, "config", "user.email", "standards-fixture@example.invalid")
    (root / ".gitignore").write_text("node_modules\ndist\nstandards-runtime\n", encoding="utf-8")
    adopted = manifest.Manifest(manifest.adopted_version(), (), ".", ".", hook_manager="none")
    (root / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")


def _native_project(root: Path, *, failure: str = "") -> Path:
    project = root / ".github/scripts"
    project.mkdir(parents=True)
    if failure:
        config = (
            "import fs from 'node:fs';\n"
            "const broken = {create(){" + failure + "throw new Error('deterministic fixture failure');}};\n"
            "export default [{plugins:{fixture:{rules:{broken}}},rules:{'fixture/broken':'error'}}];\n"
        )
    else:
        config = "export default [{rules:{'prefer-const':'warn'}}];\n"
    (project / "eslint.config.mjs").write_text(config, encoding="utf-8")
    package = root / "packages/typescript"
    package.mkdir(parents=True)
    shutil.copyfile(_TYPESCRIPT / "package.json", package / "package.json")
    (package / "node_modules").symlink_to(_TYPESCRIPT / "node_modules", target_is_directory=True)
    return project


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_SCRIPT)), cwd=root, capture_output=True, text=True, check=False, timeout=120
    )


@pytest.mark.parametrize("fix", [False, True], ids=("verify", "fix"))
@pytest.mark.parametrize("rule_warning", [False, True], ids=("ignored-only", "real-warning"))
def test_native_ignore_warning_flag_preserves_rule_warning_limit(
    tmp_path: Path, *, fix: bool, rule_warning: bool
) -> None:
    project = _native_project(tmp_path)
    (project / "eslint.config.mjs").write_text(
        "export default [{ignores:['ignored.js']},{rules:{'no-console':'warn'}}];\n", encoding="utf-8"
    )
    ignored = project / "ignored.js"
    ignored.write_text("if (\n", encoding="utf-8")
    source = project / "source.js"
    original = "console.log('fixture');\n" if rule_warning else "export const VALUE = 1;\n"
    source.write_text(original, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None

    result = subprocess.run(
        (
            node,
            str(_TYPESCRIPT / "node_modules/eslint/bin/eslint.js"),
            "--no-warn-ignored",
            "--max-warnings",
            "0",
            *(("--fix",) if fix else ()),
            "--",
            "ignored.js",
            "source.js",
        ),
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == (1 if rule_warning else 0), result.stdout + result.stderr
    assert "File ignored" not in result.stdout + result.stderr
    assert ("no-console" in result.stdout) is rule_warning
    assert source.read_text(encoding="utf-8") == original
    assert ignored.read_text(encoding="utf-8") == "if (\n"


@pytest.mark.parametrize("hidden", ["partial", "--assume-unchanged", "--skip-worktree"])
def test_authored_hook_reconciles_non_typescript_inputs_before_any_fixer_or_build(tmp_path: Path, hidden: str) -> None:
    _repository(tmp_path)
    project = _native_project(tmp_path)
    source = project / "source.js"
    source.write_bytes(_SOURCE)
    custom = tmp_path / "packages/typescript/src/source.ts"
    custom.parent.mkdir()
    custom.write_bytes(_SOURCE)
    (custom.parent.parent / "eslint.config.mjs").write_text(
        "import parser from '@typescript-eslint/parser';\n"
        "export default [{files:['**/*.ts'],languageOptions:{parser},rules:{'prefer-const':'warn'}}];\n",
        encoding="utf-8",
    )
    other = tmp_path / "other.py"
    other.write_text("VALUE: int = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "--all")
    if hidden == "partial":
        other.write_text("VALUE: int = 2\n", encoding="utf-8")
    else:
        _git(tmp_path, "update-index", hidden, "other.py")
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "unstaged content or unverifiable Git index flags" in result.stderr
    assert source.read_bytes() == _SOURCE
    assert custom.read_bytes() == _SOURCE
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert not (tmp_path / "packages/typescript/dist").exists()


@pytest.mark.parametrize("selection", ["empty", "deleted", "generated", "excluded"])
def test_authored_hook_never_widens_an_empty_source_selection(tmp_path: Path, selection: str) -> None:
    _repository(tmp_path)
    source = tmp_path / "source.ts"
    source.write_bytes(_SOURCE)
    if selection == "deleted":
        _git(tmp_path, "add", "--all")
        _git(tmp_path, "commit", "--quiet", "--message", "fixture")
        _git(tmp_path, "rm", "--", "source.ts")
        source.write_bytes(_SOURCE)
    elif selection == "generated":
        source = tmp_path / "source.gen.ts"
        source.write_bytes(_SOURCE)
        _git(tmp_path, "add", "--", source.name)
    elif selection == "excluded":
        adopted = manifest.Manifest(
            manifest.adopted_version(), (), ".", ".", hook_manager="none", excluded_paths=("source.ts",)
        )
        (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
        _git(tmp_path, "add", "--", source.name)
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == _SOURCE
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert not (tmp_path / "packages").exists()


@pytest.mark.parametrize(
    "failure", ["fs.writeFileSync('source.js','export const repaired = 1;\\n');", "fs.unlinkSync('source.js');"]
)
def test_authored_hook_reports_changed_source_even_when_eslint_fails(tmp_path: Path, failure: str) -> None:
    _repository(tmp_path)
    project = _native_project(tmp_path, failure=failure)
    (project / "source.js").write_bytes(_SOURCE)
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "deterministic fixture failure" in result.stdout + result.stderr
    assert "Review and stage" in result.stderr
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before


def test_authored_hook_refuses_unowned_selected_sources_before_execution(tmp_path: Path) -> None:
    _repository(tmp_path)
    package = tmp_path / "packages/typescript"
    package.mkdir(parents=True)
    shutil.copyfile(_TYPESCRIPT / "package.json", package / "package.json")
    source = tmp_path / "unowned.ts"
    source.write_bytes(_SOURCE)
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "no owning authored ESLint project" in result.stderr
    assert source.read_bytes() == _SOURCE
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert not (package / "dist").exists()


def test_authored_hook_fixes_config_sources_with_the_installed_eslint_on_restricted_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    project = _native_project(tmp_path)
    config = project / "eslint.config.mjs"
    config.write_text("let rules = { 'prefer-const': 'warn' };\nexport default [{ rules }];\n", encoding="utf-8")
    assert lifecycle.select_eslint_commands(tmp_path, [str(config)]).commands == ()
    selection = lifecycle.select_eslint_commands(tmp_path, [str(config)], include_config_sources=True)
    assert len(selection.commands) == 1
    assert selection.unowned_count == 0
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")
    node = shutil.which("node")
    assert node is not None
    monkeypatch.setenv("PATH", f"{Path(node).parent}{os.pathsep}/usr/bin{os.pathsep}/bin")

    result = _run(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "const rules" in config.read_text(encoding="utf-8")
    assert "Review and stage" in result.stderr
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before


def _installed_hook_config() -> str:
    document = manifest.as_table(parse_yaml((_ROOT / "lefthook.yml").read_text(encoding="utf-8")))
    commands = manifest.table_field(manifest.table_field(document, "pre-commit"), "commands")
    entry = manifest.text_field(manifest.as_table(commands.get("authored-eslint-fixes")), "run")
    assert entry is not None
    return (
        f"pre-commit:\n  parallel: false\n  piped: true\n  commands:\n    authored-eslint-fixes:\n      run: {entry}\n"
    )


def test_installed_own_hook_builds_fresh_custom_rules_and_preserves_native_fixes_and_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    package = tmp_path / "packages/typescript"
    shutil.copytree(_TYPESCRIPT, package, ignore=shutil.ignore_patterns("node_modules", "dist"))
    (package / "node_modules").symlink_to(_TYPESCRIPT / "node_modules", target_is_directory=True)
    shutil.copytree(_ROOT / "packages/tsconfig", tmp_path / "packages/tsconfig")
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(_SCRIPT, scripts / _SCRIPT.name)
    for sibling in ("contracts", "python", "sql", "iac", "standards"):
        (tmp_path / "packages" / sibling).symlink_to(_ROOT / "packages" / sibling, target_is_directory=True)
    with (tmp_path / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write(
            "".join(f"/packages/{sibling}\n" for sibling in ("contracts", "python", "sql", "iac", "standards"))
        )
    (tmp_path / "lefthook.yml").write_text(_installed_hook_config(), encoding="utf-8")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "--message", "fixture")
    hooks.install(tmp_path)
    source = package / "src/hook-values.ts"
    original = b"export let FIRST_VALUE = 1;\n// ================\nexport const SECOND_VALUE = 2;\n"
    source.write_bytes(original)
    excluded = package / "src/excluded-values.ts"
    excluded.write_bytes(original)
    ignored = package / "src/ignored-values.ts"
    ignored.write_bytes(original)
    rejected = package / "tests/fixtures/hook-ignored.ts"
    rejected.write_text("if (\n", encoding="utf-8")
    adopted = manifest.Manifest(
        manifest.adopted_version(),
        (),
        ".",
        ".",
        hook_manager="none",
        excluded_paths=("packages/typescript/src/ignored-values.ts",),
        exclusion_overrides=(
            manifest.ExclusionOverride(
                ("packages/typescript/src/excluded-values.ts",),
                ("eslint:@sarj/no-comment-cruft",),
                "Keep this private regression banner while allowing native fixes.",
            ),
        ),
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
    _git(tmp_path, "add", "--all")
    before = _git(tmp_path, "ls-files", "--stage", "-z")
    head = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "standards-runtime"))
    assert not (package / "dist").exists()

    result = subprocess.run(
        ("git", "commit", "--message", "feat: verify source fixes"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Review and stage" in result.stdout + result.stderr, result.stdout + result.stderr
    assert b"export const FIRST_VALUE" in source.read_bytes()
    assert b"================" not in source.read_bytes()
    assert b"export const FIRST_VALUE" in excluded.read_bytes()
    assert b"================" in excluded.read_bytes()
    assert ignored.read_bytes() == original
    assert rejected.read_text(encoding="utf-8") == "if (\n"
    assert (package / "dist/index.js").is_file()
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    _git(tmp_path, "add", "--all")
    postimage = source.read_bytes()
    converged = subprocess.run(
        (str(tmp_path / ".git/hooks/pre-commit"),),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert converged.returncode == 0, converged.stdout + converged.stderr
    assert source.read_bytes() == postimage
    assert rejected.read_text(encoding="utf-8") == "if (\n"


def test_installed_own_hook_builds_a_file_dependency_before_docs_only_native_eslint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    package = tmp_path / "packages/typescript"
    shutil.copytree(_TYPESCRIPT, package, ignore=shutil.ignore_patterns("node_modules", "dist"))
    (package / "node_modules").symlink_to(_TYPESCRIPT / "node_modules", target_is_directory=True)
    shutil.copytree(_ROOT / "packages/tsconfig", tmp_path / "packages/tsconfig")
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(_SCRIPT, scripts / _SCRIPT.name)
    for sibling in ("contracts", "python", "sql", "iac", "standards"):
        (tmp_path / "packages" / sibling).symlink_to(_ROOT / "packages" / sibling, target_is_directory=True)
    with (tmp_path / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write(
            "".join(f"/packages/{sibling}\n" for sibling in ("contracts", "python", "sql", "iac", "standards"))
        )
    docs = tmp_path / "apps/docs"
    docs.mkdir(parents=True)
    (docs / "package.json").write_text(
        '{"name":"docs-fixture","private":true,"type":"module",'
        '"devDependencies":{"@sarj/eslint-plugin":"file:../../packages/typescript"}}\n',
        encoding="utf-8",
    )
    (docs / "node_modules/@sarj").mkdir(parents=True)
    (docs / "node_modules/@sarj/eslint-plugin").symlink_to(package, target_is_directory=True)
    (docs / "eslint.config.mjs").write_text(
        "import sarj from '@sarj/eslint-plugin';\n"
        "export default [{files:['**/*.mjs'],plugins:{'@sarj':sarj},"
        "rules:{'prefer-const':'warn','@sarj/no-comment-cruft':'error'}}];\n",
        encoding="utf-8",
    )
    (tmp_path / "lefthook.yml").write_text(_installed_hook_config(), encoding="utf-8")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "--message", "fixture")
    hooks.install(tmp_path)
    source = docs / "src/hook-values.mjs"
    source.parent.mkdir()
    source.write_bytes(b"let first = 1;\n// ================\nconst second = 2;\nexport { first, second };\n")
    _git(tmp_path, "add", "--", "apps/docs/src/hook-values.mjs")
    before = _git(tmp_path, "ls-files", "--stage", "-z")
    head = _git(tmp_path, "rev-parse", "HEAD")
    assert _git(tmp_path, "diff", "--cached", "--name-only", "-z") == b"apps/docs/src/hook-values.mjs\0"
    assert not (package / "dist").exists()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "standards-runtime"))

    result = subprocess.run(
        (str(tmp_path / ".git/hooks/pre-commit"),),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Review and stage" in result.stdout + result.stderr
    assert source.read_bytes() == b"const first = 1;\n\nconst second = 2;\nexport { first, second };\n"
    assert (package / "dist/index.js").is_file()
    assert _git(tmp_path, "ls-files", "--stage", "-z") == before
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    _git(tmp_path, "add", "--", "apps/docs/src/hook-values.mjs")
    staged = _git(tmp_path, "ls-files", "--stage", "-z")
    postimage = source.read_bytes()

    converged = subprocess.run(
        (str(tmp_path / ".git/hooks/pre-commit"),),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert converged.returncode == 0, converged.stdout + converged.stderr
    assert source.read_bytes() == postimage
    assert _git(tmp_path, "ls-files", "--stage", "-z") == staged
    assert _git(tmp_path, "rev-parse", "HEAD") == head
