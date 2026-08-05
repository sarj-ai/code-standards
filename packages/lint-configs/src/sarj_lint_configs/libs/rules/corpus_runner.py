"""Run corpus linters in bounded, repository-isolated child processes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, isolated local lint processes only.
import time
from typing import TYPE_CHECKING, Final

from sarj_lint_configs.libs.corpus import CorpusSource, selected_files, verify


if TYPE_CHECKING:
    from pathlib import Path

_SAFE_ENVIRONMENT: Final = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "VIRTUAL_ENV"}
)
_MAX_BATCH_SIZE = 1_000


@dataclass(frozen=True, slots=True)
class CorpusBatchResult:
    """Aggregate-only result; source paths and diagnostic text are not retained."""

    corpus: str
    ordinal: int
    files: int
    returncode: int
    stdout_lines: int
    stderr_lines: int
    elapsed: timedelta


@dataclass(frozen=True, slots=True)
class IsolatedCorpusReport:
    """Evidence that every bounded batch completed in its own process."""

    batches: tuple[CorpusBatchResult, ...]

    @property
    def files(self) -> int:
        return sum(batch.files for batch in self.batches)

    @property
    def stdout_lines(self) -> int:
        return sum(batch.stdout_lines for batch in self.batches)

    @property
    def elapsed(self) -> timedelta:
        return sum((batch.elapsed for batch in self.batches), start=timedelta())


class CorpusLintError(RuntimeError):
    """A corpus batch timed out or the linter failed to execute."""


def run_isolated_corpora(
    sources: tuple[CorpusSource, ...],
    command: tuple[str, ...],
    *,
    batch_size: int = 250,
    timeout: timedelta = timedelta(minutes=2),
    accepted_returncodes: frozenset[int] = frozenset({0, 1}),
) -> IsolatedCorpusReport:
    """Lint verified corpora without sharing a long-lived linter or retained findings."""
    if not sources:
        msg = "isolated corpus evaluation requires at least one corpus"
        raise ValueError(msg)
    if not command or any(not argument for argument in command):
        msg = "isolated corpus evaluation requires a non-empty command"
        raise ValueError(msg)
    if not 1 <= batch_size <= _MAX_BATCH_SIZE:
        msg = f"batch size must be between 1 and {_MAX_BATCH_SIZE}"
        raise ValueError(msg)
    if timeout <= timedelta():
        msg = "corpus batch timeout must be positive"
        raise ValueError(msg)
    if not accepted_returncodes:
        msg = "accepted return codes must not be empty"
        raise ValueError(msg)

    results: list[CorpusBatchResult] = []
    for source in sources:
        verify(source)
        files = selected_files(source)
        for ordinal, offset in enumerate(range(0, len(files), batch_size), start=1):
            batch = files[offset : offset + batch_size]
            results.append(
                _run_batch(
                    source,
                    command,
                    batch,
                    ordinal=ordinal,
                    timeout=timeout,
                    accepted_returncodes=accepted_returncodes,
                )
            )
    return IsolatedCorpusReport(tuple(results))


def _run_batch(
    source: CorpusSource,
    command: tuple[str, ...],
    files: tuple[Path, ...],
    *,
    ordinal: int,
    timeout: timedelta,
    accepted_returncodes: frozenset[int],
) -> CorpusBatchResult:
    relative_files = tuple(path.relative_to(source.root).as_posix() for path in files if path.is_file())
    if not relative_files:
        msg = f"corpus {source.report_name} batch {ordinal} contains no existing files"
        raise CorpusLintError(msg)
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- intentionally discard hook-local state.
        if name in _SAFE_ENVIRONMENT
    }
    started = time.monotonic()
    try:
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is never interpreted by a shell.
            (*command, *relative_files),
            cwd=source.root,
            check=False,
            capture_output=True,
            env=environment,
            shell=False,
            text=True,
            timeout=timeout.total_seconds(),
        )
    except subprocess.TimeoutExpired as error:
        msg = f"corpus {source.report_name} batch {ordinal} exceeded {timeout.total_seconds():g}s"
        raise CorpusLintError(msg) from error
    elapsed = timedelta(seconds=time.monotonic() - started)
    if completed.returncode not in accepted_returncodes:
        msg = f"corpus {source.report_name} batch {ordinal} exited with {completed.returncode}"
        raise CorpusLintError(msg)
    return CorpusBatchResult(
        source.report_name,
        ordinal,
        len(relative_files),
        completed.returncode,
        len(completed.stdout.splitlines()),
        len(completed.stderr.splitlines()),
        elapsed,
    )
