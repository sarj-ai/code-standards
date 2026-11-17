from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.rules import RuleSelection


if TYPE_CHECKING:
    import pytest


@dataclass(slots=True)
class _CallbackState:
    calls: int = 0


def test_native_path_resolution_scales_with_files_and_rechecks_each_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "service.py"
    resolve = Path.resolve
    callback_state = _CallbackState(calls=0)

    def counted(path: Path, strict: bool = False) -> Path:
        if path == source:
            callback_state.calls += 1
        return resolve(path, strict=strict)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real filesystem resolution; injecting a fake path would miss the repeated I/O this regression measures.
        Path, "resolve", counted
    )
    observed: list[int] = []
    for copies in (4, 40):
        source.write_text("logger.info('request', token=token)\n" * copies, encoding="utf-8")
        callback_state.calls = 0
        report = analyze(
            [str(source)], root=tmp_path, rule_selection=RuleSelection.from_values(("python:no-secret-in-log",))
        )
        findings = [item for item in report.diagnostics if item.code == "SARJ012"]
        assert not report.issues
        assert len(findings) == copies
        assert [item.location.path for item in findings] == [source.name] * copies
        assert findings[-1].location.position is not None
        assert findings[-1].location.position.line == copies - 1
        observed.append(callback_state.calls)
    assert observed[0] == observed[1]
