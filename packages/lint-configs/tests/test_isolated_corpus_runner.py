"""Corpus rule evaluation cannot accumulate multiple repositories in one process."""

from __future__ import annotations

from datetime import timedelta
import sys
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.corpus import CorpusKind, CorpusSource, snapshot
from sarj_lint_configs.libs.rules import CorpusLintError, corpus_runner, run_isolated_corpora


if TYPE_CHECKING:
    from pathlib import Path


_UNSET_DIGEST = "sha256:" + "0" * 64


def _source(root: Path, name: str) -> CorpusSource:
    unpinned = CorpusSource(name, root, CorpusKind.LOCAL, _UNSET_DIGEST, ("**/*.py",))
    return CorpusSource(name, root, CorpusKind.LOCAL, snapshot(unpinned).digest, ("**/*.py",))


def test_each_corpus_and_bounded_batch_gets_a_fresh_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for index in range(3):
        (first / f"file_{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
    (second / "only.py").write_text("VALUE = 1\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def run(argv: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        cwd = kwargs["cwd"]
        assert isinstance(cwd, type(tmp_path))
        calls.append((argv, cwd))
        empty = SimpleNamespace(retained_bytes=0, lines=0, truncated=False)
        return SimpleNamespace(returncode=0, stdout=empty, stderr=empty)

    monkeypatch.setattr(corpus_runner, "_run_process", run)

    report = run_isolated_corpora(
        (_source(first, "first"), _source(second, "second")),
        ("existing-linter", "check"),
        batch_size=2,
    )

    assert report.files == 4
    assert [batch.files for batch in report.batches] == [2, 1, 1]
    assert [cwd for _argv, cwd in calls] == [first, first, second]
    assert all(len(argv) <= 4 for argv, _cwd in calls)


def test_batch_size_is_deterministically_bounded(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="between 1 and 1000"):
        run_isolated_corpora((_source(corpus, "sample"),), ("linter",), batch_size=1_001)


def test_batches_are_also_bounded_by_encoded_argv_bytes(tmp_path: Path) -> None:
    files = tuple(tmp_path / ("x" * 200) / f"file-{index}.py" for index in range(400))

    batches = corpus_runner.argv_batches(
        files,
        ("linter", "check"),
        batch_size=1_000,
    )

    assert len(batches) > 1
    assert all(
        sum(len(str(argument).encode()) + 1 for argument in ("linter", "check", *batch)) <= 64 * 1024
        for batch in batches
    )


def test_runner_exercises_committed_rule_in_isolated_repositories(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe"
    clean = tmp_path / "clean"
    unsafe.mkdir()
    clean.mkdir()
    (unsafe / "service.py").write_text(
        "async def fetch(items):\n    for item in items:\n        await load(item)\n",
        encoding="utf-8",
    )
    (clean / "service.py").write_text(
        "async def fetch(items):\n    return await asyncio.gather(*(load(item) for item in items))\n",
        encoding="utf-8",
    )

    report = run_isolated_corpora(
        (_source(unsafe, "unsafe"), _source(clean, "clean")),
        (sys.executable, "-m", "sarj_python_lint", "check", "--rule", "no-sequential-await"),
        batch_size=1,
        timeout=timedelta(seconds=30),
    )

    assert len(report.batches) == 2
    assert [batch.corpus for batch in report.batches] == ["unsafe", "clean"]
    assert [batch.returncode for batch in report.batches] == [1, 0]
    assert report.stdout_lines == 1


def test_unexpected_linter_exit_does_not_leak_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    corpus = tmp_path / "private"
    corpus.mkdir()
    (corpus / "secret.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fail(argv: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        _ = argv
        private = SimpleNamespace(retained_bytes=15, lines=1, truncated=False)
        return SimpleNamespace(returncode=2, stdout=private, stderr=private)

    monkeypatch.setattr(corpus_runner, "_run_process", fail)

    with pytest.raises(CorpusLintError, match="exited with 2") as error:
        run_isolated_corpora((_source(corpus, "sample"),), ("linter",))
    assert "customer source" not in str(error.value)
    assert "private path" not in str(error.value)


def test_child_output_is_streamed_with_a_deterministic_byte_limit(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    script = "import os; os.write(1, b'x\\n' * 10000); os.write(2, b'y\\n' * 10000)"

    report = run_isolated_corpora(
        (_source(corpus, "sample"),),
        (sys.executable, "-c", script),
        max_output_bytes=128,
    )

    batch = report.batches[0]
    assert (batch.stdout_bytes, batch.stderr_bytes) == (128, 128)
    assert (batch.stdout_lines, batch.stderr_lines) == (64, 64)
    assert batch.stdout_truncated
    assert batch.stderr_truncated


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group behavior")
@pytest.mark.parametrize(
    ("parent_tail", "marker_name"),
    [("; time.sleep(60)", "descendant-survived"), ("", "orphan-survived")],
    ids=("running-parent", "successful-parent"),
)
def test_timeout_terminates_descendant_processes(tmp_path: Path, parent_tail: str, marker_name: str) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    marker = tmp_path / marker_name
    grandchild = f"import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).write_text('alive')"
    script = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {grandchild!r}]){parent_tail}"

    with pytest.raises(CorpusLintError, match="exceeded"):
        run_isolated_corpora(
            (_source(corpus, "sample"),),
            (sys.executable, "-c", script),
            timeout=timedelta(milliseconds=100),
        )
    _ = threading.Event().wait(0.7)
    assert not marker.exists()
