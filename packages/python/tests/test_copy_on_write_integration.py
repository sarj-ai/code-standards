from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


_RULES = ("no-input-model-mutation", "no-before-validator-input-mutation", "no-unused-copy-result")


@pytest.mark.parametrize("rule_id", _RULES)
def test_warning_does_not_fail_cli_or_enter_blocking_baseline(
    rule_id: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = REGISTRY[rule_id].public_examples()[0]
    target = tmp_path / example.focus_path
    target.parent.mkdir(parents=True)
    target.write_text(example.focus_file.source)
    baseline = tmp_path / "baseline.json"
    command = ["check", "--rule", rule_id]
    assert main([*command, str(target)]) == 0
    assert "warning:" in capsys.readouterr().out
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert baseline.read_text().strip() == "{}"


def test_before_validator_owns_model_input_mutation(tmp_path: Path) -> None:
    target = tmp_path / "models.py"
    target.write_text(
        "from pydantic import BaseModel, model_validator\n"
        "class Record(BaseModel):\n    name: str\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: 'Record'):\n        data.name = 'new'\n        return data\n"
    )
    findings = analyze([*_RULES, "no-frozen-after-validator-field-write"], [target])
    assert [finding.code for finding in findings] == ["SARJ482"]


def test_frozen_after_validator_keeps_existing_diagnostic(tmp_path: Path) -> None:
    target = tmp_path / "models.py"
    target.write_text(
        "from pydantic import BaseModel, ConfigDict, model_validator\n"
        "class Record(BaseModel):\n    model_config = ConfigDict(frozen=True)\n    name: str\n"
        "    @model_validator(mode='after')\n"
        "    def normalize(self):\n        self.name = 'new'\n        return self\n"
    )
    findings = analyze([*_RULES, "no-frozen-after-validator-field-write"], [target])
    assert [finding.code for finding in findings] == ["SARJ401"]
