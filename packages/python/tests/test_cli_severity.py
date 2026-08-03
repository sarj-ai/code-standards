from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_warning_remains_visible_and_nonblocking_when_error_is_baselined(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "# First fact. Second fact.\nwarning_value = 1\n\n# First fact. Second fact. Third fact.\nerror_value = 2\n"
    )
    baseline = tmp_path / "baseline.json"
    rules = ["check", "--rule", "prefer-single-sentence-comment", "--rule", "no-long-comment"]

    assert main([*rules, str(target)]) == 1
    control = capsys.readouterr().out
    assert f"{target}:1:1: SARJ090 warning:" in control
    assert f"{target}:4:1: SARJ091 " in control

    assert main([*rules, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ091": 1}}
    capsys.readouterr()

    assert main([*rules, "--baseline", str(baseline), str(target)]) == 0
    checked = capsys.readouterr().out.splitlines()
    assert len(checked) == 1
    assert checked[0].startswith(f"{target}:1:1: SARJ090 warning:")
