from __future__ import annotations

from importlib.util import find_spec
import json
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.rule_metadata import authored_descriptors

from sarj_standards.cli.main import main
from sarj_standards.libs.repository import rule_inventory_artifact, rule_maintenance


if TYPE_CHECKING:
    from pydantic import JsonValue


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("schema", [True, 1.0, "1", None], ids=("boolean", "float", "string", "null"))
def test_inventory_requires_an_integer_schema_version(schema: bool | float | str | None) -> None:
    with pytest.raises(ValueError, match="unsupported rule inventory schemaVersion"):
        rule_inventory_artifact.validate({"schemaVersion": schema, "rules": []})


def test_inventory_load_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text('{"schemaVersion":1,"rules":[],"rules":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key"):
        rule_inventory_artifact.load(path)


def test_shipped_inventory_matches_live_registries() -> None:
    python_entries: list[rule_inventory_artifact.RuleInventoryEntry] = []
    for entry in authored_descriptors():
        module = entry.module.replace(".", "/")
        name = module.rsplit("/", maxsplit=1)[-1]
        python_entries.append(
            {
                "family": "python",
                "id": entry.rule_id,
                "code": entry.code,
                "source": f"packages/python/src/{module}.py",
                "test": f"packages/python/tests/rules/test_{name}.py",
            }
        )
    expected = rule_inventory_artifact.validate(
        {"schemaVersion": 1, "rules": rule_maintenance.inventory(ROOT, python_entries=python_entries)}
    )
    assert rule_inventory_artifact.load() == expected
    if _uses_selected_python_sources(ROOT):
        result = rule_inventory_artifact.sync(ROOT, check=True)
        assert result.status == 0, result.message
    else:
        with pytest.raises(RuntimeError, match="selected checkout's source packages"):
            rule_inventory_artifact.sync(ROOT, check=True)


def _uses_selected_python_sources(root: Path) -> bool:
    packages = (("standards", "sarj_standards"), ("contracts", "sarj_rule_contracts"), ("python", "sarj_python_lint"))
    for package, module in packages:
        spec = find_spec(module)
        expected = root / f"packages/{package}/src/{module}/__init__.py"
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected.resolve():
            return False
    return True


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

    output: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
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
    inventory: dict[str, JsonValue] = {
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

    def build_inventory(_root: Path) -> dict[str, JsonValue]:
        return inventory

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- artifact builder interception is the behavior under test.
        rule_inventory_artifact, "build", build_inventory
    )

    first = rule_inventory_artifact.sync(tmp_path, check=False)
    second = rule_inventory_artifact.sync(tmp_path, check=True)

    assert first.message == "updated: rule-inventory.v1.json"
    assert second.status == 0
    assert destination.read_text(encoding="utf-8") == rule_inventory_artifact.render(tmp_path)
