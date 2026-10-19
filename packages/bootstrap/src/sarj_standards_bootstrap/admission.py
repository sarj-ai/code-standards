from __future__ import annotations

from contextlib import contextmanager
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


LEASE_ENV: Final = "SARJ_LOCAL_CHECK_LEASE"
JSON_PARSER: Callable[[str], dict[str, object] | list[object] | str | int | float | bool | None] = json.loads


@contextmanager
def check_slot(environment: dict[str, str]) -> Generator[None]:
    if os.name != "posix" or environment.get("CI", "").lower() in {"true", "1"}:
        yield
        return
    import fcntl  # ruff: ignore[import-outside-top-level] -- unavailable on Windows, whose launcher stays unchanged.

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
    started = time.monotonic()
    next_report = started
    while True:
        for slot in range(slots):
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
                environment[LEASE_ENV] = marker
                environment["SARJ_LOCAL_CHECK_STATE_DIR"] = str(directory)
                # POSIX exec replaces this launcher; its replacement owns the
                # lock until the exact pinned checker exits, including uvx's wait.
                flags = fcntl.fcntl(handle, fcntl.F_GETFD)
                fcntl.fcntl(handle, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
                yield
                return
        now = time.monotonic()
        if now >= next_report:
            sys.stderr.write(
                f"Local checks: waiting for one of {slots} shared slot(s) ({now - started:.0f}s elapsed).\n"
            )
            sys.stderr.flush()
            next_report = now + 15
        if now - started >= timeout:
            message = f"local checks: no shared slot became free within {timeout:g}s"
            raise TimeoutError(message)
        time.sleep(min(0.1, timeout - (now - started)))


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
