"""One deterministic Standards launcher for every consumer ecosystem."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
from typing import Final, NamedTuple


TOOL_PYTHON: Final = "3.14"
PACKAGE: Final = "sarj-standards"
COMMAND: Final = "sarj-standards"
BOOTSTRAP_SPEC: Final = "sarj-standards-bootstrap==1.0.1"
RETIRED_REPOSITORY_LAUNCHER: Final = Path(".sarj/standards")
RETIRED_LAUNCHER_PROTOCOL: Final = 1
_VERSION: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_SHELL_WHITESPACE: Final = r"(?:\s|\\\r?\n)+"
_LEGACY_REPOSITORY_INVOCATION: Final = re.compile(
    rf"\buvx{_SHELL_WHITESPACE}(?:(?!--from\b)[^\s;&|\\]+{_SHELL_WHITESPACE})*"
    rf"--from{_SHELL_WHITESPACE}['\"]?sarj-standards==[^\s;&|\\'\"]+['\"]?"
    rf"{_SHELL_WHITESPACE}sarj-standards"
    rf"(?:{_SHELL_WHITESPACE}--root(?:{_SHELL_WHITESPACE}|=)(?:\.|['\"]\.['\"]))?"
)
_REPOSITORY_LAUNCHER_INVOCATION: Final = re.compile(
    rf"\buv{_SHELL_WHITESPACE}run{_SHELL_WHITESPACE}--no-config"
    rf"{_SHELL_WHITESPACE}--no-project{_SHELL_WHITESPACE}--python"
    rf"{_SHELL_WHITESPACE}3\.14{_SHELL_WHITESPACE}python"
    rf"{_SHELL_WHITESPACE}(?:\./)?\.sarj/standards"
)
_LEGACY_MAKE_RUN: Final = re.compile(
    r"(?m)^(?P<indent>\t?)(?:@)?\$\(STANDARDS_RUN\)[ \t]+sarj-standards"
    r"(?:[ \t]+--root(?:[ \t]+|=)(?:\.|['\"]\.['\"]))?"
)
_LEGACY_MAKE_RUN_ASSIGNMENT: Final = re.compile(
    r"(?m)^[ \t]*STANDARDS_RUN[ \t]*:?=[ \t]*uvx[^\r\n]*"
    r"sarj-standards==(?:['\"])?\$\(STANDARDS_VERSION\)(?:['\"])?[^\r\n]*(?:\r?\n)?"
)
_LEGACY_MAKE_VERSION_ASSIGNMENT: Final = re.compile(r"(?m)^[ \t]*STANDARDS_VERSION[ \t]*:?=[ \t]*[^\r\n]+(?:\r?\n)?")
_LEGACY_MAKE_VERSION_PRINT: Final = re.compile(
    r"(?m)^\t@?printf[ \t]+['\"]%s\\n['\"][ \t]+['\"]?\$\(STANDARDS_VERSION\)['\"]?[ \t]*$"
)
_LEGACY_PYTHON_ARGV_INVOCATION: Final = re.compile(
    r"(?m)^(?P<indent>[ \t]*)['\"]uvx['\"],[ \t]*\r?\n"
    r"(?:(?P=indent)['\"]--no-config['\"],[ \t]*\r?\n)?"
    r"(?P=indent)['\"]--isolated['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--python['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]3\.14['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--from['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]sarj-standards==[^'\"\r\n]+['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]sarj-standards['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--root['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]\.['\"],[ \t]*\r?\n"
)
_REPOSITORY_PYTHON_ARGV_INVOCATION: Final = re.compile(
    r"(?m)^(?P<indent>[ \t]*)['\"]uv['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]run['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--no-config['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--no-project['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]--python['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]3\.14['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]python['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]\.sarj/standards['\"],[ \t]*\r?\n"
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


def repository_argv(*arguments: str, executable: str = "uvx") -> tuple[str, ...]:
    """Build the immutable bootstrap command committed to consumer wiring."""
    return (
        executable,
        "--no-config",
        "--isolated",
        "--python",
        TOOL_PYTHON,
        "--from",
        BOOTSTRAP_SPEC,
        COMMAND,
        *arguments,
    )


def repository_command(*arguments: str) -> str:
    """Render the stable consumer invocation shared by hooks, CI, and scripts."""
    return shlex.join(repository_argv(*arguments))


def rewrite_legacy_repository_invocations(text: str) -> LegacyInvocationRewrite:
    """Replace former direct-bundle and repository-file launchers with bootstrap."""
    contents, count = _LEGACY_REPOSITORY_INVOCATION.subn(repository_command(), text)
    contents, repository_count = _REPOSITORY_LAUNCHER_INVOCATION.subn(repository_command(), contents)
    count += repository_count
    update_target = re.compile(
        rf"{re.escape(repository_command())}{_SHELL_WHITESPACE}update"
        rf"{_SHELL_WHITESPACE}--to(?:{_SHELL_WHITESPACE}|=)[^\s;&|\\'\"]+"
    )
    contents, update_target_count = update_target.subn(f"{repository_command()} update", contents)
    count += update_target_count
    contents, python_argv_count = _LEGACY_PYTHON_ARGV_INVOCATION.subn(_python_repository_argv, contents)
    count += python_argv_count
    contents, repository_python_count = _REPOSITORY_PYTHON_ARGV_INVOCATION.subn(_python_repository_argv, contents)
    count += repository_python_count
    before_make = contents
    make_invocations = tuple(_LEGACY_MAKE_RUN.finditer(contents))
    if (
        make_invocations
        and _LEGACY_MAKE_RUN_ASSIGNMENT.search(contents) is not None
        and _LEGACY_MAKE_VERSION_ASSIGNMENT.search(contents) is not None
    ):
        contents = _LEGACY_MAKE_RUN.sub(
            lambda match: f"{match.group('indent')}{repository_command()}",
            contents,
        )
        contents = _LEGACY_MAKE_VERSION_PRINT.sub(f"\t@{repository_command('--version')}", contents)
        contents = _LEGACY_MAKE_RUN_ASSIGNMENT.sub("", contents)
        contents = _LEGACY_MAKE_VERSION_ASSIGNMENT.sub(
            f"STANDARDS_VERSION := $(shell {repository_command('--version')})\n",
            contents,
        )
        if "$(STANDARDS_RUN)" not in contents:
            count += len(make_invocations)
        else:
            return LegacyInvocationRewrite(before_make, count)
    return LegacyInvocationRewrite(contents, count)


def _python_repository_argv(match: re.Match[str]) -> str:
    indent = match.group("indent")
    return "".join(f'{indent}"{argument}",\n' for argument in repository_argv())


def retired_repository_script() -> str:
    """Render protocol 1 exactly so only an unmodified retired launcher is removed."""
    return f"""# Managed by sarj-standards launcher protocol {RETIRED_LAUNCHER_PROTOCOL}; do not edit.
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib


PROTOCOL = {RETIRED_LAUNCHER_PROTOCOL}
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
