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
    strict: Path


def _repository(root: Path) -> _RepositoryFiles:
    configs = root / "packages/standards/src/sarj_standards/configs"
    configs.mkdir(parents=True)
    catalog = root / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json"
    catalog.parent.mkdir(parents=True)
    strict = configs / "oxlint.strict.mts"
    catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:first-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    strict.write_text(
        'import { defineConfig } from "oxlint";\n'
        "// BEGIN GENERATED LIBRARY POLICY\n// END GENERATED LIBRARY POLICY\n"
        'const RULES = {\n  "@sarj/first-rule": ["error", { option: true }],\n'
        '  "@sarj/second-rule": "warn",\n};\n'
        "export default defineConfig({ rules: RULES });\n",
        encoding="utf-8",
    )
    return _RepositoryFiles(catalog, strict)


def test_source_catalog_drives_oxlint_rule_levels(tmp_path: Path) -> None:
    _catalog, strict = _repository(tmp_path)

    assert not config_generation.sync_warning_levels(tmp_path, check=True)
    assert config_generation.sync_warning_levels(tmp_path, check=False)
    assert config_generation.sync_warning_levels(tmp_path, check=True)

    strict_text = strict.read_text(encoding="utf-8")
    assert '"@sarj/first-rule": ["warn", { option: true }]' in strict_text
    assert '"@sarj/second-rule": "error"' in strict_text


def test_warning_parity_check_detects_drift_in_either_direction(tmp_path: Path) -> None:
    catalog, strict = _repository(tmp_path)
    config_generation.sync_warning_levels(tmp_path, check=False)
    strict.write_text(strict.read_text(encoding="utf-8").replace('"warn"', '"error"', 1), encoding="utf-8")
    assert not config_generation.sync_warning_levels(tmp_path, check=True)

    catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:second-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    assert not config_generation.sync_warning_levels(tmp_path, check=True)


def test_missing_warning_rule_refuses_every_write(tmp_path: Path) -> None:
    files = _repository(tmp_path)
    files.catalog.write_text(
        json.dumps({"schemaVersion": 1, "rules": [{"key": "eslint:missing-rule", "defaultLevel": "warning"}]}),
        encoding="utf-8",
    )
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(ValueError, match="missing warning-stage Oxlint rules: missing-rule"):
        config_generation.sync_warning_levels(tmp_path, check=False)
    assert tuple(path.read_bytes() for path in files) == before


def test_canonical_library_generation_is_idempotent() -> None:
    assert config_generation.sync(check=True)
    generated = config_generation.generated_configs()
    strict = next(text for path, text in generated.items() if path.name == "oxlint.strict.mts")
    assert config_generation.render_oxlint_strict(strict) == strict
    assert '"@sarj/no-restricted-library-load": ["error", { libraries: LIBRARY_LOADS }]' in strict
    assert '{"id": "LIB101", "module": "axios"' in strict
    assert '{"group": ["axios/*"], "message": "LIB101:' in strict
    assert '{"message": "LIB101:' in strict


def test_oxlint_library_policy_needs_exactly_one_generated_block() -> None:
    with pytest.raises(ValueError, match="exactly one GENERATED LIBRARY POLICY block"):
        config_generation.render_oxlint_strict("const RULES = {};\n")


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
