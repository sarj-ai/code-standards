"""One deterministic Standards launcher for every consumer ecosystem."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
from typing import Final, NamedTuple


TOOL_PYTHON: Final = "3.14"
PACKAGE: Final = "sarj-standards"
COMMAND: Final = "sarj-standards"
REPOSITORY_LAUNCHER: Final = Path(".sarj/standards")
LAUNCHER_PROTOCOL: Final = 1
_VERSION: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_LEGACY_REPOSITORY_INVOCATION: Final = re.compile(
    r"\buvx\s+(?:(?!--from\b)[^\s;&|]+\s+)*"
    r"--from\s+sarj-standards==[^\s;&|]+\s+sarj-standards"
    r"(?:\s+--root(?:\s+|=)(?:\.|['\"]\.['\"]))?"
)


class LegacyInvocationRewrite(NamedTuple):
    """A legacy-launcher rewrite and the number of replacements made."""

    contents: str
    replacements: int


def argv(*, executable: str = "uvx", version: str | None = None, refresh: bool = False) -> tuple[str, ...]:
    """Build the isolated launcher without consulting a consumer environment."""
    if version is not None and _VERSION.fullmatch(version) is None:
        msg = f"invalid exact Standards version: {version!r}"
        raise ValueError(msg)
    package = PACKAGE if version is None else f"{PACKAGE}=={version}"
    refresh_args = ("--refresh",) if refresh else ()
    return (
        executable,
        "--no-config",
        "--isolated",
        "--python",
        TOOL_PYTHON,
        *refresh_args,
        "--from",
        package,
        COMMAND,
    )


def repository_argv(*arguments: str, executable: str = "uv") -> tuple[str, ...]:
    """Build the versionless command committed to consumer wiring."""
    return (
        executable,
        "run",
        "--no-config",
        "--no-project",
        "--python",
        TOOL_PYTHON,
        "python",
        REPOSITORY_LAUNCHER.as_posix(),
        *arguments,
    )


def repository_command(*arguments: str) -> str:
    """Render the stable consumer invocation shared by hooks, CI, and scripts."""
    return shlex.join(repository_argv(*arguments))


def rewrite_legacy_repository_invocations(text: str) -> LegacyInvocationRewrite:
    """Replace exact legacy uvx launchers with the manifest-driven repository launcher."""
    contents, count = _LEGACY_REPOSITORY_INVOCATION.subn(repository_command(), text)
    return LegacyInvocationRewrite(contents, count)


def repository_script() -> str:
    """Render the dependency-free launcher whose only authority is the manifest."""
    return f"""# Managed by sarj-standards launcher protocol {LAUNCHER_PROTOCOL}; do not edit.
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib


PROTOCOL = {LAUNCHER_PROTOCOL}
TOOL_PYTHON = {TOOL_PYTHON!r}
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\Z")
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".sarj-standards.toml"


def fail(message: str) -> int:
    print(f"sarj-standards launcher: {{message}}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        with MANIFEST.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return fail(f"cannot read {{MANIFEST}}: {{exc}}")
    schema = document.get("schema")
    bundle = document.get("bundle")
    if schema != 3:
        return fail(f"unsupported manifest schema {{schema!r}}")
    if not isinstance(bundle, str) or VERSION.fullmatch(bundle) is None:
        return fail("manifest bundle must be one exact canonical release")
    uvx = shutil.which("uvx")
    if uvx is None:
        return fail("uvx is required; install uv and retry")
    environment = dict(os.environ)
    for name in (
        "PIP_EXTRA_INDEX_URL",
        "PIP_INDEX_URL",
        "UV_CONFIG_FILE",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX_URL",
        "UV_PROJECT",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    command = (
        uvx,
        "--no-config",
        "--isolated",
        "--python",
        TOOL_PYTHON,
        "--from",
        f"sarj-standards=={{bundle}}",
        "sarj-standards",
        "--root",
        str(ROOT),
        *sys.argv[1:],
    )
    try:
        return subprocess.run(command, check=False, env=environment, shell=False).returncode  # noqa: S603
    except OSError as exc:
        return fail(f"could not execute standards {{bundle}}: {{exc}}")


if __name__ == "__main__":
    raise SystemExit(main())
"""


def latest() -> str:
    """Render the installation-free launcher for the latest release."""
    return shlex.join(argv())


def install() -> str:
    """Render the optional persistent tool installation command."""
    return shlex.join(("uv", "tool", "install", "--python", TOOL_PYTHON, PACKAGE))
