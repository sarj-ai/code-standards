"""Run corpus linters in bounded, repository-isolated child processes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, isolated local lint processes only.
import threading
import time
from typing import TYPE_CHECKING, Final

from sarj_lint_configs.libs.corpus import CorpusSource, selected_files, verify


if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

_SAFE_ENVIRONMENT: Final = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "VIRTUAL_ENV"}
)
_MAX_BATCH_SIZE = 1_000
_DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
_MAX_OUTPUT_BYTES = 8 * 1_048_576
_MAX_ARGV_BYTES = 64 * 1024
_DEFAULT_MAX_FILES_PER_CORPUS = 50_000
_DEFAULT_MAX_BATCHES = 1_000
_READ_SIZE = 65_536


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
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False


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


@dataclass(frozen=True, slots=True)
class _StreamSummary:
    retained_bytes: int
    lines: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    returncode: int
    stdout: _StreamSummary
    stderr: _StreamSummary


def run_isolated_corpora(
    sources: tuple[CorpusSource, ...],
    command: tuple[str, ...],
    *,
    batch_size: int = 250,
    timeout: timedelta = timedelta(minutes=2),
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    total_timeout: timedelta = timedelta(minutes=15),
    max_files_per_corpus: int = _DEFAULT_MAX_FILES_PER_CORPUS,
    max_batches: int = _DEFAULT_MAX_BATCHES,
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
    if not 1 <= max_output_bytes <= _MAX_OUTPUT_BYTES:
        msg = f"corpus batch output limit must be between 1 and {_MAX_OUTPUT_BYTES} bytes"
        raise ValueError(msg)
    if total_timeout <= timedelta():
        msg = "corpus total timeout must be positive"
        raise ValueError(msg)
    if max_files_per_corpus <= 0 or max_batches <= 0:
        msg = "corpus file and batch limits must be positive"
        raise ValueError(msg)
    if not accepted_returncodes:
        msg = "accepted return codes must not be empty"
        raise ValueError(msg)

    results: list[CorpusBatchResult] = []
    deadline = time.monotonic() + total_timeout.total_seconds()
    for source in sources:
        verify(source)
        files = selected_files(source)
        if len(files) > max_files_per_corpus:
            msg = f"corpus {source.report_name} exceeds the {max_files_per_corpus}-file evaluation limit"
            raise CorpusLintError(msg)
        batches = argv_batches(files, command, batch_size=batch_size)
        if len(results) + len(batches) > max_batches:
            msg = f"corpus evaluation exceeds the {max_batches}-batch limit"
            raise CorpusLintError(msg)
        for ordinal, batch in enumerate(batches, start=1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = f"corpus evaluation exceeded {total_timeout.total_seconds():g}s total"
                raise CorpusLintError(msg)
            results.append(
                _run_batch(
                    source,
                    command,
                    batch,
                    ordinal=ordinal,
                    timeout=min(timeout, timedelta(seconds=remaining)),
                    max_output_bytes=max_output_bytes,
                    accepted_returncodes=accepted_returncodes,
                )
            )
    return IsolatedCorpusReport(tuple(results))


def argv_batches(
    files: tuple[Path, ...],
    command: tuple[str, ...],
    *,
    batch_size: int,
) -> tuple[tuple[Path, ...], ...]:
    """Bound batches by both file count and conservative encoded argv bytes."""
    base_bytes = sum(len(os.fsencode(argument)) + 1 for argument in command)
    if base_bytes >= _MAX_ARGV_BYTES:
        msg = "corpus linter command exceeds the argv byte budget"
        raise CorpusLintError(msg)
    batches: list[tuple[Path, ...]] = []
    current: list[Path] = []
    current_bytes = base_bytes
    for path in files:
        argument_bytes = len(os.fsencode(str(path))) + 1
        if current and (len(current) >= batch_size or current_bytes + argument_bytes > _MAX_ARGV_BYTES):
            batches.append(tuple(current))
            current = []
            current_bytes = base_bytes
        if current_bytes + argument_bytes > _MAX_ARGV_BYTES:
            msg = "one corpus path exceeds the argv byte budget"
            raise CorpusLintError(msg)
        current.append(path)
        current_bytes += argument_bytes
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _run_batch(
    source: CorpusSource,
    command: tuple[str, ...],
    files: tuple[Path, ...],
    *,
    ordinal: int,
    timeout: timedelta,
    max_output_bytes: int,
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
        completed = _run_process(
            (*command, *relative_files),
            cwd=source.root,
            env=environment,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
    except subprocess.TimeoutExpired as error:
        msg = f"corpus {source.report_name} batch {ordinal} exceeded {timeout.total_seconds():g}s"
        raise CorpusLintError(msg) from error
    except OSError as error:
        msg = f"corpus {source.report_name} batch {ordinal} failed to execute"
        raise CorpusLintError(msg) from error
    elapsed = timedelta(seconds=time.monotonic() - started)
    if completed.returncode not in accepted_returncodes:
        msg = f"corpus {source.report_name} batch {ordinal} exited with {completed.returncode}"
        raise CorpusLintError(msg)
    return CorpusBatchResult(
        corpus=source.report_name,
        ordinal=ordinal,
        files=len(relative_files),
        returncode=completed.returncode,
        stdout_lines=completed.stdout.lines,
        stderr_lines=completed.stderr.lines,
        elapsed=elapsed,
        stdout_bytes=completed.stdout.retained_bytes,
        stderr_bytes=completed.stderr.retained_bytes,
        stdout_truncated=completed.stdout.truncated,
        stderr_truncated=completed.stderr.truncated,
    )


def _run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: timedelta,
    max_output_bytes: int,
) -> _ProcessResult:
    """Drain both output streams while retaining only a deterministic prefix."""
    timeout_seconds = timeout.total_seconds()
    deadline = time.monotonic() + timeout_seconds
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is never interpreted by a shell.
        argv,
        cwd=cwd,
        env=env,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:  # pragma: no cover - PIPE guarantees both streams.
        process.kill()
        msg = "corpus process did not expose output pipes"
        raise OSError(msg)

    summaries: list[_StreamSummary | None] = [None, None]
    threads = (
        threading.Thread(target=_drain_stream, args=(stdout, max_output_bytes, summaries, 0), daemon=True),
        threading.Thread(target=_drain_stream, args=(stderr, max_output_bytes, summaries, 1), daemon=True),
    )
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        _ = process.wait()
        for thread in threads:
            thread.join()
        raise

    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        _terminate_process_group(process)
        for thread in threads:
            thread.join()
        raise subprocess.TimeoutExpired(argv, timeout_seconds)

    stdout_summary, stderr_summary = summaries
    if stdout_summary is None or stderr_summary is None:  # pragma: no cover - threads always assign on EOF.
        msg = "corpus process output could not be summarized"
        raise OSError(msg)
    return _ProcessResult(returncode, stdout_summary, stderr_summary)


def _drain_stream(
    stream: BinaryIO,
    max_output_bytes: int,
    summaries: list[_StreamSummary | None],
    index: int,
) -> None:
    retained = bytearray()
    truncated = False
    try:
        while chunk := stream.read(_READ_SIZE):
            remaining = max_output_bytes - len(retained)
            if remaining > 0:
                retained.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
    finally:
        stream.close()
    summaries[index] = _StreamSummary(len(retained), len(retained.splitlines()), truncated)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate a timed-out child and its descendants when process groups are available."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:  # pragma: no cover - CI exercises POSIX process-group cleanup.
        process.kill()
