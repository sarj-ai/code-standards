from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

from sarj_lint_configs import (
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
    __version__,
    _meta,  # sarj-noqa: SARJ048 — the source-tree version fallback is the subject of a test below
    config_generation,
    manifest,
)


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

#: Expected fallback independent of the module under test.
_SOURCE_TREE_VERSION = "0.0.0.dev0"


def test_version_string() -> None:
    """The shipped version has to BE the pyproject version, not merely look like one."""
    declared = tomllib.loads((_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == declared["project"]["version"]


def test_an_uninstalled_source_tree_reports_a_dev_version() -> None:
    real = importlib.metadata.version

    def _absent(distribution_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(distribution_name)

    importlib.metadata.version = _absent
    try:
        _ = importlib.reload(_meta)
    finally:
        importlib.metadata.version = real
    assert _meta.__version__ == _SOURCE_TREE_VERSION
    _ = importlib.reload(_meta)
    assert _meta.__version__ == __version__


def test_configs_dir_exists() -> None:
    assert CONFIGS_DIR.is_dir(), f"missing: {CONFIGS_DIR}"


@pytest.mark.parametrize(
    "path",
    [RUFF_STRICT, PYRIGHT_STRICT, ESLINT_STRICT, MARKDOWNLINT_STRICT, TAPLO_STRICT, YAMLLINT_STRICT],
)
def test_all_six_configs_bundled(path: Path) -> None:
    assert path.is_file(), f"missing bundled config: {path}"
    assert path.stat().st_size > 0


@pytest.mark.parametrize("path", [RUFF_APPLICATION, ESLINT_APPLICATION])
def test_application_configs_bundled(path: Path) -> None:
    assert path.is_file(), f"missing bundled application config: {path}"
    assert path.stat().st_size > 0


def test_application_configs_have_no_generation_drift() -> None:
    assert config_generation.sync(check=True)


def test_application_configs_are_standalone_supersets() -> None:
    application_ruff = RUFF_APPLICATION.read_text()
    application_eslint = ESLINT_APPLICATION.read_text()
    assert application_ruff.startswith(RUFF_STRICT.read_text().split("[lint.per-file-ignores]", 1)[0])
    assert len(application_eslint) >= len(ESLINT_STRICT.read_text())
    assert "Generated application-profile library policy" in application_ruff
    assert "Generated application-profile library policy" in application_eslint


def test_application_configs_enforce_catalog_without_changing_standard_profile() -> None:
    application_ruff = manifest.as_table(tomllib.loads(RUFF_APPLICATION.read_text()))
    application_lint = manifest.table_field(application_ruff, "lint")
    application_tidy = manifest.table_field(application_lint, "flake8-tidy-imports")
    application_bans = manifest.table_field(application_tidy, "banned-api")
    standard_ruff = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text()))
    standard_lint = manifest.table_field(standard_ruff, "lint")
    standard_tidy = manifest.table_field(standard_lint, "flake8-tidy-imports")
    standard_bans = manifest.table_field(standard_tidy, "banned-api")
    assert "argparse" in application_bans
    assert "pandas" in application_bans
    assert "argparse" not in standard_bans
    assert "pandas" not in standard_bans

    application_eslint = ESLINT_APPLICATION.read_text()
    standard_eslint = ESLINT_STRICT.read_text()
    assert '"name": "axios"' in application_eslint
    assert '"name": "lodash"' in application_eslint
    assert 'name: "@clerk/nextjs"' in application_eslint
    assert '"group": ["axios/*"]' in application_eslint
    assert '"@sarj/no-restricted-library-load"' in application_eslint
    assert '"@sarj/prefer-native-random-uuid": "error"' in application_eslint
    assert '"module": "axios"' in application_eslint
    assert '"name": "axios"' not in standard_eslint
    assert '"name": "lodash"' not in standard_eslint
    assert '"@sarj/no-restricted-library-load"' not in standard_eslint


def test_ruff_config_is_valid_toml() -> None:
    text = RUFF_STRICT.read_text()
    data = tomllib.loads(text)  # parses as TOML
    assert "lint" in data
    assert re.search(r'external\s*=\s*\[\s*"SARJ"\s*\]', text)
    assert re.search(r'select\s*=\s*\[\s*"ALL"\s*\]', text)


def test_ruff_formatter_does_not_rewrite_markdown() -> None:
    data = tomllib.loads(RUFF_STRICT.read_text())
    assert data["format"]["exclude"] == ["*.md"]


def test_pyright_config_is_valid_jsonc() -> None:
    # pyright loads its config as JSONC; a bare-key .toml is silently ignored by
    # `extends`, so the strict pyright config must ship as JSON(C), not TOML.
    raw = PYRIGHT_STRICT.read_text()
    assert isinstance(json.loads(re.sub(r"//.*", "", raw)), dict)  # parses as JSON(C)
    assert re.search(r'"typeCheckingMode"\s*:\s*"strict"', raw)
    assert re.search(r'"reportExplicitAny"\s*:\s*"error"', raw)


def test_eslint_config_is_esm() -> None:
    text = ESLINT_STRICT.read_text()
    assert "export default" in text


def test_yamllint_accepts_github_actions_on_key() -> None:
    text = YAMLLINT_STRICT.read_text()
    assert "check-keys: false" in text


def test_taplo_excludes_generated_strict_configs() -> None:
    data = tomllib.loads(TAPLO_STRICT.read_text())
    assert data["exclude"] == ["**/.ruff-strict.toml", "**/.taplo.toml"]


def test_consistent_type_assertions_options_are_schema_compatible() -> None:
    text = ESLINT_STRICT.read_text()
    match = re.search(
        r'"@typescript-eslint/consistent-type-assertions"\s*:\s*\[\s*"error"\s*,\s*\{(?P<options>[^}]*)\}',
        text,
    )
    assert match is not None
    options = match.group("options")
    if 'assertionStyle: "never"' in options:
        assert "objectLiteralTypeAssertions" not in options


def test_eslint_config_avoids_eslint_10_only_unicorn_rules() -> None:
    text = ESLINT_STRICT.read_text()
    assert "prohibitLocalVariables" not in text
    assert '"unicorn/no-array-for-each"' not in text
    assert '"unicorn/no-for-each"' not in text
    assert "CallExpression[callee.property.name='forEach']" in text


def test_prefer_nullish_coalescing_ignores_primitives() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/prefer-nullish-coalescing"\s*:\s*\[\s*"error"\s*,\s*\{[^}]*ignorePrimitives\s*:\s*\{',
        text,
    )


def test_naming_convention_allows_framework_names() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/naming-convention".+?format:\s*\["camelCase"\].+?filter:\s*\{\s*regex:\s*"\^\(UNSAFE_\|__\)"',
        text,
        re.DOTALL,
    )


def test_eslint_config_does_not_assume_react_compiler() -> None:
    text = ESLINT_STRICT.read_text()
    assert "CallExpression[callee.name='useMemo']" not in text
    assert "CallExpression[callee.name='useCallback']" not in text


def test_cli_list(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "list"],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    assert "ruff" in proc.stdout
    assert "pyright" in proc.stdout
    assert "eslint" in proc.stdout
    assert "markdownlint" in proc.stdout
    assert "taplo" in proc.stdout
    assert "yamllint" in proc.stdout


def test_cli_path_ruff() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "path", "ruff"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == str(RUFF_STRICT)


def test_cli_sync_writes_files(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--dest", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert (tmp_path / "eslint.strict.mjs").is_file()
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert (tmp_path / ".taplo.toml").is_file()
    assert (tmp_path / ".yamllint.yaml").is_file()
    assert "synced 6/6" in proc.stdout


def test_cli_sync_skips_existing_without_force(tmp_path: Path) -> None:
    (tmp_path / ".ruff-strict.toml").write_text("pre-existing")
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--dest", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "skip" in proc.stdout
    assert (tmp_path / ".ruff-strict.toml").read_text() == "pre-existing"


def test_cli_sync_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / ".ruff-strict.toml").write_text("pre-existing")
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--force", "--dest", str(tmp_path)],
        check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").read_text() != "pre-existing"


def test_cli_sync_only_ruff(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert not (tmp_path / ".pyright-strict.json").exists()
    assert not (tmp_path / "eslint.strict.mjs").exists()


def test_cli_unknown_subcommand_exits_nonzero(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "bogus"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode != 0


def test_synced_ruff_parses_as_toml(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    parsed = tomllib.loads((tmp_path / ".ruff-strict.toml").read_text())
    assert "lint" in parsed


def test_sync_to_nonexistent_dest_errors(tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist"
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--dest", str(bogus)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0


def test_sync_routes_python_and_typescript_configs(tmp_path: Path) -> None:
    python_dest = tmp_path / "python"
    typescript_dest = tmp_path / "typescript"
    python_dest.mkdir()
    typescript_dest.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--dest",
            str(tmp_path),
            "--python-dest",
            str(python_dest),
            "--typescript-dest",
            str(typescript_dest),
        ],
        check=True,
    )
    assert (python_dest / ".ruff-strict.toml").is_file()
    assert (python_dest / ".pyright-strict.json").is_file()
    assert not (python_dest / "eslint.strict.mjs").exists()
    assert (typescript_dest / "eslint.strict.mjs").is_file()
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert (tmp_path / ".taplo.toml").is_file()
    assert (tmp_path / ".yamllint.yaml").is_file()


def test_repository_root_must_exist_even_with_an_explicit_routed_destination(tmp_path: Path) -> None:
    python_dest = tmp_path / "python"
    python_dest.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--dest",
            str(tmp_path / "unused-and-missing"),
            "--python-dest",
            str(python_dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "is not a directory" in proc.stderr
    assert not (python_dest / ".ruff-strict.toml").exists()


def test_sync_rejects_symlink_destination_file(tmp_path: Path) -> None:
    victim = tmp_path / "victim.toml"
    victim.write_text("do not overwrite\n")
    (tmp_path / ".ruff-strict.toml").symlink_to(victim)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--force",
            "--dest",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "invalid:" in proc.stdout
    assert victim.read_text() == "do not overwrite\n"


def test_sync_check_accepts_matching_canonical_symlink_inside_repository(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.toml"
    canonical.write_bytes(RUFF_STRICT.read_bytes())
    (tmp_path / ".ruff-strict.toml").symlink_to(canonical)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--check",
            "--dest",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok:" in proc.stdout


def test_sync_check_rejects_matching_symlink_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_bytes(RUFF_STRICT.read_bytes())
    (tmp_path / ".ruff-strict.toml").symlink_to(outside)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--check",
            "--dest",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "invalid:" in proc.stdout


def test_sync_rejects_non_regular_destination_file(tmp_path: Path) -> None:
    (tmp_path / ".ruff-strict.toml").mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--force",
            "--dest",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2


def test_sync_accepts_a_symlinked_repository_root_but_not_a_symlinked_file(tmp_path: Path) -> None:
    real_dest = tmp_path / "real"
    real_dest.mkdir()
    linked_dest = tmp_path / "linked"
    linked_dest.symlink_to(real_dest, target_is_directory=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--dest",
            str(linked_dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert (real_dest / ".ruff-strict.toml").is_file()


def test_sync_accepts_a_symlinked_ancestor_that_resolves_inside_the_root(tmp_path: Path) -> None:
    real_dest = tmp_path / "real"
    nested_dest = real_dest / "nested"
    nested_dest.mkdir(parents=True)
    linked_dest = tmp_path / "linked"
    linked_dest.symlink_to(real_dest, target_is_directory=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--force",
            "--dest",
            str(linked_dest / "nested"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert (nested_dest / ".ruff-strict.toml").is_file()


def test_sync_rejects_an_explicit_destination_outside_the_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_lint_configs",
            "sync",
            "--only",
            "ruff",
            "--dest",
            str(root),
            "--python-dest",
            str(outside),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "escapes repository root" in proc.stderr
    assert not (outside / ".ruff-strict.toml").exists()


def test_sync_check_detects_drift(tmp_path: Path) -> None:
    sync = [sys.executable, "-m", "sarj_lint_configs", "sync", "--dest", str(tmp_path)]
    subprocess.run(sync, check=True)
    assert subprocess.run([*sync, "--check"], check=False).returncode == 0

    (tmp_path / ".ruff-strict.toml").write_text("drift\n")
    assert subprocess.run([*sync, "--check"], check=False).returncode == 1


def test_ruff_consumes_synced_extend_file(tmp_path: Path) -> None:
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nextend = ".ruff-strict.toml"\n')
    (tmp_path / "ok.py").write_text("x = 1\n")
    proc = subprocess.run(
        ["ruff", "check", "--no-cache", str(tmp_path / "ok.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "error reading config" not in proc.stderr.lower()
    assert "could not resolve" not in proc.stderr.lower()


@pytest.mark.parametrize(
    "source",
    [
        "def f() -> int:\n    return 1\n",
        'def f() -> int:\n    """does a thing"""\n    return 1\n',
    ],
)
def test_ruff_does_not_require_or_police_docstrings(tmp_path: Path, source: str) -> None:
    pytest.importorskip("ruff", reason="ruff not installed in this env")
    subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "sync", "--only", "ruff", "--dest", str(tmp_path)],
        check=True,
    )
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nextend = ".ruff-strict.toml"\n')
    probe = tmp_path / "probe.py"
    probe.write_text(source)

    proc = subprocess.run(
        ["ruff", "check", "--no-cache", str(probe)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_ruff_ignores_sections_forbidden_by_typed_docstring_policy() -> None:
    parsed: object = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.as_table(manifest.as_table(parsed).get("lint"))
    ignored = manifest.list_field(lint, "ignore")

    assert {"DOC201", "DOC402"} <= {item for item in ignored if isinstance(item, str)}


def test_eslint_module_sort_does_not_conflict_with_imports_first() -> None:
    config = ESLINT_STRICT.read_text()

    assert '"perfectionist/sort-modules": "off"' in config
    assert '"perfectionist/sort-objects": "off"' in config


def test_eslint_async_and_void_rules_have_single_authorities() -> None:
    config = ESLINT_STRICT.read_text()

    assert '"@typescript-eslint/promise-function-async": "off"' in config
    assert '"@typescript-eslint/no-inferrable-types": "off"' in config
    assert "{ ignoreArrowShorthand: true }" in config
    assert '"unicorn/no-thenable": "off"' in config
    assert '"unicorn/no-useless-undefined": "off"' in config
    assert '"unicorn/no-useless-switch-case": "off"' in config
    assert '"react/forbid-component-props": "off"' in config
    assert '"react/forbid-dom-props": "off"' in config
