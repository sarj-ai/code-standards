from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_blocking_error_is_recorded_with_other_errors_when_baseline_is_updated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        'class Record:\n    status: str\n    status_choices = ("active", "disabled")\n\n# ----------------\nerror_value = 2\n'
    )
    baseline = tmp_path / "baseline.json"
    rules = ["check", "--rule", "prefer-str-enum", "--rule", "no-comment-cruft"]

    assert main([*rules, str(target)]) == 1
    control = capsys.readouterr().out
    assert "SARJ006 " in control
    assert "SARJ016 " in control

    assert main([*rules, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ006": 1, "SARJ016": 1}}
    baseline_output = capsys.readouterr().out
    assert "2 blocking diagnostics over 1 files; 0 warnings excluded" in baseline_output

    assert main([*rules, "--baseline", str(baseline), str(target)]) == 0
    assert not capsys.readouterr().out


def test_warning_only_baseline_excludes_the_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "example.py"
    target.write_text("VALUES = [1]\n")
    baseline = tmp_path / "baseline.json"

    assert (
        main(
            [
                "check",
                "--rule",
                "prefer-immutable-module-constant",
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


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.py"

    assert main(["check", "--rule", "no-comment-cruft", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err


def test_invalid_baseline_is_a_concise_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("not json", encoding="utf-8")

    status = main(["check", "--rule", "no-comment-cruft", "--baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "invalid baseline" in output.err
    assert "Traceback" not in output.err


def test_baseline_update_requires_an_existing_parent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "missing" / "baseline.json"

    status = main(["check", "--rule", "no-comment-cruft", "--update-baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "baseline parent does not exist" in output.err
    assert "Traceback" not in output.err
