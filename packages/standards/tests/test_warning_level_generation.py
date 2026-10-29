from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import NamedTuple

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.repository import config_generation


class _RepositoryFiles(NamedTuple):
    catalog: Path
    preset: Path
    strict: Path
    application: Path


def _repository(root: Path) -> _RepositoryFiles:
    configs = root / "packages/standards/src/sarj_standards/configs"
    preset = root / "packages/typescript/src/index.ts"
    configs.mkdir(parents=True)
    preset.parent.mkdir(parents=True)
    catalog = root / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json"
    catalog.parent.mkdir(parents=True)
    strict = configs / "eslint.strict.ts"
    application = configs / "eslint.application.mjs"
    catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:first-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    preset.write_text(
        'const ADVISORY_RULES = [\n  "@sarj/stale-rule",\n] as const;\n'
        'const RECOMMENDED_RULES = {\n  "@sarj/first-rule": "error",\n  "@sarj/second-rule": "warn",\n} as const;\n'
        'const STRICT_RULES = {\n  "@sarj/first-rule": ["error", { option: true }],\n'
        '  "@sarj/second-rule": "warn",\n} as const;\n',
        encoding="utf-8",
    )
    strict.write_text(
        'const rules = {\n  "@sarj/first-rule": ["error", { option: true }],\n'
        '  "@sarj/second-rule": "warn",\n};\n'
        "function createConfig() {\n  return [{\n          paths: [\n          ],\n"
        '          patterns: ["*/index", "*/index.ts"],\n'
        "  }] as unknown as Linter.Config[];\n}\n\nconst config = createConfig();\nexport default config;\n",
        encoding="utf-8",
    )
    application.write_text("stale\n", encoding="utf-8")
    return _RepositoryFiles(catalog, preset, strict, application)


def test_source_catalog_drives_plugin_presets_and_generated_configs(tmp_path: Path) -> None:
    _catalog, preset, strict, application = _repository(tmp_path)

    assert not config_generation.sync_warning_levels(tmp_path, check=True)
    assert config_generation.sync_warning_levels(tmp_path, check=False)
    assert config_generation.sync_warning_levels(tmp_path, check=True)
    assert strict.with_suffix(".mjs").read_text(encoding="utf-8") == config_generation.render_legacy_eslint(
        strict.read_text(encoding="utf-8")
    )

    preset_text = preset.read_text(encoding="utf-8")
    strict_text = strict.read_text(encoding="utf-8")
    application_text = application.read_text(encoding="utf-8")
    assert 'const ADVISORY_RULES = [\n  "@sarj/first-rule",\n] as const;' in preset_text
    assert '"@sarj/first-rule": ["warn", { option: true }]' in preset_text
    assert '"@sarj/second-rule": "error"' in preset_text
    assert '"@sarj/first-rule": ["warn", { option: true }]' in strict_text
    assert '"@sarj/second-rule": "error"' in strict_text
    assert 'export { createConfig, default } from "./eslint.strict.mjs";' in application_text


def test_warning_parity_check_detects_drift_in_either_direction(tmp_path: Path) -> None:
    catalog, _preset, strict, _application = _repository(tmp_path)
    config_generation.sync_warning_levels(tmp_path, check=False)
    strict.write_text(strict.read_text(encoding="utf-8").replace('"warn"', '"error"', 1), encoding="utf-8")
    assert not config_generation.sync_warning_levels(tmp_path, check=True)

    catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:second-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    assert not config_generation.sync_warning_levels(tmp_path, check=True)


def test_single_policy_table_tracks_catalog_levels_without_changing_options_or_membership(tmp_path: Path) -> None:
    catalog, preset, strict, _application = _policy_repository(tmp_path)
    before = preset.read_text(encoding="utf-8")

    assert not config_generation.sync_warning_levels(tmp_path, check=True)
    assert config_generation.sync_warning_levels(tmp_path, check=False)
    assert config_generation.sync_warning_levels(tmp_path, check=True)
    expected = before.replace('"@sarj/first-rule": ["error"', '"@sarj/first-rule": ["warn"')
    expected = expected.replace('    "warn",\n    "strict",', '    "error",\n    "strict",')
    assert preset.read_text(encoding="utf-8") == expected
    assert '"@sarj/first-rule": ["warn", { option: true }]' in strict.read_text(encoding="utf-8")

    catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:second-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    assert not config_generation.sync_warning_levels(tmp_path, check=True)
    assert config_generation.sync_warning_levels(tmp_path, check=False)
    assert config_generation.sync_warning_levels(tmp_path, check=True)
    assert preset.read_text(encoding="utf-8") == before


def _policy_repository(root: Path) -> _RepositoryFiles:
    files = _repository(root)
    files.preset.write_text(
        "const RULE_POLICY = {\n"
        '  "@sarj/first-rule": ["error", "both"],\n'
        '  "@sarj/second-rule": [\n'
        '    "warn",\n'
        '    "strict",\n'
        "    () => [{ option: true }] as const,\n"
        "  ],\n"
        '  "no-restricted-imports": ["shared", "both", LIBRARY_IMPORT_POLICY],\n'
        "} as const satisfies PresetPolicy;\n"
        "const ADVISORY_RULES = Object.keys(RULE_POLICY).filter(isAdvisoryRuleName).toSorted();\n"
        'const RECOMMENDED_RULES = presetRules("recommended");\n'
        'const STRICT_RULES = presetRules("strict");\n',
        encoding="utf-8",
    )
    return files


def test_single_policy_missing_warning_rule_refuses_every_write(tmp_path: Path) -> None:
    files = _policy_repository(tmp_path)
    files.catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:missing-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(ValueError, match="missing warning-stage ESLint rules: missing-rule"):
        config_generation.sync_warning_levels(tmp_path, check=False)
    assert tuple(path.read_bytes() for path in files) == before


@pytest.mark.parametrize("variant", ["duplicate", "missing-end", "orphan-end", "mixed-legacy", "reversed", "unknown"])
def test_ambiguous_or_unknown_policy_format_refuses_every_write(tmp_path: Path, variant: str) -> None:
    files = _policy_repository(tmp_path)
    source = files.preset.read_text(encoding="utf-8")
    files.preset.write_text(_invalid_policy_source(source, variant), encoding="utf-8")
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(ValueError, match="TypeScript preset"):
        config_generation.sync_warning_levels(tmp_path, check=False)
    assert tuple(path.read_bytes() for path in files) == before


def _invalid_policy_source(source: str, variant: str) -> str:
    opening = "const RULE_POLICY = {\n"
    closing = "} as const satisfies PresetPolicy;"
    if variant == "duplicate":
        return source.replace(opening, opening + opening)
    if variant == "missing-end":
        return source.replace(closing, "")
    if variant == "orphan-end":
        return source.replace(opening, "")
    if variant == "mixed-legacy":
        return f"{source}const ADVISORY_RULES = [\n] as const;\n"
    if variant == "reversed":
        return closing + "\n" + source.replace(closing, "")
    return "const RULE_POLICY = unknownPolicy();\n"


def test_canonical_library_generation_is_idempotent() -> None:
    assert config_generation.sync(check=True)
    generated = config_generation.generated_configs()
    strict = next(text for path, text in generated.items() if path.name == "eslint.strict.ts")
    assert config_generation.render_eslint_strict(strict) == strict
    assert '"@sarj/no-restricted-library-load"' in strict
    assert '"module": "axios"' in strict
    assert '"@sarj/prefer-native-random-uuid": "error"' in strict


@pytest.mark.parametrize("decorator", ["command", "callback"])
def test_typer_annotations_remain_available_at_runtime(decorator: str) -> None:
    source = (
        "from __future__ import annotations\nfrom pathlib import Path\nimport typer\n"
        f"app = typer.Typer()\n@app.{decorator}()\ndef run(path: Path) -> None:\n    print(path)\n"
    )
    result = subprocess.run(
        [
            "ruff",
            "check",
            "--config",
            str(CONFIGS_DIR / "ruff.strict.toml"),
            "--select",
            "TC003",
            "--stdin-filename",
            "src/tool.py",
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
