from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypedDict, TypeGuard, runtime_checkable

from typer.core import TyperArgument, TyperCommand, TyperGroup, TyperOption
from typer.main import get_command

from sarj_standards._meta import CONFIGS_DIR, __version__


if TYPE_CHECKING:
    from collections.abc import Iterable

    import typer


SCHEMA_VERSION: Final = 1
CLI_REFERENCE_PATH: Final = CONFIGS_DIR / "cli-reference.v1.json"
_REPOSITORY_REFERENCE_PATH: Final = Path("packages/standards/src/sarj_standards/configs/cli-reference.v1.json")


@dataclass(frozen=True, slots=True)
class ReferenceSyncResult:
    status: int
    message: str


class ReferenceArgument(TypedDict):
    kind: Literal["positional", "option"]
    names: list[str]
    metavar: str | None
    summary: str
    choices: list[str]
    required: bool
    repeatable: bool


class ReferenceCommand(TypedDict):
    name: str
    path: list[str]
    usage: str
    summary: str
    options: list[ReferenceArgument]
    commands: list[ReferenceCommand]


class ReferenceLauncher(TypedDict):
    install: str
    runLatest: str


class CliReference(TypedDict):
    schemaVersion: int
    version: str
    program: str
    summary: str
    epilog: str | None
    globalOptions: list[ReferenceArgument]
    commands: list[ReferenceCommand]
    launcher: ReferenceLauncher


def validate(value: object) -> CliReference:
    if not _is_object(value) or frozenset(value) != frozenset(
        {
            "schemaVersion",
            "version",
            "program",
            "summary",
            "epilog",
            "globalOptions",
            "commands",
            "launcher",
        }
    ):
        msg = "CLI reference has an invalid top-level shape"
        raise ValueError(msg)
    if value["schemaVersion"] != SCHEMA_VERSION:
        msg = f"unsupported CLI reference schemaVersion: {value['schemaVersion']!r}; expected {SCHEMA_VERSION}"
        raise ValueError(msg)
    if not isinstance(value["version"], str) or not value["version"]:
        msg = "CLI reference version must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(value["program"], str) or not value["program"]:
        msg = "CLI reference program must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(value["summary"], str):
        msg = "CLI reference summary must be a string"
        raise TypeError(msg)
    epilog = value["epilog"]
    if epilog is not None and not isinstance(epilog, str):
        msg = "CLI reference epilog must be null or a string"
        raise TypeError(msg)
    global_options = value["globalOptions"]
    commands = value["commands"]
    launcher = value["launcher"]
    if not _is_argument_list(global_options) or not _is_command_list(commands) or not _is_launcher(launcher):
        msg = "CLI reference options and commands must have the documented shape"
        raise TypeError(msg)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "version": value["version"],
        "program": value["program"],
        "summary": value["summary"],
        "epilog": epilog,
        "globalOptions": global_options,
        "commands": commands,
        "launcher": launcher,
    }


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_argument_list(value: object) -> TypeGuard[list[ReferenceArgument]]:
    return _is_object_list(value) and all(_is_argument(item) for item in value)


def _is_argument(value: object) -> TypeGuard[ReferenceArgument]:
    if not _is_object(value) or frozenset(value) != frozenset(ReferenceArgument.__required_keys__):
        return False
    kind = value["kind"]
    metavar = value["metavar"]
    return (
        kind in {"positional", "option"}
        and _is_string_list(value["names"])
        and (metavar is None or isinstance(metavar, str))
        and isinstance(value["summary"], str)
        and _is_string_list(value["choices"])
        and isinstance(value["required"], bool)
        and isinstance(value["repeatable"], bool)
    )


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return _is_object_list(value) and all(isinstance(item, str) for item in value)


def _is_command_list(value: object) -> TypeGuard[list[ReferenceCommand]]:
    return _is_object_list(value) and all(_is_command(item) for item in value)


def _is_command(value: object) -> TypeGuard[ReferenceCommand]:
    if not _is_object(value) or frozenset(value) != frozenset(ReferenceCommand.__required_keys__):
        return False
    return (
        isinstance(value["name"], str)
        and _is_string_list(value["path"])
        and isinstance(value["usage"], str)
        and isinstance(value["summary"], str)
        and _is_argument_list(value["options"])
        and _is_command_list(value["commands"])
    )


def _is_launcher(value: object) -> TypeGuard[ReferenceLauncher]:
    return (
        _is_object(value)
        and frozenset(value) == frozenset(ReferenceLauncher.__required_keys__)
        and isinstance(value["install"], str)
        and bool(value["install"])
        and isinstance(value["runLatest"], str)
        and bool(value["runLatest"])
    )


def load(path: Path = CLI_REFERENCE_PATH) -> CliReference:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot load shipped CLI reference {path}: {exc}"
        raise ValueError(msg) from exc
    return validate(payload)


def build(app: typer.Typer) -> CliReference:
    from sarj_standards.libs.adoption import launcher  # ruff: ignore[import-outside-top-level]

    parser = get_command(app)
    if not isinstance(parser, (TyperCommand, TyperGroup)):
        msg = "CLI reference requires a native Typer command tree"
        raise TypeError(msg)
    program = parser.name or "code-standards"
    root = _command(parser, name=program, path=(), program=program)
    return validate(
        {
            "schemaVersion": SCHEMA_VERSION,
            "version": __version__,
            "program": program,
            "summary": parser.help or "",
            "epilog": parser.epilog,
            "globalOptions": root["options"],
            "commands": root["commands"],
            "launcher": {"install": launcher.install(), "runLatest": launcher.latest()},
        }
    )


def _command(
    parser: TyperCommand | TyperGroup,
    *,
    name: str,
    path: tuple[str, ...],
    program: str,
) -> ReferenceCommand:
    arguments: list[ReferenceArgument] = []
    commands: list[ReferenceCommand] = []
    for action in parser.params:
        if isinstance(action, TyperOption) and action.hidden:
            continue
        if not isinstance(action, (TyperArgument, TyperOption)):
            msg = f"Unsupported CLI parameter: {action.name}"
            raise TypeError(msg)
        arguments.append(_argument(action))
    if parser.add_help_option:
        arguments.insert(
            0,
            {
                "kind": "option",
                "names": ["-h", "--help"],
                "metavar": None,
                "summary": "Show this message and exit.",
                "choices": [],
                "required": False,
                "repeatable": False,
            },
        )
    if isinstance(parser, TyperGroup):
        for command_name, child in parser.commands.items():
            if not isinstance(child, (TyperCommand, TyperGroup)):
                msg = f"Unsupported CLI command: {command_name}"
                raise TypeError(msg)
            commands.append(_command(child, name=command_name, path=(*path, command_name), program=program))
    return {
        "name": name,
        "path": list(path),
        "usage": _usage(" ".join((program, *path)), arguments, commands),
        "summary": parser.help or "",
        "options": arguments,
        "commands": commands,
    }


@runtime_checkable
class _ChoiceType(Protocol):
    @property
    def choices(self) -> Iterable[object]: ...


def _argument(action: TyperArgument | TyperOption) -> ReferenceArgument:
    choices = action.type.choices if isinstance(action.type, _ChoiceType) else ()
    positional = isinstance(action, TyperArgument)
    flag = isinstance(action, TyperOption) and action.is_flag
    return {
        "kind": "positional" if positional else "option",
        "names": [action.name or ""] if positional else [*action.opts, *action.secondary_opts],
        "metavar": None if flag else action.metavar or (action.name or "").upper(),
        "summary": action.help or "",
        "choices": [str(choice) for choice in choices],
        "required": action.required,
        "repeatable": action.nargs == -1 or action.multiple,
    }


def _usage(
    program: str,
    arguments: list[ReferenceArgument],
    commands: list[ReferenceCommand],
) -> str:
    parts = [program]
    for argument in arguments:
        if not argument["names"]:
            continue
        token = argument["names"][0]
        metavar = argument["metavar"]
        if metavar is not None:
            token = f"{token} {metavar}" if argument["kind"] == "option" else metavar
        if argument["repeatable"]:
            token = f"{token} ..."
        if not argument["required"]:
            token = f"[{token}]"
        parts.append(token)
    if commands:
        parts.append("{" + ",".join(command["name"] for command in commands) + "}")
    return " ".join(parts)


def render(parser: typer.Typer) -> str:
    return json.dumps(build(parser), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def sync(root: Path, parser: typer.Typer, *, check: bool) -> ReferenceSyncResult:
    from sarj_standards.libs.adoption import transaction  # ruff: ignore[import-outside-top-level]

    destination = root.resolve() / _REPOSITORY_REFERENCE_PATH
    expected = render(parser)
    try:
        current = destination.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if current == expected:
        return ReferenceSyncResult(0, "ok: cli-reference.v1.json matches the parser graph")
    if check:
        return ReferenceSyncResult(
            1,
            "drift: cli-reference.v1.json differs from the parser graph; "
            "run `code-standards maintain cli-reference sync`",
        )
    transaction.atomic_write_text(root.resolve(), destination, expected)
    return ReferenceSyncResult(0, "updated: cli-reference.v1.json")
