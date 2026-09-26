from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.benchmark import measure


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.benchmark import BenchmarkReport


def test_benchmark_reports_reproducible_findings_and_changed_input(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    source = "__all__ = ['value']\nvalue = 1\n"
    path.write_text(source, encoding="utf-8")
    report = measure([path], ["no-dunder-all"], repeats=2)
    assert report.files == 1
    assert report.source_bytes == len(source.encode())
    assert all(sample.diagnostics == 1 for sample in report.samples)
    assert len({sample.diagnostic_digest for sample in report.samples}) == 1
    assert all(
        sample.seconds > 0 and (sample.peak_memory_bytes is None or sample.peak_memory_bytes > 0)
        for sample in report.samples
    )
    path.write_text("value = 1\n", encoding="utf-8")
    changed = measure([path], ["no-dunder-all"], repeats=1)
    assert changed.source_digest != report.source_digest
    assert changed.samples[0].diagnostics == 0


def test_benchmark_rejects_empty_repetitions() -> None:
    with pytest.raises(ValueError, match="repeats must be positive"):
        measure([], repeats=0)


def test_fingerprints_are_independent_of_checkout_directory(tmp_path: Path) -> None:
    reports: list[BenchmarkReport] = []
    for name in ("first", "second"):
        path = tmp_path / name / "app.py"
        path.parent.mkdir()
        path.write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")
        reports.append(measure([path], ["no-dunder-all"], repeats=1))
    first, second = reports
    assert first.source_digest == second.source_digest
    assert first.samples[0].diagnostic_digest == second.samples[0].diagnostic_digest


def test_benchmark_rejects_missing_inputs_and_unknown_rules(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one Python source"):
        measure([])
    with pytest.raises(ValueError, match="input does not exist"):
        measure([tmp_path / "missing.py"])
    with pytest.raises(ValueError, match="unknown rule"):
        measure([], ["not-a-real-rule"])


@pytest.mark.skipif(sys.platform == "win32", reason="Creating symlinks can require elevated Windows privileges")
def test_benchmark_preserves_generated_symlink_classification(tmp_path: Path) -> None:
    target = tmp_path / "authored.py"
    target.write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")
    link = tmp_path / "generated" / "alias.py"
    link.parent.mkdir()
    link.symlink_to(target)
    report = measure([link], ["no-dunder-all"], repeats=1)
    assert report.samples[0].diagnostics == 0
