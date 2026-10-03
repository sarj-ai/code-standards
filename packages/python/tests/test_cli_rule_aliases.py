from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("rule_id", ["defect-xfail-requires-strict", "xfail-requires-strict"])
def test_analyze_accepts_authored_historical_rule_aliases(tmp_path: Path, rule_id: str) -> None:
    target = tmp_path / "test_example.py"
    target.write_text(
        'import pytest\n\n@pytest.mark.xfail(reason="BUG: wrong status code")\ndef test_status():\n    assert True\n'
    )

    findings = analyze([rule_id], [target])

    assert [finding.code for finding in findings] == ["SARJ046"]
    assert rule_id not in REGISTRY


def test_analyze_deduplicates_canonical_and_historical_selections(tmp_path: Path) -> None:
    target = tmp_path / "test_example.py"
    target.write_text(
        'import pytest\n\n@pytest.mark.xfail(reason="BUG: wrong status code")\ndef test_status():\n    assert True\n'
    )

    findings = analyze(
        ["xfail-requires-strict", "defect-xfail-requires-explicit-strict", "defect-xfail-requires-strict"], [target]
    )

    assert [finding.code for finding in findings] == ["SARJ046"]


@pytest.mark.parametrize(
    "rule_ids",
    [
        ["prefer-required-constructor-parameters"],
        ["discourage-nullable-constructor-parameters"],
        ["prefer-required-constructor-parameters", "discourage-nullable-constructor-parameters"],
    ],
    ids=("canonical", "historical", "both"),
)
@pytest.mark.parametrize(
    ("signature", "expected_codes"),
    [('room_prefix: str = ""', ["SARJ468"]), ("agent_name: str | None", [])],
    ids=("implicit-empty-string", "explicit-absent-choice"),
)
def test_constructor_rule_rename_keeps_historical_selection_working(
    tmp_path: Path, rule_ids: list[str], signature: str, expected_codes: list[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text(f"class Service:\n    def __init__(self, {signature}) -> None: ...\n")

    findings = analyze(rule_ids, [target])

    assert [finding.code for finding in findings] == expected_codes
    assert "discourage-nullable-constructor-parameters" not in REGISTRY


def test_analyze_rejects_unknown_rule_ids_after_alias_resolution(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        analyze(["xfail-requires-strict", "missing-rule"], [])

    assert failure.value.code == 2
    assert "unknown rule(s): missing-rule\n" in capsys.readouterr().err
