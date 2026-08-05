"""Typed, injectable process execution for release operations."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- Centralized argv-only process adapter; shell execution is never enabled.
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """The process data release code needs, independent of subprocess internals."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class ProcessRunner(Protocol):
    """Run one argv vector without a shell."""

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool = False,
    ) -> ProcessResult: ...


class ProcessFailureError(RuntimeError):
    """A child process failed during a release operation."""

    argv: tuple[str, ...]
    returncode: int

    def __init__(self, argv: tuple[str, ...], returncode: int) -> None:
        self.argv = argv
        self.returncode = returncode
        super().__init__(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed with exit code {returncode}")


def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> ProcessResult:
    """Run an argv vector directly, inheriting the environment and never using a shell."""
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is passed directly and shell remains disabled.
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=None,
    )
    result = ProcessResult(completed.returncode, completed.stdout or "")
    if result.returncode != 0:
        raise ProcessFailureError(argv, result.returncode)
    return result
