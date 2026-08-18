from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.repository import rule_inventory_artifact


ROOT = Path(__file__).resolve().parents[3]


def test_shipped_inventory_matches_live_registries() -> None:
    result = rule_inventory_artifact.sync(ROOT, check=True)

    assert result.status == 0, result.message


def test_runtime_load_does_not_import_rule_registries() -> None:
    script = (
        "import contextlib, io, sys; "
        "from sarj_standards.cli.main import main; "
        "blocked = {'sarj_python_lint.rules', 'sarj_sql_lint.rules', "
        "'sarj_iac_lint.rules'}; "
        "output = io.StringIO(); "
        "contextlib.redirect_stdout(output).__enter__(); "
        "status = main(['show', 'rules']); "
        "raise SystemExit(1 if status or blocked & sys.modules.keys() else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_show_rules_prints_versioned_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", "rules"]) == 0

    output: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    assert output["schemaVersion"] == 1
    assert output["rules"]


def test_inventory_validation_rejects_unsorted_rules(tmp_path: Path) -> None:
    inventory_path = tmp_path / "rule-inventory.v1.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "rules": [
                    {
                        "family": "python",
                        "id": "z-rule",
                        "code": "SARJ999",
                        "source": "src/z.py",
                        "test": "tests/test_z.py",
                    },
                    {
                        "family": "python",
                        "id": "a-rule",
                        "code": "SARJ998",
                        "source": "src/a.py",
                        "test": "tests/test_a.py",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sorted by family and id"):
        rule_inventory_artifact.load(inventory_path)


def test_sync_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    destination = tmp_path / "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json"
    destination.parent.mkdir(parents=True)
    inventory: dict[str, object] = {
        "schemaVersion": 1,
        "rules": [
            {
                "family": "python",
                "id": "sample-rule",
                "code": "SARJ999",
                "source": "src/sample.py",
                "test": "tests/test_sample.py",
            }
        ],
    }

    def build_inventory(_root: Path) -> dict[str, object]:
        return inventory

    monkeypatch.setattr(rule_inventory_artifact, "build", build_inventory)

    first = rule_inventory_artifact.sync(tmp_path, check=False)
    second = rule_inventory_artifact.sync(tmp_path, check=True)

    assert first.message == "updated: rule-inventory.v1.json"
    assert second.status == 0
    assert destination.read_text(encoding="utf-8") == rule_inventory_artifact.render(tmp_path)
