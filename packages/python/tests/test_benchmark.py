from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint import benchmark
from sarj_python_lint.benchmark import measure
from sarj_python_lint.rule_base import AutofixPolicy, Diagnostic, DiagnosticSubject, Fix, TextEdit


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint.benchmark import BenchmarkReport


_PARITY_SOURCE = "value = 1\nother = 2\nthird = 3\n"
_PARITY_EDITS = (TextEdit(1, 1, 1, 6, "first"), TextEdit(2, 1, 2, 6, "second"))
_PARITY_FIX = Fix("Rename values", AutofixPolicy.SAFE, sha256(_PARITY_SOURCE.encode()).hexdigest(), _PARITY_EDITS)
_PARITY_OTHER_FIX = replace(_PARITY_FIX, title="Rename third", edits=(TextEdit(3, 1, 3, 6, "last"),))
_PARITY_DIAGNOSTIC = Diagnostic(
    Path("app.py"), 1, 1, "SARJ094", "same visible diagnostic", fixes=(_PARITY_FIX, _PARITY_OTHER_FIX)
)


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(replace(_PARITY_DIAGNOSTIC, subject=DiagnosticSubject.RETURN), id="subject"),
        pytest.param(replace(_PARITY_DIAGNOSTIC, fixes=()), id="fixes-missing"),
        pytest.param(
            replace(_PARITY_DIAGNOSTIC, fixes=(replace(_PARITY_FIX, title="Other title"), _PARITY_OTHER_FIX)),
            id="fix-title",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(replace(_PARITY_FIX, safety=AutofixPolicy.SUGGESTION), _PARITY_OTHER_FIX),
            ),
            id="fix-safety",
        ),
        pytest.param(
            replace(_PARITY_DIAGNOSTIC, fixes=(replace(_PARITY_FIX, source_hash="0" * 64), _PARITY_OTHER_FIX)),
            id="fix-source-hash",
        ),
        pytest.param(
            replace(_PARITY_DIAGNOSTIC, fixes=(replace(_PARITY_FIX, edits=()), _PARITY_OTHER_FIX)),
            id="edits-missing",
        ),
        pytest.param(replace(_PARITY_DIAGNOSTIC, fixes=(_PARITY_OTHER_FIX, _PARITY_FIX)), id="fix-order"),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(replace(_PARITY_FIX, edits=tuple(reversed(_PARITY_EDITS))), _PARITY_OTHER_FIX),
            ),
            id="edit-order",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(
                    replace(_PARITY_FIX, edits=(replace(_PARITY_EDITS[0], start_line=2), _PARITY_EDITS[1])),
                    _PARITY_OTHER_FIX,
                ),
            ),
            id="edit-start-line",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(
                    replace(_PARITY_FIX, edits=(replace(_PARITY_EDITS[0], start_col=2), _PARITY_EDITS[1])),
                    _PARITY_OTHER_FIX,
                ),
            ),
            id="edit-start-column",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(
                    replace(_PARITY_FIX, edits=(replace(_PARITY_EDITS[0], end_line=2), _PARITY_EDITS[1])),
                    _PARITY_OTHER_FIX,
                ),
            ),
            id="edit-end-line",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(
                    replace(_PARITY_FIX, edits=(replace(_PARITY_EDITS[0], end_col=5), _PARITY_EDITS[1])),
                    _PARITY_OTHER_FIX,
                ),
            ),
            id="edit-end-column",
        ),
        pytest.param(
            replace(
                _PARITY_DIAGNOSTIC,
                fixes=(
                    replace(_PARITY_FIX, edits=(replace(_PARITY_EDITS[0], replacement="renamed"), _PARITY_EDITS[1])),
                    _PARITY_OTHER_FIX,
                ),
            ),
            id="edit-replacement",
        ),
    ],
)
def test_benchmark_rejects_changed_native_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: Diagnostic
) -> None:
    path = tmp_path / "app.py"
    path.write_text(_PARITY_SOURCE, encoding="utf-8")
    original = replace(_PARITY_DIAGNOSTIC, path=path)
    changed = replace(changed, path=path)
    assert original != changed
    outputs = iter(([original], [changed]))

    def analyze(_rule_ids: Sequence[str], _paths: list[Path]) -> list[Diagnostic]:
        return next(outputs)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- inject native payloads at the result boundary; real digesting and the repetition guard remain active.
        benchmark, "analyze", analyze
    )
    with pytest.raises(RuntimeError, match="diagnostics changed between benchmark repetitions"):
        measure([path], ["no-dunder-all"], repeats=2)


def test_benchmark_rejects_native_payload_order_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "app.py"
    path.write_text(_PARITY_SOURCE, encoding="utf-8")
    original = replace(_PARITY_DIAGNOSTIC, path=path)
    other = replace(original, subject=DiagnosticSubject.RETURN)
    outputs = iter(([original, other], [other, original]))

    def analyze(_rule_ids: Sequence[str], _paths: list[Path]) -> list[Diagnostic]:
        return next(outputs)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- vary only native payload order while exercising the real benchmark consistency guard.
        benchmark, "analyze", analyze
    )
    with pytest.raises(RuntimeError, match="diagnostics changed between benchmark repetitions"):
        measure([path], ["no-dunder-all"], repeats=2)


def test_full_native_payload_fingerprint_is_independent_of_checkout_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def analyze(_rule_ids: Sequence[str], paths: list[Path]) -> list[Diagnostic]:
        return [replace(_PARITY_DIAGNOSTIC, path=paths[0], subject=DiagnosticSubject.RETURN)]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- hold a complete native payload constant across real corpus roots, retaining actual path normalization and hashing.
        benchmark, "analyze", analyze
    )
    reports: list[BenchmarkReport] = []
    for name in ("first", "second"):
        path = tmp_path / name / "app.py"
        path.parent.mkdir()
        path.write_text(_PARITY_SOURCE, encoding="utf-8")
        reports.append(measure([path], ["no-dunder-all"], repeats=2))
    assert reports[0].source_digest == reports[1].source_digest
    assert reports[0].samples[0].diagnostic_digest == reports[1].samples[0].diagnostic_digest


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
    assert all(
        sample.memory_scope == ("unsupported" if sample.peak_memory_bytes is None else "process-lifetime-self")
        for sample in report.samples
    )
    path.write_text("value = 1\n", encoding="utf-8")
    changed = measure([path], ["no-dunder-all"], repeats=1)
    assert changed.source_digest != report.source_digest
    assert changed.samples[0].diagnostics == 0


def test_benchmark_rejects_empty_repetitions() -> None:
    with pytest.raises(ValueError, match="repeats must be positive"):
        measure([], repeats=0)


@pytest.mark.parametrize(
    ("peak", "scope"), [(123, "process-lifetime-self"), (None, "unsupported")], ids=("measured", "unsupported")
)
def test_benchmark_sample_preserves_four_positional_arguments(peak: int | None, scope: str) -> None:
    sample = benchmark.BenchmarkSample(0.25, 1, "digest", peak)
    assert sample.seconds == pytest.approx(0.25)
    assert sample.diagnostics == 1
    assert sample.diagnostic_digest == "digest"
    assert sample.peak_memory_bytes == peak
    assert sample.memory_scope == scope


def test_benchmark_reports_unsupported_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "app.py"
    path.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- force the optional platform-memory boundary while preserving real analysis and its unsupported-result mapping.
        benchmark, "peak_memory_bytes", lambda: None
    )
    sample = measure([path], ["no-dunder-all"], repeats=1).samples[0]
    assert sample.peak_memory_bytes is None
    assert sample.memory_scope == "unsupported"


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
