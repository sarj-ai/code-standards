"""Typed, injectable process execution for release operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- Centralized argv-only process adapter; shell execution is never enabled.
import tempfile
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_BLOCKED_CREDENTIAL_NAMES = frozenset(
    {"DOCKER_CONFIG", "GIT_ASKPASS", "NETRC", "NPM_CONFIG_USERCONFIG", "PIP_CONFIG_FILE", "SSH_ASKPASS"}
)


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
    return run_process_environment(argv, cwd=cwd, capture_output=capture_output, environment=None)


def run_process_environment(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool = False,
    environment: Mapping[str, str] | None,
) -> ProcessResult:
    """Run one argv vector with an explicit environment boundary."""
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is passed directly and shell remains disabled.
        argv,
        cwd=cwd,
        check=False,
        env=None if environment is None else dict(environment),
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=None,
    )
    result = ProcessResult(completed.returncode, completed.stdout or "")
    if result.returncode != 0:
        raise ProcessFailureError(argv, result.returncode)
    return result


def credential_free_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Filter credential-shaped variables; filesystem isolation is added by the runner."""
    source = os.environ if environment is None else environment  # ruff: ignore[banned-api] -- deliberate child-process boundary
    blocked_fragments = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "AUTH")
    blocked_prefixes = ("AWS_", "AZURE_", "GOOGLE_", "TWINE_", "UV_PUBLISH_", "ACTIONS_ID_TOKEN_")
    return {
        name: value
        for name, value in source.items()
        if name.upper() not in _BLOCKED_CREDENTIAL_NAMES
        and not name.upper().startswith(blocked_prefixes)
        and not any(fragment in name.upper() for fragment in blocked_fragments)
    }


def run_build_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> ProcessResult:
    """Run build code with scrubbed variables and an empty temporary home."""
    with tempfile.TemporaryDirectory(prefix="sarj-build-home-") as home:
        environment = credential_free_environment()
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "HOME": home,
                "USERPROFILE": home,
                "APPDATA": home,
                "LOCALAPPDATA": home,
                "NETRC": os.devnull,
                "NPM_CONFIG_USERCONFIG": os.devnull,
                "PIP_CONFIG_FILE": os.devnull,
                "XDG_CONFIG_HOME": home,
            }
        )
        return run_process_environment(
            argv,
            cwd=cwd,
            capture_output=capture_output,
            environment=environment,
        )
