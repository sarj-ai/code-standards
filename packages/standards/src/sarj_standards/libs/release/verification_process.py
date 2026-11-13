from __future__ import annotations

from codecs import getincrementaldecoder
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from enum import StrEnum
from io import IncrementalNewlineDecoder
import math
import os
from selectors import EVENT_READ, DefaultSelector
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- owns argv-only verification process groups.
from threading import Event, Thread
import time
from typing import TYPE_CHECKING, Final, Self, assert_never


if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence
    from pathlib import Path
    from types import TracebackType
    from typing import IO


# Provisional per-command bound for combined stdout and stderr raw bytes.
_DEFAULT_MAX_CAPTURE_BYTES: Final = 64 * 1024 * 1024
_READ_CHUNK_BYTES: Final = 64 * 1024
_POLL_SECONDS: Final = 0.25
_OUTPUT_TAIL_SIZE: Final = 4000
_CLEANUP_SECONDS: Final = 2


def _capture_limit(value: int) -> int:
    if type(value) is not int:
        message = "max_capture_bytes must be an integer"
        raise TypeError(message)
    if value <= 0:
        message = "max_capture_bytes must be positive"
        raise ValueError(message)
    return value


def _utf8_decoder() -> IncrementalNewlineDecoder:
    return IncrementalNewlineDecoder(getincrementaldecoder("utf-8")(errors="replace"), translate=True)


@dataclass(slots=True)
class _CapturedStream:
    data: bytearray = field(default_factory=bytearray)
    raw_tail: bytes = b""
    text_tail: str = ""
    decoder: IncrementalNewlineDecoder = field(default_factory=_utf8_decoder)

    def feed(self, chunk: bytes) -> None:
        self.raw_tail = (self.raw_tail + chunk)[-_OUTPUT_TAIL_SIZE:]
        self.text_tail = (self.text_tail + self.decoder.decode(chunk))[-_OUTPUT_TAIL_SIZE:]

    def finish(self) -> None:
        self.text_tail = (self.text_tail + self.decoder.decode(b"", final=True))[-_OUTPUT_TAIL_SIZE:]

    def output(self) -> str:
        return self.data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True, slots=True)
class _RetainingBytes:
    remaining: int


class _TailRetention(StrEnum):
    CANCELLED = "cancelled"
    OVERFLOW = "overflow"


type _Retention = _RetainingBytes | _TailRetention


class _InactiveWatch(StrEnum):
    NEW = "new"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class _RunningWatch:
    thread: Thread


type _WatchLifecycle = _InactiveWatch | _RunningWatch


class _UnmovedBase(StrEnum):
    UNOBSERVED = "unobserved"
    UNCHANGED = "unchanged"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class _MovedBase:
    revision: str


type _BaseObservation = _UnmovedBase | _MovedBase


class _Capture:
    def __init__(self, process: subprocess.Popen[bytes], limit: int) -> None:
        self.stdout = _CapturedStream()
        self.stderr = _CapturedStream()
        self._retention: _Retention = _RetainingBytes(limit)
        self._selector = DefaultSelector()
        self._pending: dict[int, tuple[IO[bytes], _CapturedStream]] = {}
        try:
            for pipe, stream in ((process.stdout, self.stdout), (process.stderr, self.stderr)):
                if pipe is not None:
                    descriptor = pipe.fileno()
                    os.set_blocking(descriptor, False)
                    self._selector.register(descriptor, EVENT_READ)
                    self._pending[descriptor] = (pipe, stream)
        except BaseException as error:
            try:
                self._selector.close()
            except OSError as cleanup_error:
                error.add_note(f"closing the partial capture selector failed: {cleanup_error}")
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close_pipes()
        self._selector.close()

    @property
    def complete(self) -> bool:
        return not self._pending

    @property
    def exceeded(self) -> bool:
        return self._retention is _TailRetention.OVERFLOW

    def keep_tails_only(self) -> None:
        if isinstance(self._retention, _RetainingBytes):
            self._retention = _TailRetention.CANCELLED
        self.stdout.data.clear()
        self.stderr.data.clear()

    def read_ready(self, timeout: float) -> None:
        # At most one bounded read per ready pipe returns control to the caller's
        # cancellation/deadline checks, even if a child writes continuously.
        for key, _events in self._selector.select(timeout):
            pipe, stream = self._pending[key.fd]
            try:
                chunk = os.read(key.fd, _READ_CHUNK_BYTES)
            except BlockingIOError:
                continue
            if not chunk:
                stream.finish()
                self._selector.unregister(key.fd)
                self._pending.pop(key.fd)
                pipe.close()
                continue
            stream.feed(chunk)
            match self._retention:
                case _RetainingBytes(remaining):
                    if len(chunk) > remaining:
                        self._retention = _TailRetention.OVERFLOW
                        self.keep_tails_only()
                    else:
                        self._retention = _RetainingBytes(remaining - len(chunk))
                        stream.data.extend(chunk)
                case _TailRetention.CANCELLED | _TailRetention.OVERFLOW:
                    pass
                case _:
                    assert_never(self._retention)

    def drain(self, process: subprocess.Popen[bytes], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.complete and process.poll() is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.read_ready(min(_POLL_SECONDS, remaining))

    def close_pipes(self) -> None:
        for descriptor, (pipe, _stream) in tuple(self._pending.items()):
            self._selector.unregister(descriptor)
            pipe.close()
        self._pending.clear()


@dataclass
class BaseWatch:
    expected_base: str
    read_base: Callable[[], str | None]
    command_timeout: float
    poll_interval: float = 10
    phase: str = "verification"
    max_capture_bytes: int = field(default=_DEFAULT_MAX_CAPTURE_BYTES, kw_only=True)
    cancelled: Event = field(default_factory=Event, init=False)
    _stop: Event = field(default_factory=Event, init=False)
    _lifecycle: _WatchLifecycle = field(default=_InactiveWatch.NEW, init=False)
    _base: _BaseObservation = field(default=_UnmovedBase.UNOBSERVED, init=False)

    @property
    def moved_to(self) -> str | None:
        match self._base:
            case _MovedBase(revision):
                return revision
            case _UnmovedBase():
                return None
            case _:
                assert_never(self._base)

    def __post_init__(self) -> None:
        _capture_limit(self.max_capture_bytes)
        if (
            isinstance(self.command_timeout, bool)
            or not math.isfinite(self.command_timeout)
            or self.command_timeout < 0
        ):
            message = "command_timeout must be finite and non-negative"
            raise ValueError(message)
        if isinstance(self.poll_interval, bool) or not math.isfinite(self.poll_interval) or self.poll_interval <= 0:
            message = "poll_interval must be finite and positive"
            raise ValueError(message)

    def __enter__(self) -> Self:
        if self._lifecycle is not _InactiveWatch.NEW:
            message = "base watcher can only be entered once"
            raise ValueError(message)
        thread = Thread(target=self._watch, name="standards-base-watch", daemon=True)
        self._lifecycle = _RunningWatch(thread)
        try:
            thread.start()
        except BaseException:
            self._stop.set()
            self._lifecycle = _InactiveWatch.CLOSED
            raise
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        match self._lifecycle:
            case _RunningWatch(thread):
                thread.join()
            case _InactiveWatch.NEW | _InactiveWatch.CLOSED:
                pass
            case _:
                assert_never(self._lifecycle)
        self._lifecycle = _InactiveWatch.CLOSED

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if self._lifecycle is _InactiveWatch.CLOSED:
            message = "closed base watcher cannot start another command"
            raise ValueError(message)
        if self.cancelled.is_set():
            return _result(command, 125, "", f"consumer base changed; {self.phase} cancelled", check=check)
        limit = _capture_limit(self.max_capture_bytes)
        deadline = time.monotonic() + self.command_timeout
        process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is supplied directly and shell remains disabled.
            list(command),
            cwd=cwd,
            env=env,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        try:
            capture = _Capture(process, limit)
        except BaseException as error:
            _abort_capture_setup(process, error)
            raise
        with _owned_capture(process, capture):
            while True:
                if self.cancelled.is_set():
                    return _interrupt(
                        process,
                        capture,
                        command,
                        125,
                        f"consumer base changed; {self.phase} cancelled",
                        check=check,
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    message = f"{command[0]} exceeded the {self.command_timeout:g}s command timeout"
                    return _interrupt(process, capture, command, 124, message, check=check)
                if capture.exceeded:
                    message = f"{command[0]} exceeded the {limit:,}-byte combined output limit"
                    return _interrupt(process, capture, command, 123, message, check=check)
                if capture.complete and (returncode := process.poll()) is not None:
                    return _result(command, returncode, capture.stdout.output(), capture.stderr.output(), check=check)
                capture.read_ready(min(_POLL_SECONDS, remaining))

    def _watch(self) -> None:
        while not self._stop.is_set():
            current = self.read_base()
            # Unavailable evidence cannot establish movement. The controller
            # still requires its independent exact-base check before pushing.
            if current is not None and current != self.expected_base:
                self._base = _MovedBase(current)
                self.cancelled.set()
                return
            self._base = _UnmovedBase.UNAVAILABLE if current is None else _UnmovedBase.UNCHANGED
            if self._stop.wait(self.poll_interval):
                return


@contextmanager
def _owned_capture(process: subprocess.Popen[bytes], capture: _Capture) -> Generator[None]:
    try:
        with capture:
            yield
    except BaseException as error:
        # Never enter Popen.__exit__'s unbounded wait after capture failure.
        # A reaped leader no longer owns its numeric process-group identity.
        if process.returncode is None:
            _abort_capture_setup(process, error)
        raise


def _abort_capture_setup(process: subprocess.Popen[bytes], error: BaseException) -> None:
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError as cleanup_error:
                error.add_note(f"closing a capture pipe failed: {cleanup_error}")
    # Without a usable collector, abort the group before reaping its leader.
    # Ordinary observed interruptions retain their TERM/KILL grace periods below.
    for number in (signal.SIGTERM, signal.SIGKILL):
        try:
            _signal_group(process, number)
        except OSError as cleanup_error:
            error.add_note(f"signalling the capture setup process group failed: {cleanup_error}")
    try:
        process.wait(timeout=_CLEANUP_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as cleanup_error:
        error.add_note(f"reaping the capture setup process failed: {cleanup_error}")


def _interrupt(
    process: subprocess.Popen[bytes],
    capture: _Capture,
    command: Sequence[str],
    returncode: int,
    message: str,
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    capture.keep_tails_only()
    _signal_group(process, signal.SIGTERM)
    if not capture.drain(process, _CLEANUP_SECONDS):
        _signal_group(process, signal.SIGKILL)
        if not capture.drain(process, _CLEANUP_SECONDS):
            # A detached descendant may retain a pipe; close descriptors after the timeout.
            capture.close_pipes()
            process.kill()
            process.wait(timeout=_CLEANUP_SECONDS)
            stdout, stderr = _tail(capture.stdout.raw_tail), _tail(capture.stderr.raw_tail)
            return _result(command, returncode, stdout, f"{stderr}\n{message}".strip(), check=check)
    stdout, stderr = capture.stdout.text_tail, capture.stderr.text_tail
    return _result(command, returncode, _tail(stdout), f"{_tail(stderr)}\n{message}".strip(), check=check)


def _signal_group(process: subprocess.Popen[bytes], number: int) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, number)


def _tail(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value[-_OUTPUT_TAIL_SIZE:].decode("utf-8", errors="replace")
    return value[-_OUTPUT_TAIL_SIZE:] if value else ""


def _result(
    command: Sequence[str], returncode: int, stdout: str, stderr: str, *, check: bool
) -> subprocess.CompletedProcess[str]:
    result = subprocess.CompletedProcess(list(command), returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
