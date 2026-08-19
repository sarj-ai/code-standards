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

from sarj_standards import (
    __version__,
    _meta,  # sarj-noqa: SARJ048 — source-tree fallback is under test
)
from sarj_standards._meta import (
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
)
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.repository import config_generation


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

#: Expected fallback independent of the module under test.
_SOURCE_TREE_VERSION = "0.0.0.dev0"


def test_version_string() -> None:
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


def test_pyright_allows_directly_awaited_discarded_results() -> None:
    text = PYRIGHT_STRICT.read_text()
    assert '"reportUnusedCallResult": false' in text
    assert '"reportUnusedCoroutine": "error"' in text


def test_requested_ruff_families_remain_globally_enabled() -> None:
    data = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.table_field(manifest.as_table(data), "lint")
    assert manifest.list_field(lint, "select") == ["ALL"]
    assert lint["future-annotations"] is True
    raw_ignored = manifest.list_field(lint, "ignore")
    assert all(isinstance(code, str) for code in raw_ignored)
    ignored = {code for code in raw_ignored if isinstance(code, str)}
    assert not any(code.startswith(("ANN", "UP")) or re.fullmatch(r"F\d+", code) is not None for code in ignored)
    assert {"PLC0415", "BLE001"}.isdisjoint(ignored)


def test_ruff_rejects_quoted_type_checking_union_annotations(tmp_path: Path) -> None:
    source = tmp_path / "context.py"
    source.write_text(
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from example import BatchId, ScenarioId\n\n\n"
        "class Context:\n"
        '    agent_id: "ScenarioId | None"\n'
        '    batch_id: "BatchId | None" = None\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            "UP037",
            "--config",
            str(RUFF_STRICT),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count('"code": "UP037"') == 2


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION])
def test_s311_is_owned_by_sarj410_in_every_supported_python_test_path(config: Path) -> None:
    data = manifest.as_table(tomllib.loads(config.read_text(encoding="utf-8")))
    lint = manifest.table_field(data, "lint")
    per_file = manifest.table_field(lint, "per-file-ignores")
    patterns = {
        "**/tests/**",
        "**/test/**",
        "**/integration_tests/**",
        "**/test_*.py",
        "**/*_test.py",
        "**/conftest.py",
    }
    assert all("S311" in manifest.list_field(per_file, pattern) for pattern in patterns)
    assert "S311" not in manifest.list_field(lint, "ignore")


def test_random_sampling_has_one_owner_in_tests_and_production(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_sampling.py"
    production_file = tmp_path / "src" / "sampling.py"
    test_file.parent.mkdir()
    production_file.parent.mkdir()
    test_file.write_text(
        "import random\n\n\ndef test_sampling() -> None:\n"
        "    samples = [random.random() for _ in range(10)]\n"
        "    assert len(samples) == 10\n",
        encoding="utf-8",
    )
    production_file.write_text(
        "import random\n\n\ndef sample() -> float:\n    return random.random()\n",
        encoding="utf-8",
    )

    ruff = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            "S311",
            "--config",
            str(RUFF_STRICT),
            str(test_file),
            str(production_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    sarj = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_python_lint",
            "check",
            "--rule",
            "uncontrolled-randomness-in-test",
            str(test_file),
            str(production_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert ruff.returncode == 1, ruff.stdout + ruff.stderr
    assert ruff.stdout.count('"code": "S311"') == 1
    assert str(production_file) in ruff.stdout
    assert str(test_file) not in ruff.stdout
    assert sarj.returncode == 1, sarj.stdout + sarj.stderr
    assert sarj.stdout.count("SARJ410") == 1
    assert str(test_file) in sarj.stdout
    assert str(production_file) not in sarj.stdout


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


def test_python_visibility_contract_is_explicitly_strict() -> None:
    ruff = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.table_field(manifest.as_table(ruff), "lint")
    ignored = set(manifest.list_field(lint, "ignore"))
    assert {"SLF001", "N801", "N802", "N806", "N999", "F401", "F822", "RUF022", "RUF068"}.isdisjoint(ignored)
    assert "PLC2701" in ignored

    raw = PYRIGHT_STRICT.read_text()
    for setting in (
        "reportPrivateUsage",
        "reportPrivateImportUsage",
        "reportPrivateLocalImportUsage",
        "reportUnsupportedDunderAll",
    ):
        assert re.search(rf'"{setting}"\s*:\s*"error"', raw)


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
        [sys.executable, "-m", "sarj_standards", "show", "configs"],
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
        [sys.executable, "-m", "sarj_standards", "show", "config", "ruff"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == str(RUFF_STRICT)


def test_cli_unknown_subcommand_exits_nonzero(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "bogus"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode != 0


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
