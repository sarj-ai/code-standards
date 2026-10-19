from __future__ import annotations

import os
import sys
import threading
import time
from typing import Final


_ENABLED: Final = os.environ.get("SARJ_STANDARDS_TIMINGS") == "1"  # ruff: ignore[banned-api] -- opt-in profiling.
_ORIGIN: Final = time.monotonic()
_LOCK: Final = threading.Lock()


def report(name: str, seconds: float) -> None:
    if not _ENABLED:
        return
    with _LOCK:
        sys.stderr.write(f"code-standards timing: {name} {seconds:.2f}s @{time.monotonic() - _ORIGIN:.1f}s\n")
        sys.stderr.flush()


class Clock:
    def __init__(self, group: str) -> None:
        self._group = group
        self._last = time.monotonic()

    def mark(self, phase: str) -> None:
        now = time.monotonic()
        report(f"{self._group}/{phase}", now - self._last)
        self._last = now
