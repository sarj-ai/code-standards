from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path


def test_benchmark_reports_real_selected_analysis(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "example.py").write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")

    status = cli.main(
        [
            "--root",
            str(tmp_path),
            "maintain",
            "rules",
            "bench",
            "example.py",
            "--rule",
            "python:no-dunder-all",
            "--repeats",
            "2",
        ]
    )

    assert status == 0
    report = parse_json(capsys.readouterr().out)
    assert isinstance(report, dict)
    assert report["files"] == 1
    assert report["rules"] == ["no-dunder-all"]
    samples = report["samples"]
    assert isinstance(samples, list)
    assert len(samples) == 2
    for sample in samples:
        assert isinstance(sample, dict)
        assert sample["diagnostics"] == 1
        assert sample["diagnostic_digest"]


@pytest.mark.parametrize("selector", ["sql:no-select-star", "python:not-a-registered-rule"])
def test_benchmark_rejects_unavailable_rules(tmp_path: Path, capsys: pytest.CaptureFixture[str], selector: str) -> None:
    status = cli.main(["--root", str(tmp_path), "maintain", "rules", "bench", ".", "--rule", selector])

    assert status == 2
    assert "registered python:ID" in capsys.readouterr().err
