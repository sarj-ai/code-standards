"""One deterministic Standards launcher for every consumer ecosystem."""

from __future__ import annotations

import shlex
from typing import Final


TOOL_PYTHON: Final = "3.14"
PACKAGE: Final = "sarj-lint-configs"
COMMAND: Final = "sarj-standards"


def argv(*, executable: str = "uvx", version: str | None = None, refresh: bool = False) -> tuple[str, ...]:
    """Build the isolated launcher without consulting a consumer environment."""
    package = PACKAGE if version is None else f"{PACKAGE}=={version}"
    refresh_args = ("--refresh",) if refresh else ()
    return (
        executable,
        "--isolated",
        "--python",
        TOOL_PYTHON,
        *refresh_args,
        "--from",
        package,
        COMMAND,
    )


def pinned(version: str) -> str:
    """Render the exact launcher embedded in hooks and CI."""
    return shlex.join(argv(version=version))
