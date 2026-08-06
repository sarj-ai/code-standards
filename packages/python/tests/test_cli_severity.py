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
    target.write_text("# First fact. Second fact.\nwarning_value = 1\n\n# ----------------\nerror_value = 2\n")
    baseline = tmp_path / "baseline.json"
    rules = ["check", "--rule", "prefer-single-sentence-comment", "--rule", "no-comment-cruft"]

    assert main([*rules, str(target)]) == 1
    control = capsys.readouterr().out
    assert f"{target}:1:1: SARJ090 warning:" in control
    assert f"{target}:4:1: SARJ016 " in control

    assert main([*rules, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ016": 1}}
    baseline_output = capsys.readouterr().out
    assert "1 blocking diagnostics over 1 files; 1 warnings excluded" in baseline_output

    assert main([*rules, "--baseline", str(baseline), str(target)]) == 0
    checked = capsys.readouterr().out.splitlines()
    assert len(checked) == 1
    assert checked[0].startswith(f"{target}:1:1: SARJ090 warning:")


def test_warning_only_baseline_reports_zero_blocking_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text("# First fact. Second fact.\nvalue = 1\n")
    baseline = tmp_path / "baseline.json"

    assert (
        main(
            [
                "check",
                "--rule",
                "prefer-single-sentence-comment",
                "--update-baseline",
                str(baseline),
                str(target),
            ]
        )
        == 0
    )

    assert json.loads(baseline.read_text()) == {}
    assert "0 blocking diagnostics over 0 files; 1 warnings excluded" in capsys.readouterr().out


def test_baseline_written_from_absolute_repo_path_is_portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("# ----------------\nvalue = 2\n")
    baseline = tmp_path / "baseline.json"
    monkeypatch.chdir(tmp_path)
    command = ["check", "--rule", "no-comment-cruft"]

    assert main([*command, "--update-baseline", str(baseline), str(target.resolve())]) == 0
    assert json.loads(baseline.read_text()) == {"src/example.py": {"SARJ016": 1}}
    assert main([*command, "--baseline", str(baseline), "src/example.py"]) == 0
