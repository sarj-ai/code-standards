from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.process import ProcessCancelledError, initialize_process_cancellation


_INPUTS = (
    ("fixture.py", "VALUE = 1\n"),
    ("query.sql", "SELECT id FROM items;\n"),
    ("main.tf", 'terraform { required_version = ">= 1.0" }\n'),
    ("notes.md", "A short note.\n"),
)


@pytest.mark.parametrize("cancel_after", ["before-dispatch", *(name for name, _ in _INPUTS)])
def test_cancelled_native_analysis_stops_real_engines_and_next_invocation_is_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_after: str
) -> None:
    paths = [tmp_path / name for name, _ in _INPUTS]
    for path, (_, content) in zip(paths, _INPUTS, strict=True):
        path.write_text(content)
    cancellation = Event()
    captured: list[str] = []
    read = Path.read_bytes

    def observe_read(path: Path) -> bytes:
        raw = read(path)
        if path in paths:
            captured.append(path.name)
            if path.name == cancel_after:
                cancellation.set()
        return raw

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- signal cancellation after the real selected-source read; preserve all actual engines and diagnostics.
        Path, "read_bytes", observe_read
    )
    if cancel_after == "before-dispatch":
        cancellation.set()
    with ThreadPoolExecutor(
        max_workers=1, initializer=initialize_process_cancellation, initargs=(cancellation,)
    ) as workers:
        pending = workers.submit(analyze, [str(path) for path in paths], root=tmp_path)
        with pytest.raises(ProcessCancelledError, match="analysis process cancelled"):
            pending.result(timeout=30)

    expected = [name for name, _ in _INPUTS]
    stopped_after = 0 if cancel_after == "before-dispatch" else expected.index(cancel_after) + 1
    assert cancellation.is_set()
    assert captured == expected[:stopped_after]

    captured.clear()
    fresh_cancellation = Event()
    with ThreadPoolExecutor(
        max_workers=1, initializer=initialize_process_cancellation, initargs=(fresh_cancellation,)
    ) as workers:
        report = workers.submit(analyze, [str(path) for path in paths], root=tmp_path).result(timeout=30)

    assert not fresh_cancellation.is_set()
    assert captured == expected
    assert report.completion is Completion.COMPLETE
    assert {tool.name for tool in report.tools} == {
        "sarj-python-lint",
        "sarj-sql-lint",
        "sarj-iac-lint",
        "sarj-text-lint",
    }


def test_cancelled_native_analysis_keeps_empty_input_a_noop(tmp_path: Path) -> None:
    cancellation = Event()
    cancellation.set()
    with ThreadPoolExecutor(
        max_workers=1, initializer=initialize_process_cancellation, initargs=(cancellation,)
    ) as workers:
        report = workers.submit(analyze, [], root=tmp_path).result(timeout=30)

    assert report.completion is Completion.COMPLETE
    assert not report.tools
