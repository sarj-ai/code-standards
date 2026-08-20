from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- Windows cannot replace the current process.
import sys
import tomllib
from typing import TYPE_CHECKING, Final, NoReturn


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


MANIFEST_NAME: Final = ".sarj-standards.toml"
MANIFEST_SCHEMA: Final = 3
TOOL_PYTHON: Final = "3.14"
_VERSION: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


class BootstrapError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedArguments:
    root: Path | None
    forwarded: tuple[str, ...]


def explicit_root(arguments: Sequence[str], *, cwd: Path) -> ParsedArguments:
    root: Path | None = None
    forwarded: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            forwarded.extend(arguments[index:])
            break
        if argument == "--root":
            if root is not None:
                message = "--root may be specified only once"
                raise BootstrapError(message)
            index += 1
            if index >= len(arguments):
                message = "--root requires a directory"
                raise BootstrapError(message)
            root = (cwd / arguments[index]).resolve()
        elif argument.startswith("--root="):
            if root is not None:
                message = "--root may be specified only once"
                raise BootstrapError(message)
            value = argument.partition("=")[2]
            if not value:
                message = "--root requires a directory"
                raise BootstrapError(message)
            root = (cwd / value).resolve()
        else:
            forwarded.append(argument)
        index += 1
    return ParsedArguments(root, tuple(forwarded))


def find_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
    message = f"no {MANIFEST_NAME} found at or above {current}"
    raise BootstrapError(message)


def table(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        message = f"{MANIFEST_NAME} must contain a TOML table"
        raise BootstrapError(message)
    entries: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
        if isinstance(key, str):
            entries[key] = item  # ruff: ignore[manual-dict-comprehension] — pyright needs explicit narrowing.
    return entries


def bundle(root: Path) -> str:
    manifest = root / MANIFEST_NAME
    try:
        with manifest.open("rb") as stream:
            document: object = tomllib.load(stream)
    except FileNotFoundError as exc:
        message = f"{manifest} does not exist"
        raise BootstrapError(message) from exc
    except OSError as exc:
        message = f"cannot read {manifest}: {exc}"
        raise BootstrapError(message) from exc
    except tomllib.TOMLDecodeError as exc:
        message = f"{manifest} is not valid TOML: {exc}"
        raise BootstrapError(message) from exc
    data = table(document)
    schema = data.get("schema")
    if schema != MANIFEST_SCHEMA:
        message = f"{manifest} schema must equal {MANIFEST_SCHEMA}, got {schema!r}"
        raise BootstrapError(message)
    selected_bundle = data.get("bundle")
    if not isinstance(selected_bundle, str) or _VERSION.fullmatch(selected_bundle) is None:
        message = f"{manifest} bundle must be one exact canonical X.Y.Z release"
        raise BootstrapError(message)
    return selected_bundle


def command(uvx: str, root: Path, selected_bundle: str, arguments: Sequence[str]) -> tuple[str, ...]:
    return (
        uvx,
        "--no-config",
        "--isolated",
        "--python",
        TOOL_PYTHON,
        "--from",
        f"code-standards=={selected_bundle}",
        "code-standards",
        "--root",
        str(root),
        *arguments,
    )


def execute(exact_command: Sequence[str], environment: Mapping[str, str], *, platform: str = os.name) -> NoReturn:
    arguments = tuple(exact_command)
    if platform == "nt":
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv; no consumer shell.
            arguments,
            env=environment,
            check=False,
            shell=False,
        )
        raise SystemExit(completed.returncode)
    os.execvpe(  # ruff: ignore[start-process-with-no-shell] -- POSIX replacement preserves signals and exit status.
        arguments[0],
        arguments,
        dict(environment),
    )


def run(arguments: Sequence[str], *, cwd: Path) -> NoReturn:
    parsed = explicit_root(arguments, cwd=cwd)
    explicit = parsed.root
    if explicit is not None:
        if not explicit.is_dir():
            message = f"--root {explicit} is not a directory"
            raise BootstrapError(message)
        root = explicit
    else:
        root = find_root(cwd)
    selected_bundle = bundle(root)
    uvx = shutil.which("uvx")
    if uvx is None:
        message = "uvx is required; install uv and retry"
        raise BootstrapError(message)
    exact_command = command(uvx, root, selected_bundle, parsed.forwarded)
    try:
        execute(
            exact_command,
            os.environ.copy(),  # ruff: ignore[banned-api] -- inherit registry, certificate, cache, proxy, and offline policy.
        )
    except OSError as exc:
        message = f"could not execute Standards {selected_bundle}: {exc}"
        raise BootstrapError(message) from exc


def main(argv: Sequence[str] | None = None) -> int:
    try:
        run(sys.argv[1:] if argv is None else argv, cwd=Path.cwd())
    except BootstrapError as exc:
        sys.stderr.write(f"code-standards bootstrap: {exc}\n")
        return 2
