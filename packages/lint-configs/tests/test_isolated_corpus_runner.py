"""Corpus rule evaluation cannot accumulate multiple repositories in one process."""

from __future__ import annotations

from datetime import timedelta
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.corpus import CorpusKind, CorpusSource, snapshot
from sarj_lint_configs.libs.rules import CorpusLintError, run_isolated_corpora


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

    def run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = kwargs["cwd"]
        assert isinstance(cwd, type(tmp_path))
        calls.append((argv, cwd))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

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

    def fail(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 2, "customer source", "private path")

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(CorpusLintError, match="exited with 2") as error:
        run_isolated_corpora((_source(corpus, "sample"),), ("linter",))
    assert "customer source" not in str(error.value)
    assert "private path" not in str(error.value)
