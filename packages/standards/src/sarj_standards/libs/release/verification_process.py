from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
import os
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- owns argv-only verification process groups.
from threading import Event, Thread
import time
from typing import TYPE_CHECKING, Self


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from types import TracebackType


@dataclass
class BaseWatch:
    expected_base: str
    read_base: Callable[[], str | None]
    command_timeout: float
    poll_interval: float = 10
    moved_to: str | None = field(default=None, init=False)
    stopped: Event = field(default_factory=Event, init=False)
    cancelled: Event = field(default_factory=Event, init=False)
    thread: Thread | None = field(default=None, init=False)

    def __enter__(self) -> Self:
        self.thread = Thread(target=self._watch, name="standards-base-watch", daemon=True)
        self.thread.start()
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if self.cancelled.is_set():
            return _result(command, 125, "", "consumer base changed; verification cancelled", check=check)
        deadline = time.monotonic() + self.command_timeout
        with subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is supplied directly and shell remains disabled.
            list(command),
            cwd=cwd,
            env=env,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        ) as process:
            while True:
                if self.cancelled.is_set():
                    return _interrupt(
                        process, command, 125, "consumer base changed; verification cancelled", check=check
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    message = f"{command[0]} exceeded the {self.command_timeout:g}s command timeout"
                    return _interrupt(process, command, 124, message, check=check)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                except subprocess.TimeoutExpired:
                    continue
                return _result(command, process.wait(), stdout, stderr, check=check)

    def _watch(self) -> None:
        while not self.stopped.wait(self.poll_interval):
            current = self.read_base()
            # Unavailable evidence cannot establish movement. The controller
            # still requires its independent exact-base check before pushing.
            if current is not None and current != self.expected_base:
                self.moved_to = current
                self.cancelled.set()
                return


def _interrupt(
    process: subprocess.Popen[str],
    command: Sequence[str],
    returncode: int,
    message: str,
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    _signal_group(process, signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired as exc:
            # A descendant that starts its own session may retain a pipe.
            # Close our descriptors rather than waiting indefinitely for it.
            stdout, stderr = _tail(exc.stdout), _tail(exc.stderr)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            process.kill()
            process.wait(timeout=2)
    return _result(command, returncode, _tail(stdout), f"{_tail(stderr)}\n{message}".strip(), check=check)


def _signal_group(process: subprocess.Popen[str], number: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, number)


def _tail(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value[-4000:].decode("utf-8", errors="replace")
    return value[-4000:] if value else ""


def _result(
    command: Sequence[str], returncode: int, stdout: str, stderr: str, *, check: bool
) -> subprocess.CompletedProcess[str]:
    result = subprocess.CompletedProcess(list(command), returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
