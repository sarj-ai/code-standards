from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from sarj_standards.libs.repository import config_generation


class _RepositoryFiles(NamedTuple):
    warning: Path
    preset: Path
    strict: Path
    application: Path


def _repository(root: Path) -> _RepositoryFiles:
    configs = root / "packages/standards/src/sarj_standards/configs"
    preset = root / "packages/typescript/src/index.ts"
    configs.mkdir(parents=True)
    preset.parent.mkdir(parents=True)
    warning = configs / "rule-warning-levels.v1.json"
    strict = configs / "eslint.strict.mjs"
    application = configs / "eslint.application.mjs"
    warning.write_text(
        json.dumps({"schemaVersion": 1, "rules": ["eslint:first-rule"]}),
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
        "          paths: [\n"
        '          patterns: ["*/index", "*/index.ts"],\n'
        "  ];\n}\n\nconst config = createConfig();\nexport default config;\n",
        encoding="utf-8",
    )
    application.write_text("stale\n", encoding="utf-8")
    return _RepositoryFiles(warning, preset, strict, application)


def test_warning_manifest_drives_plugin_presets_and_generated_configs(tmp_path: Path) -> None:
    _warning, preset, strict, application = _repository(tmp_path)

    assert not config_generation.sync_warning_levels(tmp_path, check=True)
    assert config_generation.sync_warning_levels(tmp_path, check=False)
    assert config_generation.sync_warning_levels(tmp_path, check=True)

    preset_text = preset.read_text(encoding="utf-8")
    strict_text = strict.read_text(encoding="utf-8")
    application_text = application.read_text(encoding="utf-8")
    assert 'const ADVISORY_RULES = [\n  "@sarj/first-rule",\n] as const;' in preset_text
    assert '"@sarj/first-rule": ["warn", { option: true }]' in preset_text
    assert '"@sarj/second-rule": "error"' in preset_text
    assert '"@sarj/first-rule": ["warn", { option: true }]' in strict_text
    assert '"@sarj/second-rule": "error"' in strict_text
    assert '"@sarj/first-rule": ["warn", { option: true }]' in application_text


def test_warning_parity_check_detects_drift_in_either_direction(tmp_path: Path) -> None:
    warning, _preset, strict, _application = _repository(tmp_path)
    config_generation.sync_warning_levels(tmp_path, check=False)
    strict.write_text(strict.read_text(encoding="utf-8").replace('"warn"', '"error"', 1), encoding="utf-8")
    assert not config_generation.sync_warning_levels(tmp_path, check=True)

    warning.write_text(
        json.dumps({"schemaVersion": 1, "rules": ["eslint:second-rule"]}),
        encoding="utf-8",
    )
    assert not config_generation.sync_warning_levels(tmp_path, check=True)
