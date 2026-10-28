from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import secrets
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- inspect only the caller's parent chain.
import sys
import time
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import TextIO


MAX_SLOTS: Final = 64
LEASE_ENV: Final = "SARJ_LOCAL_CHECK_LEASE"
JSON_PARSER: Callable[[str], dict[str, object] | list[object] | str | int | float | bool | None] = json.loads


@dataclass(slots=True)
class Wait:
    started: float
    timeout: float
    next_report: float = 0


@contextmanager
def check_slot(environment: dict[str, str]) -> Generator[None]:
    if os.name != "posix" or environment.get("CI", "").lower() in {"true", "1"}:
        yield
        return
    slots = int(environment.get("SARJ_LOCAL_CHECK_JOBS", "1"))
    timeout = float(environment.get("SARJ_LOCAL_CHECK_WAIT_SECONDS", "3600"))
    if slots < 1 or not math.isfinite(timeout) or timeout < 0:
        message = "local check slots must be positive; wait timeout must be finite and nonnegative"
        raise ValueError(message)
    cache = Path(environment.get("XDG_CACHE_HOME", ""))
    if not cache.is_absolute():
        cache = Path.home() / ".cache"
    directory = Path(environment.get("SARJ_LOCAL_CHECK_STATE_DIR", str(cache / "sarj" / "local-checks"))).resolve()
    if _inherited_lease(directory, environment.get(LEASE_ENV)):
        yield
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    wait = Wait(started=time.monotonic(), timeout=timeout)
    with _registered_waiter(directory, wait) as ticket_path:
        yield from _wait_for_slot(directory, slots, environment, wait, ticket_path)


def _wait_for_slot(
    directory: Path,
    slots: int,
    environment: dict[str, str],
    wait: Wait,
    ticket_path: Path,
) -> Generator[None]:
    import fcntl  # ruff: ignore[import-outside-top-level] -- POSIX admission path only.

    while True:
        capacity = _capacity(directory, slots)
        position = _queue_position(directory, ticket_path, wait)
        for slot in range(capacity) if position == 1 else ():
            if wait.timeout > 0 and time.monotonic() - wait.started >= wait.timeout:
                _pause(wait, "shared slot")
            with (directory / f"slot-{slot}.lock").open("a+", encoding="utf-8") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                marker = json.dumps(
                    {"path": str(Path(handle.name)), "pid": os.getpid(), "token": secrets.token_hex(16)}
                )
                handle.seek(0)
                handle.truncate()
                handle.write(marker)
                handle.flush()
                ticket_path.unlink(missing_ok=True)
                environment["SARJ_LOCAL_CHECK_JOBS"] = str(capacity)
                environment[LEASE_ENV] = marker
                environment["SARJ_LOCAL_CHECK_STATE_DIR"] = str(directory)
                # POSIX exec replaces this launcher; its replacement owns the
                # lock until the exact pinned checker exits, including uvx's wait.
                flags = fcntl.fcntl(handle, fcntl.F_GETFD)
                fcntl.fcntl(handle, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
                yield
                return
        _pause(wait, f"one of {capacity} shared slot(s); queue position {position}")


def _pause(wait: Wait, description: str) -> None:
    now = time.monotonic()
    if now >= wait.next_report:
        sys.stderr.write(f"Local checks: waiting for {description} ({now - wait.started:.2f}s elapsed).\n")
        sys.stderr.flush()
        wait.next_report = now + 15
    remaining = wait.timeout - (now - wait.started)
    if remaining <= 0:
        message = f"local checks: no shared slot became free within {wait.timeout:g}s (waiting for {description})"
        raise TimeoutError(message)
    time.sleep(min(0.25, remaining))


def _lock_queue(registration: TextIO, wait: Wait) -> None:
    import fcntl  # ruff: ignore[import-outside-top-level] -- POSIX admission path only.

    while True:
        if wait.timeout > 0 and time.monotonic() - wait.started >= wait.timeout:
            _pause(wait, "admission metadata lock")
        try:
            fcntl.flock(registration, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _pause(wait, "admission metadata lock")
        else:
            return


@contextmanager
def _registered_waiter(directory: Path, wait: Wait) -> Generator[Path]:
    import fcntl  # ruff: ignore[import-outside-top-level] -- POSIX admission path only.

    path = directory / f"wait-{time.time_ns():020d}-{secrets.token_hex(8)}.lock"
    with ExitStack() as stack:
        with (directory / "queue.lock").open("a+", encoding="utf-8") as registration:
            _lock_queue(registration, wait)
            handle = stack.enter_context(path.open("x", encoding="utf-8"))
            stack.callback(path.unlink, missing_ok=True)
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield path


def _capacity(directory: Path, slots: int) -> int:
    policy = directory / "capacity.json"
    try:
        value = JSON_PARSER(policy.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return slots
    capacity = value.get("slots") if isinstance(value, dict) else None
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= MAX_SLOTS:
        message = f"capacity.json must contain an integer slots value from 1 to {MAX_SLOTS}."
        raise ValueError(message)
    return capacity


def _queue_position(directory: Path, ticket_path: Path, wait: Wait) -> int:
    with (directory / "queue.lock").open("a+", encoding="utf-8") as registration:
        _lock_queue(registration, wait)
        return _live_queue_position(directory, ticket_path)


def _live_queue_position(directory: Path, ticket_path: Path) -> int:
    position = 1
    for path in sorted(directory.glob("wait-*.lock")):
        if path.name >= ticket_path.name:
            break
        if _ticket_is_live(path):
            position += 1
    return position


def _ticket_is_live(path: Path) -> bool:
    import fcntl  # ruff: ignore[import-outside-top-level] -- POSIX admission path only.

    try:
        handle = path.open("r+", encoding="utf-8")
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        path.unlink(missing_ok=True)
    return False


def _inherited_lease(directory: Path, marker: str | None) -> bool:
    if not marker:
        return False
    try:
        return _held_ancestor(directory, marker)
    except OSError, ValueError, subprocess.TimeoutExpired:
        return False


def _held_ancestor(directory: Path, marker: str) -> bool:
    import fcntl  # ruff: ignore[import-outside-top-level] -- called only by the POSIX reservation.

    lease = JSON_PARSER(marker)
    if not isinstance(lease, dict):
        return False
    raw_path, pid = lease.get("path"), lease.get("pid")
    if not isinstance(raw_path, str) or not isinstance(pid, int) or pid <= 1:
        return False
    path = Path(raw_path)
    if path.parent != directory or not path.name.startswith("slot-") or path.suffix != ".lock":
        return False
    with path.open("r+", encoding="utf-8") as handle:
        if handle.read(4096) != marker or not _is_ancestor(pid):
            return False
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def _is_ancestor(pid: int) -> bool:
    current = os.getppid()
    seen: set[int] = set()
    while current > 1 and current not in seen:
        if current == pid:
            return True
        seen.add(current)
        parent = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and numeric PID.
            ["/bin/ps", "-o", "ppid=", "-p", str(current)], capture_output=True, text=True, check=False, timeout=5
        )
        if parent.returncode or not parent.stdout.strip().isdigit():
            return False
        current = int(parent.stdout.strip())
    return current == pid
