from __future__ import annotations

from pathlib import Path
import re
import shlex
from typing import Final, NamedTuple

from sarj_standards.libs.linting import shell_ast
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


TOOL_PYTHON: Final = "3.15.0"
PYTHON_DOWNLOADS: Final = "https://raw.githubusercontent.com/astral-sh/uv/f69fb50c8b28997af9c6b0e5c700a34470d86005/crates/uv-python-managed/download-metadata.json"
PACKAGE: Final = "code-standards"
COMMAND: Final = "code-standards"
BOOTSTRAP_PACKAGE: Final = "sarj-standards-bootstrap"
RETIRED_REPOSITORY_LAUNCHER: Final = Path(".sarj/standards")
RETIRED_LAUNCHER_PROTOCOL: Final = 1
_VERSION: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_SHELL_WHITESPACE: Final = r"(?:\s|\\\r?\n)+"
_LEGACY_REPOSITORY_INVOCATION: Final = re.compile(
    rf"\buvx{_SHELL_WHITESPACE}(?:(?!--from\b)[^\s;&|\\]+{_SHELL_WHITESPACE})*"
    rf"--from{_SHELL_WHITESPACE}['\"]?sarj-standards(?:-bootstrap)?==[^\s;&|\\'\"]+['\"]?"
    rf"{_SHELL_WHITESPACE}(?:sarj|code)-standards"
    rf"(?:{_SHELL_WHITESPACE}--root(?:{_SHELL_WHITESPACE}|=)(?:\.|['\"]\.['\"]))?"
)
_REPOSITORY_LAUNCHER_INVOCATION: Final = re.compile(
    rf"\buv{_SHELL_WHITESPACE}run{_SHELL_WHITESPACE}--no-config"
    rf"{_SHELL_WHITESPACE}--no-project{_SHELL_WHITESPACE}--python"
    rf"{_SHELL_WHITESPACE}3\.14{_SHELL_WHITESPACE}python"
    rf"{_SHELL_WHITESPACE}(?:\./)?\.sarj/standards"
)
_BARE_REPOSITORY_LAUNCHER_INVOCATION: Final = re.compile(
    rf"(?<![\w./-])python{_SHELL_WHITESPACE}(?:\./)?\.sarj/standards"
)
_LEGACY_MAKE_RUN: Final = re.compile(
    r"(?m)^(?P<indent>\t?)(?:@)?\$\(STANDARDS_RUN\)[ \t]+sarj-standards"
    r"(?:[ \t]+--root(?:[ \t]+|=)(?:\.|['\"]\.['\"]))?"
)
_LEGACY_MAKE_RUN_ASSIGNMENT: Final = re.compile(
    r"(?m)^[ \t]*STANDARDS_RUN[ \t]*:?=[ \t]*uvx[^\r\n]*"
    r"sarj-standards(?:-bootstrap)?==(?:['\"])?\$\(STANDARDS_VERSION\)(?:['\"])?[^\r\n]*(?:\r?\n)?"
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
    r"(?P=indent)['\"]sarj-standards(?:-bootstrap)?==[^'\"\r\n]+['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"](?:sarj|code)-standards['\"],[ \t]*\r?\n"
    r"(?:(?P=indent)['\"]--root['\"],[ \t]*\r?\n"
    r"(?P=indent)['\"]\.['\"],[ \t]*\r?\n)?"
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
    contents: str
    replacements: int


def argv(*, executable: str = "uvx", version: str | None = None, refresh: bool = False) -> tuple[str, ...]:
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
        "3.14" if version is not None and tuple(int(part) for part in version.split(".")) < (8, 40, 0) else TOOL_PYTHON,
        *refresh_args,
        "--from",
        package,
        COMMAND,
    )


def repository_argv(*arguments: str, executable: str = "uvx") -> tuple[str, ...]:
    return (
        executable,
        "--no-config",
        "--isolated",
        "--python",
        "3.14",  # Dependency-free bootstrap provisions the final core runtime.
        "--from",
        BOOTSTRAP_PACKAGE,
        COMMAND,
        *arguments,
    )


def repository_command(*arguments: str) -> str:
    return shlex.join(repository_argv(*arguments))


def rewrite_legacy_repository_invocations(text: str) -> LegacyInvocationRewrite:
    contents, count = re.subn(
        rf"\bmise{_SHELL_WHITESPACE}exec{_SHELL_WHITESPACE}pipx:sarj-standards-bootstrap"
        rf"{_SHELL_WHITESPACE}--{_SHELL_WHITESPACE}code-standards",
        repository_command(),
        text,
    )
    contents, legacy_count = _LEGACY_REPOSITORY_INVOCATION.subn(repository_command(), contents)
    count += legacy_count
    contents, repository_count = _REPOSITORY_LAUNCHER_INVOCATION.subn(repository_command(), contents)
    count += repository_count
    contents, bare_repository_count = _BARE_REPOSITORY_LAUNCHER_INVOCATION.subn(repository_command(), contents)
    count += bare_repository_count
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
        contents = _LEGACY_MAKE_RUN_ASSIGNMENT.sub(
            lambda match: (
                "\r\n" if match.group(0).endswith("\r\n") else ("\n" if match.group(0).endswith("\n") else "")
            ),
            contents,
        )
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


def rewrite_native_bootstrap_pin(source: bytes, *, version: str) -> bytes | None:
    if _VERSION.fullmatch(version) is None:
        msg = f"invalid exact Standards version: {version!r}"
        raise ValueError(msg)
    try:
        statements = shell_ast.parse_shell(source.decode("utf-8")).get("Stmts", [])
    except UnicodeError, shell_ast.ShellSyntaxError:
        return None
    if not is_object_list(statements):
        return None
    for statement in statements:
        words = _native_bootstrap_words(statement, source)
        if words is None:
            return None
        arguments = tuple(word[0] for word in words)
        # Earlier source/eval/alias/function definitions could replace uv.
        # Only this literal native shell-options prelude precedes the proven call.
        if arguments == ("set", "-euo", "pipefail"):
            continue
        prefix = ("uv", "run", "--no-config", "--no-project", "--python", TOOL_PYTHON, "--with")
        if arguments[:7] != prefix or arguments[8:] != (
            "python",
            "-m",
            "sarj_standards.libs.adoption.native_bootstrap",
        ):
            return None
        package, start, end = words[7]
        old_version = package.removeprefix(f"{PACKAGE}==")
        if package == old_version or _VERSION.fullmatch(old_version) is None or old_version == version:
            return None
        literal = source[start:end]
        if literal.count(old_version.encode()) != 1:
            return None
        return source[:start] + literal.replace(old_version.encode(), version.encode(), 1) + source[end:]
    return None


def _native_bootstrap_words(statement: object, source: bytes) -> tuple[tuple[str, int, int], ...] | None:
    if not is_object_mapping(statement) or any(
        statement.get(key) for key in ("Negated", "Background", "Coprocess", "Redirs")
    ):
        return None
    command = statement.get("Cmd")
    if not is_object_mapping(command) or command.get("Type") != "CallExpr":
        return None
    assignments, arguments = command.get("Assigns", []), command.get("Args", [])
    if not is_object_list(assignments) or not is_object_list(arguments):
        return None
    for item in assignments:
        if not is_object_mapping(item) or _literal_shell_word(item.get("Value"), source) is None:
            return None
        name = item.get("Name")
        if not is_object_mapping(name) or name.get("Value") == "PATH":
            return None
    words = tuple(_literal_shell_word(word, source) for word in arguments)
    if any(word is None for word in words):
        return None
    return tuple(word for word in words if word is not None)


def _literal_shell_word(word: object, source: bytes) -> tuple[str, int, int] | None:
    if not is_object_mapping(word):
        return None
    parts, position, end_position = word.get("Parts"), word.get("Pos"), word.get("End")
    if not is_object_list(parts) or not is_object_mapping(position) or not is_object_mapping(end_position):
        return None
    for part in parts:
        if not is_object_mapping(part) or part.get("Dollar"):
            return None
        match part.get("Type"):
            case "Lit" | "SglQuoted":
                continue
            case "DblQuoted":
                quoted = part.get("Parts", [])
                if not is_object_list(quoted) or any(
                    not is_object_mapping(item) or item.get("Type") != "Lit" for item in quoted
                ):
                    return None
            case _:
                return None
    start, end = position.get("Offset", 0), end_position.get("Offset", 0)
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(source):
        return None
    values = shlex.split(source[start:end].decode("utf-8"))
    return (values[0], start, end) if len(values) == 1 else None


def retired_repository_script() -> str:
    return f"""# Managed by code-standards launcher protocol {RETIRED_LAUNCHER_PROTOCOL}; do not edit.
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
PYTHON_DOWNLOADS = "https://raw.githubusercontent.com/astral-sh/uv/f69fb50c8b28997af9c6b0e5c700a34470d86005/crates/uv-python-managed/download-metadata.json"
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\Z")
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".sarj-standards.toml"


def fail(message: str) -> int:
    print(f"code-standards launcher: {{message}}", file=sys.stderr)
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
    python = TOOL_PYTHON if tuple(int(part) for part in bundle.split(".")) >= (8, 40, 0) else "3.14"
    if python == TOOL_PYTHON:
        environment.setdefault("UV_PYTHON_DOWNLOADS_JSON_URL", PYTHON_DOWNLOADS)
    command = (
        uvx,
        "--no-config",
        "--isolated",
        "--python",
        python,
        "--from",
        f"code-standards=={{bundle}}",
        "code-standards",
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
    return shlex.join(argv())


def install() -> str:
    return shlex.join(("uv", "tool", "install", "--python", TOOL_PYTHON, PACKAGE))
