from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import RuleExample


_RULES = ("no-test-method-grafting", "no-mocked-pydantic-value-object")
_NEIGHBORS = (
    "mock-without-spec",
    "over-mocked-test",
    "prefer-injected-dependency-over-monkeypatch",
    "async-mock-call-without-await-assertion",
)


@pytest.mark.parametrize("rule_id", _RULES)
def test_new_warning_does_not_enter_blocking_baseline(
    rule_id: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example: RuleExample = REGISTRY[rule_id].public_examples()[0]
    target = tmp_path / example.focus_path
    target.parent.mkdir(parents=True)
    target.write_text(example.focus_file.source)
    baseline = tmp_path / "baseline.json"
    command = ["check", "--rule", rule_id]

    assert main([*command, str(target)]) == 0
    assert "warning:" in capsys.readouterr().out
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert baseline.read_text().strip() == "{}"


@pytest.mark.parametrize("rule_id", _RULES)
def test_new_rules_do_not_duplicate_neighbor_findings(rule_id: str, tmp_path: Path) -> None:
    example = REGISTRY[rule_id].public_examples()[0]
    target = tmp_path / example.focus_path
    target.parent.mkdir(parents=True)
    target.write_text(example.focus_file.source)

    findings = analyze([rule_id, *_NEIGHBORS], [target])

    assert [finding.code for finding in findings] == [REGISTRY[rule_id].code]


def test_method_graft_does_not_also_report_a_field_only_model_mock(tmp_path: Path) -> None:
    target = tmp_path / "test_profile.py"
    target.write_text(
        "from unittest.mock import Mock\n"
        "from pydantic import BaseModel\n"
        "class Profile(BaseModel):\n"
        "    language: str\n"
        "    def resolve(self):\n"
        "        return self.language\n"
        "def test_profile():\n"
        "    profile = Mock(spec=Profile)\n"
        "    profile.language = 'ar'\n"
        "    profile.resolve = lambda: 'ar'\n"
    )

    assert [finding.code for finding in analyze(list(_RULES), [target])] == ["SARJ478"]
