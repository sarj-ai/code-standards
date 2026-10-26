from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts import RuleId


_RULES = ("no-input-model-mutation", "no-before-validator-input-mutation", "no-unused-copy-result")


@pytest.mark.skipif(sys.version_info < (3, 15), reason="Dictionary-unpacking comprehensions require Python 3.15")
@pytest.mark.parametrize(
    "body",
    [
        "result = {**item for item in items}\n",
        "merge = lambda items: {**item for item in items}\n",
        "consume({**item for item in items})\n",
        "class Client:\n    def __init__(self, items):\n        self.values = {**item for item in items}\n",
    ],
)
@pytest.mark.parametrize("filename", ["app/helpers.py", "tests/test_helpers.py"])
def test_python_315_unpacking_runs_all_native_rules(body: str, filename: str, tmp_path: Path) -> None:
    source = "from typing import Any\n" + body + "def record() -> dict[str, Any]: ...\n"
    findings = check_source([rule() for rule in REGISTRY.values()], tmp_path / filename, source)
    assert "SARJ447" in {finding.code for finding in findings}


@pytest.mark.skipif(sys.version_info < (3, 15), reason="Dictionary-unpacking comprehensions require Python 3.15")
@pytest.mark.parametrize("expression", ["part", "part.pop('nested')"])
def test_unpacking_keeps_before_validator_mutation_ownership(expression: str, tmp_path: Path) -> None:
    target = tmp_path / "records.py"
    target.write_text(
        "from pydantic import BaseModel, field_validator\n"
        "class Record(BaseModel):\n    values: dict[str, object]\n"
        "    @field_validator('values', mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: list[dict[str, object]]) -> dict[str, object]:\n"
        f"        result = {{**{expression} for part in data}}\n"
        "        result['added'] = True\n        return result\n"
    )
    findings = analyze(list(_RULES), [target])
    assert [finding.code for finding in findings] == (["SARJ482"] if ".pop" in expression else [])


@pytest.mark.parametrize("rule_id", ["no-unused-copy-result"])
def test_unused_copy_error_enters_blocking_baseline(
    rule_id: RuleId, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = REGISTRY[rule_id].public_examples()[0]
    target = tmp_path / example.focus_path
    target.parent.mkdir(parents=True)
    target.write_text(example.focus_file.source)
    baseline = tmp_path / "baseline.json"
    command = ["check", "--rule", rule_id]
    assert main([*command, str(target)]) == 1
    assert "warning:" not in capsys.readouterr().out
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert REGISTRY[rule_id].code in baseline.read_text()
    assert main([*command, "--baseline", str(baseline), str(target)]) == 0


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
