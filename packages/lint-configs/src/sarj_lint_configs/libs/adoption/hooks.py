"""Hook-manager detection and validation shared by init, update, and doctor."""

from __future__ import annotations

from pathlib import Path, PurePath
import re
import shlex
from typing import TYPE_CHECKING, Final, NamedTuple

import yaml

from . import manifest


if TYPE_CHECKING:
    from collections.abc import Mapping

    from .manifest import HookManager


LEFTHOOK_NAMES: Final = ("lefthook.yml", "lefthook.yaml")
_COMMANDS_BLOCK: Final = re.compile(r"(?m)^(?P<indent> +)commands:(?P<tail>[^\n]*)$")


class LefthookWrite(NamedTuple):
    """One comment-preserving Lefthook repair ready for a scaffold plan."""

    path: Path
    contents: str


def lefthook_config(root: Path) -> Path | None:
    """Return the active Lefthook configuration, if present."""
    return next((root / name for name in LEFTHOOK_NAMES if (root / name).is_file()), None)


def detect_manager(root: Path) -> HookManager:
    """Preserve an existing Lefthook setup; otherwise manage pre-commit."""
    return "lefthook" if lefthook_config(root) is not None else "pre-commit"


def lefthook_runs_staged_check(root: Path) -> bool:
    """Require the user-managed hook to invoke the canonical staged command."""
    path = lefthook_config(root)
    if path is None:
        return False
    try:
        parsed: object = yaml.safe_load(  # pyright: ignore[reportAny] -- narrow the untyped YAML parser boundary below.
            path.read_text(encoding="utf-8")
        )
    except OSError, UnicodeError, yaml.YAMLError:
        return False
    document = manifest.as_table(parsed)
    pre_commit = manifest.as_table(document.get("pre-commit"))
    commands = manifest.as_table(pre_commit.get("commands"))
    return any(_runs_staged_check(manifest.as_table(command).get("run")) for command in commands.values())


def wire_lefthook_staged_check(root: Path) -> LefthookWrite:
    """Add the canonical command to a conventional Lefthook mapping without reformatting it."""
    path = lefthook_config(root)
    if path is None:
        msg = "--hooks lefthook requires lefthook.yml or lefthook.yaml"
        raise ValueError(msg)
    text, commands = _load_lefthook_commands(path)
    commands_match, section_end = _locate_commands_block(path, text)
    name = "sarj-standards" if "sarj-standards" not in commands else "sarj-standards-staged"
    return LefthookWrite(path, _insert_staged_command(path, text, commands_match, section_end, name))


def _load_lefthook_commands(path: Path) -> tuple[str, Mapping[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
        parsed: object = yaml.safe_load(text)  # pyright: ignore[reportAny] -- narrowed immediately below.
        document = manifest.as_table(parsed)
        pre_commit = manifest.as_table(document.get("pre-commit"))
        commands = manifest.as_table(pre_commit.get("commands"))
    except (OSError, UnicodeError, TypeError, yaml.YAMLError) as exc:
        msg = f"cannot safely wire {path.name}: expected a valid pre-commit.commands mapping"
        raise ValueError(msg) from exc
    if "commands" not in pre_commit:
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)
    return text, commands


def _locate_commands_block(path: Path, text: str) -> tuple[re.Match[str], int]:
    pre_commit_match = re.search(r"(?m)^pre-commit:\s*(?:#.*)?$", text)
    if pre_commit_match is None:
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)
    section_end_match = re.search(r"(?m)^[^\s#][^:]*:\s*", text[pre_commit_match.end() :])
    section_end = len(text) if section_end_match is None else pre_commit_match.end() + section_end_match.start()
    commands_match = _COMMANDS_BLOCK.search(text, pre_commit_match.end(), section_end)
    if commands_match is None:
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)
    return commands_match, section_end


def _insert_staged_command(
    path: Path,
    text: str,
    commands_match: re.Match[str],
    section_end: int,
    name: str,
) -> str:
    command_indent = len(commands_match.group("indent"))
    child_indent = " " * (command_indent + 2)
    rendered = f"{child_indent}{name}:\n{child_indent}  run: sarj-standards check --staged\n"
    absolute_start = commands_match.start()
    absolute_end = commands_match.end()
    tail = commands_match.group("tail")
    if re.fullmatch(r"\s*\{\}\s*(?:#.*)?", tail):
        comment = tail[tail.find("#") :] if "#" in tail else ""
        replacement = f"{commands_match.group('indent')}commands:"
        if comment:
            replacement = f"{replacement}  {comment}"
        return "".join((text[:absolute_start], replacement, "\n", rendered, text[absolute_end + 1 :]))
    if tail.strip():
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)

    insertion = absolute_end + (1 if text[absolute_end:].startswith("\n") else 0)
    for line in text[insertion:section_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(line) - len(line.lstrip(" ")) <= command_indent:
            break
        insertion += len(line)
    separator = "" if insertion > absolute_end else "\n"
    return "".join((text[:insertion], separator, rendered, text[insertion:]))


def _runs_staged_check(value: object) -> bool:
    if not isinstance(value, str) or re.search(r"(?:&&|\|\||[;|`]|\$\()", value):
        return False
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    executable = next(
        (index for index, token in enumerate(tokens) if PurePath(token).name == "sarj-standards"),
        None,
    )
    if executable is None:
        return False
    prefix = tokens[:executable]
    if prefix and PurePath(prefix[0]).name not in {"uv", "uvx"}:
        return False
    if any(PurePath(token).name in {"echo", "printf"} for token in prefix):
        return False
    return tokens[executable + 1 : executable + 3] == ["check", "--staged"]
