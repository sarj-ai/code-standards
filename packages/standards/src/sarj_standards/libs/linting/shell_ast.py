from __future__ import annotations

from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catches bounded runner timeout, never executes here.
from typing import TYPE_CHECKING

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


_MAX_CACHE_CHARACTERS = 1_048_576
_MAX_CACHE_ENTRIES = 128


class ShellParseError(RuntimeError):
    """Missing analyzer, resource limit or malformed analyzer output."""


class ShellSyntaxError(ValueError):
    """The selected executable shell field does not parse."""


def _checked_executable() -> Path:
    from .devops_tools import NativeToolError, checked_tool  # ruff: ignore[import-outside-top-level] -- native registry imports the textlint adapter.

    try:
        tool = checked_tool("shfmt", root=Path.cwd())
        if tool.executable is None:
            msg = "checked shfmt did not resolve an absolute executable"
            raise ShellParseError(msg)
    except (OSError, subprocess.SubprocessError, NativeToolError) as error:
        msg = f"shfmt failed: {error}"
        raise ShellParseError(msg) from error
    else:
        return tool.executable


def make_shell_parser() -> Callable[[str], Mapping[str, object]]:
    executable: Path | None = None
    cache: dict[str, str] = {}
    retained_characters = 0

    def parse(source: str) -> Mapping[str, object]:
        nonlocal executable, retained_characters
        if executable is None:
            executable = _checked_executable()
        if source in cache:
            return _shell_tree(cache[source])
        payload = _shell_json(source, executable=executable, dialect="bash")
        tree = _shell_tree(payload)
        size = len(source) + len(payload)
        if size <= _MAX_CACHE_CHARACTERS:
            if len(cache) >= _MAX_CACHE_ENTRIES or retained_characters + size > _MAX_CACHE_CHARACTERS:
                cache.clear()
                retained_characters = 0
            cache[source] = payload
            retained_characters += size
        return tree

    return parse


def parse_shell(source: str, *, dialect: str = "bash") -> Mapping[str, object]:
    return _parse_shell(source, executable=_checked_executable(), dialect=dialect)


def _parse_shell(source: str, *, executable: Path, dialect: str) -> Mapping[str, object]:
    return _shell_tree(_shell_json(source, executable=executable, dialect=dialect))


def _shell_json(source: str, *, executable: Path, dialect: str) -> str:
    from .external import run_process_input  # ruff: ignore[import-outside-top-level] -- runner imports textlint; avoid a module cycle.

    if dialect not in {"bash", "posix", "mksh", "bats", "zsh"}:
        msg = f"unsupported shfmt dialect: {dialect}"
        raise ShellParseError(msg)
    try:
        result = run_process_input(
            [str(executable), "--to-json", f"--language-dialect={dialect}"], cwd=Path.cwd(), source=source
        )
    except (OSError, subprocess.SubprocessError) as error:
        msg = f"shfmt failed: {error}"
        raise ShellParseError(msg) from error
    if result.returncode == 1 and result.stderr.strip() and not result.stdout.strip():
        raise ShellSyntaxError(result.stderr.strip())
    if result.returncode != 0 or result.stderr.strip():
        msg = "shfmt did not complete the typed-JSON analysis protocol"
        raise ShellParseError(msg)
    return result.stdout


def _shell_tree(payload: str) -> Mapping[str, object]:
    try:
        tree = parse_json(payload)
    except ValueError as error:
        msg = "shfmt returned invalid JSON"
        raise ShellParseError(msg) from error
    if not is_object_mapping(tree) or tree.get("Type") != "File":
        msg = "shfmt returned no File AST"
        raise ShellParseError(msg)
    return {key: value for key, value in tree.items() if isinstance(key, str)}
