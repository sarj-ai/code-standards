from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import chain
from operator import itemgetter
import re
import string
import sys
import tomllib
from typing import TYPE_CHECKING, override

from sarj_python_lint.interpreter_argv import UnprovableCommandError, classify_interpreter, unwrap_command
import yaml
from yaml.events import AliasEvent, MappingStartEvent, ScalarEvent, SequenceStartEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.kubernetes_context import CONTAINER_KINDS, POD_SPEC_PATHS
from sarj_standards.libs.linting.toml_literals import TomlStringLocationError, parse_toml_string_lines
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items

from .shell_ast import parse_shell as parse_shell


if TYPE_CHECKING:
    from yaml.error import Mark


type ShellParser = Callable[[str], Mapping[str, object]]
_MAX_DEPTH = 32
_MAX_NODES = 100_000
_WORKFLOW_PATH_COMPONENTS = 3


class ProgramProjectionError(ValueError):
    """A selected executable field cannot be analyzed completely."""


@dataclass(frozen=True, slots=True)
class ExecutionBlock:
    line: int
    source: str = ""
    argv: tuple[str, ...] = ()
    interpreter: str = "shell"
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class SourceEnd:
    line: int
    column: int


@dataclass(slots=True)
class _ComposeBudget:
    remaining: int = _MAX_NODES

    def consume(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            msg = "YAML expansion exceeds analysis node bound"
            raise ProgramProjectionError(msg)


def _alias_copy(node: Node, start: Mark, end: Mark, budget: _ComposeBudget, depth: int = 0) -> Node:
    budget.consume()
    if depth >= _MAX_DEPTH:
        msg = "recursive or excessively nested YAML alias"
        raise ProgramProjectionError(msg)
    if isinstance(node, ScalarNode):
        return ScalarNode(node.tag, _scalar_text(node), start, end, node.style)
    if isinstance(node, SequenceNode):
        return SequenceNode(
            node.tag,
            [_alias_copy(item, start, end, budget, depth + 1) for item in sequence_items(node)],
            start,
            end,
            node.flow_style,
        )
    if isinstance(node, MappingNode):
        return MappingNode(
            node.tag,
            [
                (_alias_copy(key, start, end, budget, depth + 1), _alias_copy(value, start, end, budget, depth + 1))
                for key, value in mapping_items(node)
            ],
            start,
            end,
            node.flow_style,
        )
    msg = "unsupported YAML node"
    raise ProgramProjectionError(msg)


class _OccurrenceLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._budget: _ComposeBudget = _ComposeBudget()
        self._active_anchors: set[str] = set()

    @override
    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        self._budget.consume()
        if self.check_event(AliasEvent):  # pyright: ignore[reportUnknownMemberType] -- PyYAML composer boundary.
            event: object = self.get_event()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] -- PyYAML event boundary.
            if not isinstance(event, AliasEvent):
                msg = "expected YAML alias event"
                raise ProgramProjectionError(msg)
            anchor: object = event.anchor  # pyright: ignore[reportAny] -- PyYAML alias boundary.
            if not isinstance(anchor, str) or anchor not in self.anchors:
                msg = "undefined YAML alias"
                raise ProgramProjectionError(msg)
            if anchor in self._active_anchors:
                msg = "recursive YAML alias cannot be projected safely"
                raise ProgramProjectionError(msg)
            start: Mark = event.start_mark  # pyright: ignore[reportAny] -- PyYAML source mark boundary.
            end: Mark = event.end_mark  # pyright: ignore[reportAny] -- PyYAML source mark boundary.
            return _alias_copy(self.anchors[anchor], start, end, self._budget)
        pending: object = self.peek_event()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] -- PyYAML composer boundary.
        raw_anchor: object = None
        if isinstance(pending, (MappingStartEvent, SequenceStartEvent, ScalarEvent)):
            raw_anchor = pending.anchor  # pyright: ignore[reportAny] -- PyYAML event anchor boundary.
        active = raw_anchor if isinstance(raw_anchor, str) else None
        if active is not None:
            self._active_anchors.add(active)
        try:
            return super().compose_node(parent, index)
        finally:
            if active is not None:
                self._active_anchors.remove(active)


def _table(node: Node | None, depth: int = 0) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    if depth >= _MAX_DEPTH:
        msg = "YAML merge nesting exceeds analysis bound"
        raise ProgramProjectionError(msg)
    result: dict[str, Node] = {}
    explicit: dict[str, Node] = {}
    for key, value in mapping_items(node):
        if not isinstance(key, ScalarNode):
            continue
        if key.tag == "tag:yaml.org,2002:merge":
            _merge_fields(result, value, depth)
            continue
        if _scalar_text(key) in explicit:
            msg = f"duplicate YAML key: {_scalar_text(key)}"
            raise ProgramProjectionError(msg)
        explicit[_scalar_text(key)] = value
    result.update(explicit)
    return result


def _merge_fields(result: dict[str, Node], value: Node, depth: int) -> None:
    mappings = _items(value) if isinstance(value, SequenceNode) else [value]
    for merged in mappings:
        for name, inherited in _table(merged, depth + 1).items():
            result.setdefault(name, inherited)


def _items(node: Node | None) -> list[Node]:
    return sequence_items(node) if isinstance(node, SequenceNode) else []


def _scalar_text(node: ScalarNode) -> str:
    value: object = node.value  # pyright: ignore[reportAny] -- PyYAML scalar boundary.
    if not isinstance(value, str):
        msg = "YAML scalar text is not a string"
        raise ProgramProjectionError(msg)
    return value


def _scalar(node: Node | None) -> str | None:
    return _scalar_text(node) if isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:str" else None


def _argv(node: Node | None) -> tuple[str, ...] | None:
    if not isinstance(node, SequenceNode):
        return None
    values = [_scalar(item) for item in sequence_items(node)]
    if any(value is None for value in values):
        msg = "execution argv must contain only strings"
        raise ProgramProjectionError(msg)
    return tuple(value for value in values if value is not None)


def _block(node: Node, *, interpreter: str = "shell") -> ExecutionBlock:
    value = _scalar(node)
    if value is None:
        msg = "execution source must be a string"
        raise ProgramProjectionError(msg)
    end = _node_end(node)
    return ExecutionBlock(
        node.start_mark.line + 1, value, interpreter=interpreter, end_line=end.line, end_column=end.column
    )


def _node_end(node: Node) -> SourceEnd:
    mark = node.end_mark
    buffer: object = mark.buffer
    if isinstance(buffer, str):
        prefix = buffer[: mark.index].rstrip(" \t")
        if prefix.endswith(("\n", "\r")):
            previous = prefix.removesuffix("\n").removesuffix("\r")
            return SourceEnd(mark.line, len(previous.rsplit("\n", 1)[-1]) + 1)
    return SourceEnd(mark.line + 1, mark.column + 1)


def _argv_block(node: Node, argv: tuple[str, ...], end: Node | None = None) -> ExecutionBlock:
    owner = node if end is None or node.start_mark.index <= end.start_mark.index else end
    last = node if end is None or node.end_mark.index >= end.end_mark.index else end
    position = _node_end(last)
    return ExecutionBlock(owner.start_mark.line + 1, argv=argv, end_line=position.line, end_column=position.column)


def _container(node: Node) -> list[ExecutionBlock]:
    fields = _table(node)
    command, arguments = fields.get("command"), fields.get("args")
    command_argv, argument_argv = _argv(command), _argv(arguments)
    if command is None:
        return []  # Image defaults cannot be inferred from configuration.
    if command_argv is None:
        if isinstance(command, ScalarNode):
            return [_block(command)]
            # Compose command strings are argv, NOT automatically shell source.
            # A caller normalizes Compose separately.
        msg = "unsupported container command"
        raise ProgramProjectionError(msg)
    if arguments is not None and argument_argv is None:
        msg = "container args must be an argv sequence"
        raise ProgramProjectionError(msg)
    return [_argv_block(command, command_argv + (argument_argv or ()), arguments)]


def _walk(node: Node, *, depth: int = 0) -> list[Node]:
    if depth >= _MAX_DEPTH:
        msg = "configuration nesting exceeds analysis bound"
        raise ProgramProjectionError(msg)
    result = [node]
    children: Sequence[Node] = []
    if isinstance(node, MappingNode):
        children = [value for _, value in mapping_items(node)]
    elif isinstance(node, SequenceNode):
        children = sequence_items(node)
    for child in children:
        result.extend(_walk(child, depth=depth + 1))
        if len(result) > _MAX_NODES:
            msg = "configuration exceeds analysis node bound"
            raise ProgramProjectionError(msg)
    return result


def _make_source(source: str, variables: Mapping[str, str] | None = None, depth: int = 0) -> str:
    if depth >= _MAX_DEPTH:
        msg = "Make variable expansion exceeds analysis bound"
        raise ProgramProjectionError(msg)
    result: list[str] = []
    index = 0
    while index < len(source):
        if source.startswith("$$", index):
            result.append("$")
            index += 2
            continue
        if source.startswith(("$(", "${"), index):
            cursor = _make_expansion_end(source, index)
            name = source[index + 2 : cursor - 1]
            if name.lstrip().startswith(("shell ", "eval ")):
                result.append("$(embedded_make_program)")
            elif variables is not None and name in variables:
                result.append(_make_source(variables[name], variables, depth + 1))
            else:
                result.append("make_expansion")
            index = cursor
            continue
        result.append(source[index])
        index += 1
    return "".join(result)


def _make_expansion_end(source: str, index: int) -> int:
    opening = source[index + 1]
    closing = ")" if opening == "(" else "}"
    cursor, nesting = index + 2, 1
    while cursor < len(source) and nesting:
        nesting += int(source[cursor] == opening) - int(source[cursor] == closing)
        cursor += 1
    if nesting:
        msg = "unterminated Make variable expansion"
        raise ProgramProjectionError(msg)
    return cursor


@dataclass(slots=True)
class _MakeRecipes:
    oneshell: bool
    variables: Mapping[str, str]
    contexts: Mapping[int, tuple[Mapping[str, str], ...]] = field(
        default_factory=dict[int, tuple[Mapping[str, str], ...]]
    )
    prefix: str = "\t"
    pending: list[str] = field(default_factory=list)
    blocks: list[ExecutionBlock] = field(default_factory=list)
    start: int = 0

    def consume(self, line: str, number: int) -> None:
        if line.startswith(".RECIPEPREFIX"):
            value = line.split("=", 1)[-1].strip()
            self.prefix = value[:1] or "\t"
        if self.pending and self.pending[-1].endswith("\\"):
            self.pending.append(line[1:] if line.startswith(self.prefix) else line)
            if not self.oneshell and not line.endswith("\\"):
                self.flush()
            return
        if line.startswith(self.prefix):
            self.add_recipe(line[1:].lstrip(" \t@-+"), number)
            return
        if self.oneshell and not line.strip():
            return
        self.flush()
        if (command := _make_inline_recipe(line)) is not None:
            self.add_recipe(command.lstrip(" \t@-+"), number)

    def add_recipe(self, command: str, number: int) -> None:
        if not self.pending:
            self.start = number
        self.pending.append(command)
        if not self.oneshell and not command.endswith("\\"):
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        for variables in self.contexts.get(self.start, (self.variables,)):
            self.blocks.append(
                ExecutionBlock(
                    self.start,
                    _make_source("\n".join(self.pending), variables),
                    interpreter=_make_source(
                        variables.get("SHELL", "/bin/sh") + " " + variables.get(".SHELLFLAGS", "-c"), variables
                    ),
                )
            )
        self.pending = []


def _docker_heredoc(command: str) -> re.Match[str] | None:
    quote = ""
    escaped = False
    operators: list[int] = []
    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
        elif _docker_heredoc_operator(command, index):
            operators.append(index)
    matches = [
        match
        for offset in operators
        if (match := re.match(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", command[offset:])) is not None
    ]
    if len(matches) > 1:
        msg = "multiple Docker heredoc bodies require external source"
        raise ProgramProjectionError(msg)
    return matches[0] if matches else None


def _docker_heredoc_operator(command: str, index: int) -> bool:
    return (
        command[index : index + 2] == "<<"
        and command[index : index + 3] != "<<<"
        and (index == 0 or command[index - 1] != "<")
    )


@dataclass(frozen=True, slots=True)
class _DockerInstruction:
    name: str
    command: str
    start: int
    end: SourceEnd
    deferred: bool = False


@dataclass(slots=True)
class _DockerCursor:
    lines: Sequence[str]
    escape: str
    index: int = 0

    def read_instruction(self) -> _DockerInstruction | None:
        start = self.index + 1
        line = self.read_line()
        match = re.match(
            r"\s*(?:(ONBUILD)\s+)?(FROM|RUN|CMD|ENTRYPOINT|SHELL|COPY|HEALTHCHECK)\s+(.+)", line, re.IGNORECASE
        )
        if match is None:
            return None
        command = re.sub(r"^(?:--[a-z-]+=\S+\s+)+", "", match[3])
        if match[2].casefold() != "from" and not command.startswith("["):
            command = self.read_heredoc(command)
        if match[2].casefold() == "copy":
            return None  # COPY heredoc bodies write data, not instructions.
        return _DockerInstruction(
            match[2].casefold(),
            command,
            start,
            SourceEnd(self.index, len(self.lines[self.index - 1]) + 1),
            bool(match[1]),
        )

    def read_line(self) -> str:
        line = self.lines[self.index]
        self.index += 1
        if line.lstrip().startswith("#"):
            return line  # Parser directives/comments never continue instructions.
        while line.endswith(self.escape) and self.index < len(self.lines):
            following = self.lines[self.index].lstrip()
            self.index += 1
            if not following.startswith("#"):
                line = line[:-1] + " " + following
        return line

    def read_heredoc(self, command: str) -> str:
        heredoc = _docker_heredoc(command)
        if heredoc is None:
            return command
        body: list[str] = []
        while self.index < len(self.lines):
            body.append(self.lines[self.index])
            self.index += 1
            if (body[-1].lstrip("\t") if heredoc[1] else body[-1]) == heredoc[3]:
                return "\n".join(body[:-1]) if command.startswith("<<") else command + "\n" + "\n".join(body)
        msg = "unterminated Docker heredoc"
        raise ProgramProjectionError(msg)


def _mise_template(value: str, *, execution: bool) -> str:

    def replace(match: re.Match[str]) -> str:
        token = match[0]
        if token.startswith("{#"):
            return ""
        expression = token[2:-2].strip()
        literal = re.fullmatch(r"(['\"])([^\\'\"\r\n]*)\1", expression)
        if token.startswith("{{") and literal:
            return literal[2]
        if token.startswith("{{") and re.fullmatch(r"-?\d+(?:\.\d+)?|true|false", expression):
            return expression
        if token.startswith("{{") and not execution and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", expression):
            return token  # Environment value references do not invoke a program.
        msg = "mise executable template cannot be interpreted statically without running configuration"
        raise ProgramProjectionError(msg)

    rendered = re.sub(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", replace, value, flags=re.DOTALL)
    remaining = rendered if execution else re.sub(r"\{\{\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\}\}", "", rendered)
    if any(marker in remaining for marker in ("{{", "{%", "{#")):
        msg = "mise execution template is incomplete or dynamic"
        raise ProgramProjectionError(msg)
    return rendered


def _mise_environment(value: object) -> None:
    if isinstance(value, str):
        _mise_template(value, execution=False)
    elif is_object_mapping(value):
        for field in value.values():
            _mise_environment(field)
    elif is_object_list(value):
        for field in value:
            _mise_environment(field)


def _mise_shell(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = "mise task shell must be a nonempty string"
        raise ProgramProjectionError(msg)
    return _mise_template(value, execution=True)


def execution_blocks(relative: str, source: str, *, platform: str | None = None) -> list[ExecutionBlock]:
    name = relative.rsplit("/", 1)[-1].casefold()
    if name in {"makefile", "gnumakefile"}:
        return _make_blocks(source)
    if not name.endswith(".dockerignore") and (
        name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile")
    ):
        return _docker_blocks(source)
    if (
        name in {"mise.toml", ".mise.toml"}
        or (name.startswith("mise.") and name.endswith(".toml"))
        or (name == "config.toml" and ".mise" in relative.split("/"))
    ):
        return _toml_blocks(source)
    if name.endswith((".yaml", ".yml", ".json")):
        return _yaml_blocks(relative, source, platform=sys.platform if platform is None else platform)
    return []


def _toml_blocks(source: str) -> list[ExecutionBlock]:
    try:
        parsed = parse_toml_string_lines(source)
        document = parsed.document
        string_lines = parsed.string_lines
    except tomllib.TOMLDecodeError as error:
        msg = "invalid selected mise configuration"
        raise ProgramProjectionError(msg) from error
    except TomlStringLocationError as error:
        msg = "selected mise configuration has unverified native string locations"
        raise ProgramProjectionError(msg) from error
    _mise_environment(document.get("env"))
    _mise_environment(document.get("vars"))
    tasks = document.get("tasks")
    if not is_object_mapping(tasks):
        return []
    blocks: list[ExecutionBlock] = []
    task_config = document.get("task_config")
    default_shell = _mise_shell(task_config.get("shell", "shell") if is_object_mapping(task_config) else "shell")
    for name, task_value in tasks.items():
        if not isinstance(name, str):
            msg = "native mise task names must be TOML string keys"
            raise ProgramProjectionError(msg)
        task = _mise_task_fields(task_value)
        if task is None:
            continue
        run_path = ("tasks", name) if isinstance(task_value, str) else ("tasks", name, "run")
        for index, block in enumerate(_mise_task_blocks(task, 1, default_shell)):
            command_path = run_path if isinstance(task["run"], str) else (*run_path, index)
            line = string_lines.get(command_path)
            if line is None:
                msg = "mise task run has no native-verified source location"
                raise ProgramProjectionError(msg)
            blocks.append(replace(block, line=line))
    return blocks


def _mise_task_blocks(task: Mapping[str, object], line: int, default_shell: str) -> list[ExecutionBlock]:
    _mise_environment(task.get("env"))
    shell = _mise_shell(task.get("shell", default_shell))
    run = task["run"]
    commands = [run] if isinstance(run, str) else run
    if not is_object_list(commands) or not all(isinstance(command, str) for command in commands):
        msg = "mise task run must be a string or string sequence"
        raise ProgramProjectionError(msg)
    return [
        ExecutionBlock(line, _mise_template(command, execution=True), interpreter=shell)
        for command in commands
        if isinstance(command, str)
    ]


def _mise_task_fields(value: object) -> Mapping[str, object] | None:
    if isinstance(value, str):
        return {"run": value}
    if is_object_mapping(value) and "run" in value:
        return {key: item for key, item in value.items() if isinstance(key, str)}
    return None


@dataclass(slots=True)
class _DockerStage:
    shell: tuple[str, ...] = ()
    entrypoint: ExecutionBlock | None = None
    command: ExecutionBlock | None = None
    healthcheck: _DockerInstruction | None = None
    entrypoint_shell: bool = False
    entrypoint_known: bool = False
    command_local: bool = False

    def consume(self, instruction: _DockerInstruction) -> list[ExecutionBlock]:
        if instruction.name == "run":
            return [_docker_execution(instruction, self.shell)]
        if instruction.deferred:
            if instruction.name == "entrypoint":
                return [_docker_execution(instruction, self.shell)]
            deferred = _DockerStage(shell=self.shell)
            if instruction.name == "healthcheck":
                deferred.consume(replace(instruction, deferred=False))
            return deferred.blocks()
        if instruction.name == "shell":
            words = _docker_json_argv(instruction.command)
            if words is None:
                msg = "Docker SHELL requires JSON argv"
                raise ProgramProjectionError(msg)
            self.shell = words
        elif instruction.name == "entrypoint":
            words = _docker_json_argv(instruction.command)
            self.entrypoint = _docker_execution(instruction, self.shell) if words != () else None
            self.entrypoint_shell, self.entrypoint_known = words is None, True
            if not self.command_local:
                self.command = None  # A new ENTRYPOINT clears inherited CMD.
        elif instruction.name == "cmd":
            self.command = (
                _docker_execution(instruction, self.shell) if _docker_json_argv(instruction.command) != () else None
            )
            self.command_local = True
        elif instruction.name == "healthcheck":
            self.healthcheck = _docker_healthcheck(instruction)
        return []

    def blocks(self) -> list[ExecutionBlock]:
        result = [_docker_execution(self.healthcheck, self.shell)] if self.healthcheck is not None else []
        entrypoint = self.entrypoint
        if entrypoint is not None and self.entrypoint_shell:
            return [*result, entrypoint]  # Shell-form ENTRYPOINT ignores CMD.
        command = self.command
        if entrypoint is None and not self.entrypoint_known:
            return result  # External image ENTRYPOINT defaults are unknown.
        if entrypoint is None or not entrypoint.argv:
            return [*result, *([command] if command is not None else [])]
        if command is None:
            return [*result, entrypoint]
        if classify_interpreter(entrypoint.argv).kind == "inline":
            return [*result, entrypoint]  # CMD only supplies data to this declared source.
        command_argv = command.argv or ("/bin/sh", "-c", command.source)
        last = max((entrypoint, command), key=lambda block: block.end_line or block.line)
        return [
            *result,
            replace(
                entrypoint,
                line=min(entrypoint.line, command.line),
                argv=entrypoint.argv + command_argv,
                end_line=last.end_line,
                end_column=last.end_column,
            ),
        ]


def _docker_blocks(source: str) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    state = _DockerStage()
    stages: dict[str, _DockerStage] = {}
    stage = ""
    lines = source.splitlines()
    cursor = _DockerCursor(lines, _docker_escape(lines))
    while cursor.index < len(cursor.lines):
        instruction = cursor.read_instruction()
        if instruction is None:
            continue
        if instruction.name == "from":
            blocks.extend(state.blocks())
            if stage:
                stages[stage] = state
            match = re.fullmatch(r"\s*(\S+)(?:\s+[Aa][Ss]\s+([A-Za-z][A-Za-z0-9_.-]*))?\s*", instruction.command)
            state = _DockerStage()
            stage = ""
            if match is not None:
                inherited = stages.get(
                    match[1].casefold(), _DockerStage(entrypoint_known=match[1].casefold() == "scratch")
                )
                state = replace(inherited, command_local=False)
                stage = (match[2] or "").casefold()
            continue
        blocks.extend(state.consume(instruction))
    blocks.extend(state.blocks())
    return sorted(dict.fromkeys(blocks), key=lambda block: (block.line, block.end_line or block.line))


def _docker_escape(lines: Sequence[str]) -> str:
    escape = "\\"
    for line in lines:
        directive = re.fullmatch(r"\s*#\s*(syntax|escape|check)\s*=\s*(\S.*?)\s*", line, re.IGNORECASE)
        if directive is None:
            break
        if directive[1].casefold() == "escape" and directive[2] in {"`", "\\"}:
            escape = directive[2]
    return escape


def _docker_healthcheck(instruction: _DockerInstruction) -> _DockerInstruction | None:
    if instruction.command.casefold() == "none":
        return None
    match = re.match(r"CMD\s+(.*)", instruction.command, re.IGNORECASE | re.DOTALL)
    if match is None:
        msg = "Docker HEALTHCHECK requires CMD or NONE"
        raise ProgramProjectionError(msg)
    return replace(instruction, command=match[1])


def _docker_execution(instruction: _DockerInstruction, shell_argv: tuple[str, ...]) -> ExecutionBlock:
    words = _docker_json_argv(instruction.command)
    if words is not None:
        return ExecutionBlock(
            instruction.start, argv=words, end_line=instruction.end.line, end_column=instruction.end.column
        )
    if shell_argv:
        return ExecutionBlock(
            instruction.start,
            argv=(*shell_argv, instruction.command),
            end_line=instruction.end.line,
            end_column=instruction.end.column,
        )
    return ExecutionBlock(
        instruction.start, instruction.command, end_line=instruction.end.line, end_column=instruction.end.column
    )


def _docker_json_argv(command: str) -> tuple[str, ...] | None:
    if not command.startswith("["):
        return None
    try:
        argv = parse_json(command)
    except ValueError as error:
        msg = "invalid Docker execution JSON"
        raise ProgramProjectionError(msg) from error
    if not is_object_list(argv) or not all(isinstance(argument, str) for argument in argv):
        msg = "Docker execution JSON must contain string argv"
        raise ProgramProjectionError(msg)
    return tuple(argument for argument in argv if isinstance(argument, str))


def _make_blocks(source: str) -> list[ExecutionBlock]:
    lines = source.splitlines()
    oneshell = any(re.match(r"^\s*\.ONESHELL\s*:", line) for line in lines)
    recipes = _MakeRecipes(oneshell, _make_variables(lines), _make_recipe_contexts(lines))
    for number, line in enumerate(lines, 1):
        recipes.consume(line, number)
    recipes.flush()
    return recipes.blocks


_MAKE_ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_.][A-Za-z0-9_.]*)\s*(:::=|::=|:=|[?+]?=)\s*(.*)")


@dataclass(slots=True)
class _MakeVariables:
    values: dict[str, str] = field(default_factory=dict)
    simple: set[str] = field(default_factory=set)

    def fork(self) -> _MakeVariables:
        return _MakeVariables(dict(self.values), set(self.simple))

    def overlay(self, other: _MakeVariables) -> _MakeVariables:
        if not other.values:
            return self
        values = self.values | other.values
        simple = (self.simple - other.values.keys()) | other.simple
        return _MakeVariables(values, simple)

    def consume(self, assignment: re.Match[str]) -> bool:
        name, operator, value = assignment.groups()
        value = re.split(r"(?<!\\)#", value, maxsplit=1)[0].rstrip()
        if operator == "?=" and name in self.values:
            return False
        if operator in {":=", "::=", ":::="} or (operator == "+=" and name in self.simple):
            value = _make_source(value, self.values).replace("$", "$$")
        if operator == "+=" and name in self.values:
            self.values[name] += " " + value
            return True
        self.values[name] = value
        if operator in {":=", "::="}:
            self.simple.add(name)
        else:
            self.simple.discard(name)
        return True


def _make_variables(lines: Sequence[str]) -> dict[str, str]:
    state = _MakeVariables({"SHELL": "/bin/sh", ".SHELLFLAGS": "-c"})
    for line in lines:
        if assignment := _MAKE_ASSIGNMENT.fullmatch(line):
            state.consume(assignment)
    return state.values


@dataclass(slots=True)
class _MakeScopes:
    global_values: _MakeVariables = field(
        default_factory=lambda: _MakeVariables({"SHELL": "/bin/sh", ".SHELLFLAGS": "-c"})
    )
    local_values: dict[str, _MakeVariables] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)
    recipes: dict[int, tuple[str, ...]] = field(default_factory=dict)
    owners: tuple[str, ...] = ()
    variant_cache: dict[str, tuple[_MakeVariables, ...]] = field(default_factory=dict)
    remaining: int = _MAX_NODES

    def consume(self, line: str, number: int) -> None:
        prefix = self.global_values.values.get(".RECIPEPREFIX", "\t")[:1] or "\t"
        if line.startswith(prefix):
            self.recipes[number] = self.owners
            return
        if assignment := _MAKE_ASSIGNMENT.fullmatch(line):
            self.global_values.consume(assignment)
            return
        header, colon, body = line.partition(":")
        if not colon:
            return
        names = _make_scope_words(header, self.global_values.values)
        if assignment := _make_target_assignment(body):
            self.assign(names, assignment)
            return
        self.owners = names
        if _make_inline_recipe(line) is not None:
            self.recipes[number] = self.owners
        dependencies = _make_scope_words(body.split(";", 1)[0], self.global_values.values)
        for dependency in dependencies:
            if dependency != "|":
                self.parents.setdefault(dependency, []).extend(name for name in names if name != dependency)

    def assign(self, names: tuple[str, ...], assignment: re.Match[str]) -> None:
        for name in names:
            previous = self.local_values.get(name, _MakeVariables())
            combined = self.global_values.fork().overlay(previous)
            if combined.consume(assignment):
                variable = assignment[1]
                previous.values[variable] = combined.values[variable]
                if variable in combined.simple:
                    previous.simple.add(variable)
                else:
                    previous.simple.discard(variable)
                self.local_values[name] = previous

    def variants(self, name: str, active: tuple[str, ...] = ()) -> tuple[_MakeVariables, ...]:
        if name in active or len(active) >= _MAX_DEPTH:
            msg = "Make target variable inheritance cannot be bounded"
            raise ProgramProjectionError(msg)
        if name in self.variant_cache:
            return self.variant_cache[name]
        parents = (state for parent in self.parents.get(name, ()) for state in self.variants(parent, (*active, name)))
        inherited = chain((self.global_values,), parents)
        patterns = _make_pattern_states(name, self.local_values)
        result: dict[tuple[tuple[str, str], ...], _MakeVariables] = {}
        for initial in inherited:
            self.remaining -= len(initial.values) + 1
            state = initial
            for _, pattern in patterns:
                state = state.overlay(pattern)
            state = state.overlay(self.local_values.get(name, _MakeVariables()))
            result[tuple(sorted(state.values.items()))] = state
            if self.remaining < 0:
                msg = "Make target variable contexts exceed analysis bound"
                raise ProgramProjectionError(msg)
        self.variant_cache[name] = tuple(result.values())
        return self.variant_cache[name]

    def recipe_variants(self, owners: tuple[str, ...]) -> tuple[Mapping[str, str], ...]:
        variants: list[Mapping[str, str]] = []
        for owner in owners:
            for name in self.recipe_names(owner):
                variants.extend(state.values for state in self.variants(name))
        return tuple(variants) or (self.global_values.values,)

    def recipe_names(self, owner: str) -> tuple[str, ...]:
        if "%" not in owner:
            return (owner,)
        declared = self.local_values.keys() | self.parents.keys()
        names = tuple(name for name in sorted(declared) if _make_pattern_stem(owner, name) is not None)
        return (owner, *names)


def _make_target_assignment(body: str) -> re.Match[str] | None:
    return _MAKE_ASSIGNMENT.fullmatch(body.strip().removeprefix("override "))


def _make_inline_recipe(line: str) -> str | None:
    if _MAKE_ASSIGNMENT.fullmatch(line):
        return None
    _, colon, body = line.partition(":")
    if not colon or _make_target_assignment(body):
        return None
    index = 0
    while index < len(body):
        if body.startswith(("$(", "${"), index):
            index = _make_expansion_end(body, index)
        elif body[index] == "\\":
            index += 2
        elif body[index] == "#":
            return None
        elif body[index] == ";":
            return body[index + 1 :]
        else:
            index += 1
    return None


def _make_scope_words(source: str, variables: Mapping[str, str]) -> tuple[str, ...]:
    expanded = _make_source(source.split("#", 1)[0], variables)
    if "make_expansion" in expanded or "\\" in expanded or "$(" in expanded or "${" in expanded:
        msg = "Make target or prerequisite words cannot be proven statically"
        raise ProgramProjectionError(msg)
    return tuple(expanded.split())


def _make_pattern_stem(pattern: str, name: str) -> int | None:
    if "%" not in pattern:
        return None
    prefix, _, suffix = pattern.partition("%")
    if "%" in suffix or not name.startswith(prefix) or not name.endswith(suffix):
        return None
    length = len(name) - len(prefix) - len(suffix)
    return length if length >= 0 else None


def _make_pattern_states(name: str, bindings: Mapping[str, _MakeVariables]) -> list[tuple[int, _MakeVariables]]:
    patterns: list[tuple[int, _MakeVariables]] = []
    values: dict[str, str] = {}
    for pattern, state in bindings.items():
        stem = _make_pattern_stem(pattern, name)
        if stem is None:
            continue
        for variable, value in state.values.items():
            if variable in values and values[variable] != value:
                # GNU Make 3.81 uses declaration order; modern Make uses stem
                # specificity. Configuration does not establish that version.
                msg = "Make conflicting pattern variable precedence cannot be proven"
                raise ProgramProjectionError(msg)
            values[variable] = value
        patterns.append((stem, state))
    return sorted(patterns, key=itemgetter(0), reverse=True)


def _make_recipe_contexts(lines: Sequence[str]) -> dict[int, tuple[Mapping[str, str], ...]]:
    # Ordinary Makefiles keep the existing global assignment fast path.
    if not any(
        not line.startswith("\t") and ":" in line and _make_target_assignment(line.partition(":")[2]) for line in lines
    ):
        return {}
    scopes = _MakeScopes()
    for number, line in enumerate(lines, 1):
        scopes.consume(line, number)
    contexts: dict[int, tuple[Mapping[str, str], ...]] = {}
    for number, owners in scopes.recipes.items():
        contexts[number] = scopes.recipe_variants(owners)
    return contexts


def _yaml_blocks(relative: str, source: str, *, platform: str) -> list[ExecutionBlock]:
    try:
        documents: list[Node | None] = list(yaml.compose_all(source, Loader=_OccurrenceLoader))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- PyYAML composition boundary.
    except yaml.YAMLError:
        return []  # The YAML syntax adapter owns malformed document diagnostics.
    blocks: list[ExecutionBlock] = []
    for document in documents:
        if document is not None:
            blocks.extend(_yaml_consumer_blocks(relative, document, platform=platform))
    return blocks


def _yaml_consumer_blocks(relative: str, document: Node, *, platform: str) -> list[ExecutionBlock]:
    top = _table(document)
    if (relative.startswith(".github/workflows/") and len(relative.split("/")) == _WORKFLOW_PATH_COMPONENTS) or (
        "runs" in top and "using" in _table(top["runs"])
    ):
        return _actions_blocks(top)
    if "steps" in top and any("name" in _table(step) for step in _items(top.get("steps"))):
        return _cloudbuild_blocks(top)
    if (_scalar(top.get("apiVersion")) or "").startswith("skaffold/"):
        return _skaffold_blocks(document, platform=platform)
    if "services" in top:
        return _compose_blocks(top["services"])
    if "kind" in top and "apiVersion" in top:
        return _kubernetes_blocks(document)
    return []


def _compose_blocks(services: Node) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    for service in _table(services).values():
        fields = _table(service)
        command, entrypoint = fields.get("command"), fields.get("entrypoint")
        words = (_compose_words(entrypoint) or ()) + (_compose_words(command) or ())
        owner = entrypoint if entrypoint is not None else command
        if owner is not None and words:
            blocks.append(_argv_block(owner, words, command))
        blocks.extend(_compose_healthcheck_blocks(_table(fields.get("healthcheck"))))
    return [
        replace(
            block, source=block.source.replace("$$", "$"), argv=tuple(word.replace("$$", "$") for word in block.argv)
        )
        for block in blocks
    ]


def _compose_healthcheck_blocks(healthcheck: Mapping[str, Node]) -> list[ExecutionBlock]:
    test = healthcheck.get("test")
    if _compose_healthcheck_disabled(healthcheck.get("disable")) or test is None:
        return []
    value, argv = _scalar(test), _argv(test)
    if value is not None:
        return [_block(test)]
    if argv and argv[0] == "CMD-SHELL":
        return [
            ExecutionBlock(
                test.start_mark.line + 1,
                source=" ".join(argv[1:]),
                end_line=test.end_mark.line + 1,
                end_column=test.end_mark.column + 1,
            )
        ]
    if argv and argv[0] == "CMD":
        return [_argv_block(test, argv[1:])]
    return []


def _compose_healthcheck_disabled(node: Node | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ScalarNode) and node.tag in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:str"}:
        # compose-go casts constant strings using its YAML boolean grammar.
        value = _scalar_text(node).lower()
        if value in {"true", "y", "yes", "on"}:
            return True
        if value in {"false", "n", "no", "off"}:
            return False
    msg = "Compose healthcheck disable value cannot be proven statically"
    raise ProgramProjectionError(msg)


def _compose_words(node: Node | None) -> tuple[str, ...] | None:
    import shlex  # ruff: ignore[import-outside-top-level] -- Compose command is argv with shell quoting, not shell execution.

    if node is None:
        return None
    value = _scalar(node)
    if value is None:
        return _argv(node)
    try:
        return tuple(shlex.split(value))
    except ValueError as error:
        msg = "malformed Compose command quoting"
        raise ProgramProjectionError(msg) from error


def _cloudbuild_blocks(top: Mapping[str, Node]) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    for step in _items(top.get("steps")):
        fields = _table(step)
        if "script" in fields:
            blocks.append(_block(fields["script"]))
            continue
        entrypoint = _scalar(fields.get("entrypoint"))
        arguments = _argv(fields.get("args"))
        if entrypoint is not None:
            words = tuple(word.replace("$$", "$") for word in (entrypoint, *(arguments or ())))
            blocks.append(_argv_block(fields["entrypoint"], words, fields.get("args")))
    return blocks


def _actions_blocks(top: Mapping[str, Node]) -> list[ExecutionBlock]:
    defaults = _table(_table(top.get("defaults")).get("run"))
    workflow_shell = _scalar(defaults.get("shell")) or "shell"
    blocks: list[ExecutionBlock] = []
    for job in _table(top.get("jobs")).values():
        fields = _table(job)
        defaults = _table(_table(fields.get("defaults")).get("run"))
        shell = _scalar(defaults.get("shell")) or workflow_shell
        blocks.extend(_actions_step_blocks(_items(fields.get("steps")), interpreter=shell))
    blocks.extend(_actions_step_blocks(_items(_table(top.get("runs")).get("steps")), interpreter="shell"))
    return blocks


def _actions_step_blocks(steps: Sequence[Node], *, interpreter: str) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    for step in steps:
        fields = _table(step)
        if (run := fields.get("run")) is not None:
            blocks.append(_block(run, interpreter=_scalar(fields.get("shell")) or interpreter))
    return blocks


def _kubernetes_blocks(document: Node, *, depth: int = 0) -> list[ExecutionBlock]:
    if depth >= _MAX_DEPTH:
        msg = "Kubernetes List nesting exceeds analysis bound"
        raise ProgramProjectionError(msg)
    fields = _table(document)
    version, resource_kind = _scalar(fields.get("apiVersion")), _scalar(fields.get("kind"))
    if version is None or resource_kind is None:
        return []
    identity = (version, resource_kind)
    if identity == ("v1", "List"):
        return [block for item in _items(fields.get("items")) for block in _kubernetes_blocks(item, depth=depth + 1)]
    path = POD_SPEC_PATHS.get(identity)
    if path is None:
        return []
    for key in path:
        fields = _table(fields.get(key))
    return [
        block
        for kind in CONTAINER_KINDS
        for container in _items(fields.get(kind))
        for block in [*_container(container), *_kubernetes_hooks(_table(container))]
    ]


def _kubernetes_hooks(fields: Mapping[str, Node]) -> list[ExecutionBlock]:
    lifecycle = _table(fields.get("lifecycle"))
    hooks = [
        *(lifecycle.get(hook) for hook in ("postStart", "preStop")),
        *(fields.get(probe) for probe in ("livenessProbe", "readinessProbe", "startupProbe")),
    ]
    blocks: list[ExecutionBlock] = []
    for hook in hooks:
        execute = _table(hook).get("exec")
        if "command" in _table(execute) and execute is not None:
            blocks.extend(_container(execute))
    return blocks


def _skaffold_blocks(document: Node, *, platform: str) -> list[ExecutionBlock]:
    top = _table(document)
    return [
        block
        for fields in [top, *(_table(profile) for profile in _items(top.get("profiles")))]
        for block in _skaffold_pipeline_blocks(fields, platform=platform)
    ]


def _skaffold_pipeline_blocks(fields: Mapping[str, Node], *, platform: str) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    build = _table(fields.get("build"))
    blocks.extend(_skaffold_hook_blocks(build))
    for artifact in _items(build.get("artifacts")):
        blocks.extend(_skaffold_artifact_blocks(_table(artifact), platform=platform))
    for test in _items(fields.get("test")):
        for custom_test in _items(_table(test).get("custom")):
            custom = _table(custom_test)
            if "command" in custom:
                blocks.append(_skaffold_shell_block(_block(custom["command"]), platform=platform))
            dependencies = _table(custom.get("dependencies"))
            if "command" in dependencies:
                blocks.append(
                    _skaffold_shell_block(_block(dependencies["command"]), platform=platform, templated=False)
                )
    for verify in _items(fields.get("verify")):
        container = _table(verify).get("container")
        if container is not None:
            blocks.extend(_container(container))
    for action in _items(fields.get("customActions")):
        for container in _items(_table(action).get("containers")):
            blocks.extend(_container(container))
    blocks.extend(_skaffold_hook_blocks(_table(fields.get("manifests"))))
    deploy = _table(fields.get("deploy"))
    for deployer in ("kubectl", "helm", "cloudrun"):
        blocks.extend(_skaffold_hook_blocks(_table(deploy.get(deployer))))
    return blocks


def _skaffold_artifact_blocks(fields: Mapping[str, Node], *, platform: str) -> list[ExecutionBlock]:
    blocks = _skaffold_hook_blocks(fields)
    blocks.extend(_skaffold_hook_blocks(_table(fields.get("sync"))))
    custom = _table(fields.get("custom"))
    if "buildCommand" in custom:
        blocks.append(_skaffold_shell_block(_block(custom["buildCommand"]), platform=platform))
    dependencies = _table(custom.get("dependencies"))
    # Skaffold prefers Dockerfile dependency extraction over a command.
    command = dependencies.get("command")
    if command is None or isinstance(dependencies.get("dockerfile"), MappingNode):
        return blocks
    value = _scalar(command)
    if value is None:
        msg = "Skaffold dependency command must be a string"
        raise ProgramProjectionError(msg)
    if value:
        # Upstream uses strings.Split, without shell quote processing.
        blocks.append(_argv_block(command, tuple(value.split(" "))))
    return blocks


def _skaffold_hook_blocks(fields: Mapping[str, Node]) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    hooks = _table(fields.get("hooks"))
    for phase in ("before", "after"):
        for hook in _items(hooks.get(phase)):
            hook_fields = _table(hook)
            owners = [hook, *(hook_fields[key] for key in ("host", "container") if key in hook_fields)]
            for owner in owners:
                blocks.extend(_skaffold_hook_command(_table(owner).get("command")))
    return blocks


def _skaffold_hook_command(command: Node | None) -> list[ExecutionBlock]:
    if command is None:
        return []
    argv = _argv(command)
    if argv is None:
        msg = "Skaffold hook command must be an argv sequence"
        raise ProgramProjectionError(msg)
    return [_argv_block(command, argv)]


def _skaffold_shell_block(block: ExecutionBlock, *, platform: str, templated: bool = True) -> ExecutionBlock:
    if platform == "win32":
        msg = "Windows Skaffold cmd.exe execution cannot be projected as POSIX shell"
        raise ProgramProjectionError(msg)
    if templated and ("{{" in block.source or "}}" in block.source):
        msg = "Skaffold executable template cannot be proven statically"
        raise ProgramProjectionError(msg)
    return block


def _mapping(value: object) -> Mapping[str, object]:
    if not is_object_mapping(value) or not all(isinstance(key, str) for key in value):
        msg = "invalid shfmt AST object"
        raise ProgramProjectionError(msg)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _nodes(value: object) -> list[Mapping[str, object]]:
    if value is None:
        return []
    if not is_object_list(value):
        msg = "invalid shfmt AST node sequence"
        raise ProgramProjectionError(msg)
    return [_mapping(item) for item in value]


def _argv_embeds_program(
    argv: Sequence[str], parse_shell: ShellParser, depth: int = 0, *, input_sources: Mapping[str, bool] | None = None
) -> bool:
    if depth >= _MAX_DEPTH:
        msg = "shell wrapper nesting exceeds analysis depth"
        raise ProgramProjectionError(msg)
    invocation = classify_interpreter(argv)
    if invocation.kind == "inline":
        return True
    if invocation.kind == "unknown":
        msg = "interpreter option grammar cannot be proven"
        raise ProgramProjectionError(msg)
    if invocation.kind == "stdin":
        return bool(input_sources and input_sources.get("0"))
    if invocation.kind == "shell":
        if invocation.payload is None or "${dynamic}" in invocation.payload:
            msg = "shell -c payload cannot be proven statically"
            raise ProgramProjectionError(msg)
        return _shell_embeds_program(
            invocation.payload,
            parse_shell,
            depth + 1,
            forwarded=invocation.forwarded,
            input_sources=dict(input_sources or {}),
        )
    return False


def _shell_embeds_program(
    source: str,
    parse_shell: ShellParser,
    depth: int = 0,
    *,
    forwarded: tuple[str, ...] | None = None,
    input_sources: dict[str, bool] | None = None,
) -> bool:
    if depth >= _MAX_DEPTH:
        msg = "shell wrapper nesting exceeds analysis depth"
        raise ProgramProjectionError(msg)
    # Workflow expressions are evaluated by Actions before shell parsing. Treat
    # each expression as an opaque word, never interpret its contents as shell.
    source = re.sub(r"\$\{\{.*?\}\}", "workflow_expression", source, flags=re.DOTALL)
    tree = parse_shell(source)
    if tree.get("Type") != "File":
        msg = "shfmt did not return a File AST"
        raise ProgramProjectionError(msg)
    statements = _nodes(tree.get("Stmts"))
    sources = input_sources if input_sources is not None else {}
    results = [
        _shell_statement_embeds_program(statement, parse_shell, depth, forwarded, sources) for statement in statements
    ]
    return any(results)


def _shell_statement_embeds_program(
    statement: Mapping[str, object],
    parse_shell: ShellParser,
    depth: int,
    forwarded: tuple[str, ...] | None,
    input_sources: dict[str, bool],
) -> bool:
    if any(statement.get(key) for key in ("Negated", "Background", "Coprocess", "Disown")):
        return True
    command = _mapping(statement.get("Cmd"))
    if command.get("Type") != "CallExpr" or _contains_execution(statement):
        return True
    arguments = _nodes(command.get("Args"))
    words = tuple(_word(argument) for argument in arguments)
    argv = tuple(
        item
        for word in words
        for item in (forwarded if forwarded is not None and word == "${forwarded-arguments}" else (word,))
    )
    if not argv:
        return True  # Assignment-only blocks are programs, not invocations.
    redirections = _nodes(statement.get("Redirs"))
    redirected: set[str] = set()
    sources = _shell_input_sources(redirections, input_sources, redirected=redirected)
    if _shell_exec_persists(argv):
        input_sources.update(sources)  # Commandless exec installs redirections in this shell.
        return False
    if (index := _shell_builtin_eval_index(argv)) is not None:
        result = _shell_eval_embeds_program(
            arguments, parse_shell, depth, sources, forwarded=forwarded, prefix=argv[:index]
        )
        input_sources.update(
            {descriptor: source for descriptor, source in sources.items() if descriptor not in redirected}
        )
        return result
    return _argv_embeds_program(argv, parse_shell, depth, input_sources=sources)


def _shell_exec_persists(argv: tuple[str, ...]) -> bool:
    if argv[0] not in {"exec", "command"} or "exec" not in argv:
        return False
    try:
        selected = unwrap_command(argv, allowed_wrappers=frozenset())
    except UnprovableCommandError as error:
        msg = "interpreter option grammar cannot be proven"
        raise ProgramProjectionError(msg) from error
    return not selected


def _shell_builtin_eval_index(words: tuple[str, ...]) -> int | None:
    if words[0] == "eval":
        return 1
    if words[0] != "command":
        return None
    try:
        selected = unwrap_command(words, allowed_wrappers=frozenset())
    except UnprovableCommandError:
        return None  # The ordinary argv owner reports unsupported wrappers.
    prefix = len(words) - len(selected)
    if selected[:1] == ("eval",) and all(word == "command" or word.startswith("-") for word in words[:prefix]):
        return prefix + 1
    return None  # exec/env and external paths do not invoke shell builtins.


def _shell_eval_embeds_program(
    arguments: Sequence[Mapping[str, object]],
    parse_shell: ShellParser,
    depth: int,
    input_sources: dict[str, bool],
    *,
    forwarded: tuple[str, ...] | None,
    prefix: tuple[str, ...],
) -> bool:
    literal: list[str] = []
    for argument in arguments:
        try:
            word = _word(argument, require_literal=True)
        except ProgramProjectionError:
            if forwarded is None or _word(argument) != "${forwarded-arguments}":
                raise
            literal.extend(forwarded)
        else:
            literal.append(word)
    if tuple(literal[: len(prefix)]) != prefix:
        return False  # A literal marker is data, not a forwarded shell parameter.
    words = literal[len(prefix) :]
    if words and words[0] == "--":
        words = words[1:]
    return _shell_embeds_program(" ".join(words), parse_shell, depth + 1, input_sources=input_sources)


def _shell_input_sources(
    redirections: Sequence[Mapping[str, object]], inherited: Mapping[str, bool] | None, *, redirected: set[str]
) -> dict[str, bool]:
    # Shell applies redirections left to right; only the final fd0 is stdin.
    descriptors = dict(inherited or {})
    for redirection in redirections:
        operation = str(redirection.get("Op", ""))
        descriptor = (
            _mapping(redirection["N"]).get("Value") if "N" in redirection else "0" if operation.startswith("<") else "1"
        )
        if not isinstance(descriptor, str):
            continue
        redirected.add(descriptor)
        if operation in {"<&", ">&"}:
            copied = _word(_mapping(redirection.get("Word")))
            descriptors[descriptor] = descriptors.get(copied.removesuffix("-"), False)
            if copied.endswith("-"):
                descriptors[copied[:-1]] = False
                redirected.add(copied[:-1])
        else:
            descriptors[descriptor] = redirection.get("Hdoc") is not None or operation == "<<<"
    return descriptors


def _contains_execution(node: object, depth: int = 0) -> bool:
    if depth >= _MAX_DEPTH:
        msg = "shell AST exceeds analysis depth"
        raise ProgramProjectionError(msg)
    if is_object_mapping(node):
        if node.get("Type") in {"CmdSubst", "ProcSubst", "ArithmCmd", "ArithmExp"}:
            return True
        return any(
            _contains_execution(value, depth + 1)
            for key, value in node.items()
            if key not in {"Pos", "End", "Comments", "Last"}
        )
    if is_object_list(node):
        return any(_contains_execution(item, depth + 1) for item in node)
    return False


def _word(node: Mapping[str, object], *, quoted: bool = False, require_literal: bool = False) -> str:
    pieces: list[str] = []
    for part in _nodes(node.get("Parts")):
        kind = part.get("Type")
        match part:
            case {"Type": "Lit", "Value": str() as value}:
                pieces.append(_literal(value, quoted=quoted))
            case {"Type": "Lit"}:
                msg = "invalid shfmt literal"
                raise ProgramProjectionError(msg)
            case {"Type": "SglQuoted"}:
                value = part.get("Value", "")
                if not isinstance(value, str):
                    msg = "invalid shfmt literal"
                    raise ProgramProjectionError(msg)
                pieces.append(_ansi_literal(value) if part.get("Dollar") else value)
            case {"Type": "DblQuoted"}:
                pieces.append(_word(part, quoted=True, require_literal=require_literal))
            case _:
                if require_literal:
                    msg = "selected interpreter payload cannot be proven statically"
                    raise ProgramProjectionError(msg)
                if kind == "ParamExp" and quoted and _mapping(part.get("Param")).get("Value") == "@":
                    pieces.append("${forwarded-arguments}")
                else:
                    pieces.append("${dynamic}")
    return "".join(pieces)


def _literal(value: str, *, quoted: bool) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            if following == "\n":
                index += 2
                continue
            if not quoted or following in {"$", "`", '"', "\\"}:
                character = following
                index += 1
        result.append(character)
        index += 1
    return "".join(result)


def _ansi_literal(value: str) -> str:
    escapes = {
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "E": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "?": "?",
    }

    def replace(match: re.Match[str]) -> str:
        escaped = match[0][1:]
        if escaped in escapes:
            return escapes[escaped]
        if escaped.startswith(("x", "u", "U")) and len(escaped) > 1:
            try:
                return chr(int(escaped[1:], 16))
            except ValueError as error:
                msg = "unsupported ANSI-C quoted codepoint"
                raise ProgramProjectionError(msg) from error
        if escaped[0] in string.octdigits:
            return chr(int(escaped, 8) % 256)
        if escaped.startswith("c") and len(escaped) > 1:
            return chr(127 if escaped[1] == "?" else ord(escaped[1].upper()) & 31)
        if escaped == "\n":
            return ""
        return "\\" + escaped

    decoded = re.sub(
        r"\\(?:x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|c.|.)", replace, value, flags=re.DOTALL
    )
    return decoded.split("\0", 1)[0]


def block_embeds_program(block: ExecutionBlock, *, parse_shell: ShellParser) -> bool:
    if block.argv:
        return _argv_embeds_program(block.argv, parse_shell)
    shell = block.interpreter.split()[0].rsplit("/", 1)[-1].casefold()
    if "${{" in block.interpreter:
        msg = f"unsupported configuration execution shell: {shell}"
        raise ProgramProjectionError(msg)
    if len(block.interpreter.split()) != 1:
        return _configured_shell_embeds_program(block, parse_shell)
    if block.source.startswith("#!") and re.search(
        r"\b(?:python[23]?(?:\.\d+)?|node|perl|ruby|php)\b", block.source.splitlines()[0]
    ):
        return True
    if shell not in {"shell", "sh", "bash", "dash", "zsh", "ksh"}:
        # Actions shell: python executes the run field as source regardless of
        # whether that source happens to look like a shell command.
        if re.fullmatch(r"python(?:[23](?:\.\d+)?)?|node|perl|ruby|php", shell):
            return True
        msg = f"unsupported configuration execution shell: {shell}"
        raise ProgramProjectionError(msg)
    return _shell_embeds_program(block.source, parse_shell)


def _configured_shell_embeds_program(block: ExecutionBlock, parse_shell: ShellParser) -> bool:
    statements = _nodes(parse_shell(block.interpreter).get("Stmts"))
    if len(statements) != 1 or _contains_execution(statements[0]):
        msg = "configured interpreter argv cannot be proven statically"
        raise ProgramProjectionError(msg)
    command = _mapping(statements[0].get("Cmd"))
    if command.get("Type") != "CallExpr" or command.get("Assigns") or statements[0].get("Redirs"):
        msg = "configured interpreter must be a literal invocation"
        raise ProgramProjectionError(msg)
    argv = tuple(_word(word) for word in _nodes(command.get("Args")))
    if "{0}" not in argv:
        argv = (*argv, block.source)
    invocation = classify_interpreter(argv)
    if invocation.kind == "other":
        msg = f"unsupported configuration execution shell: {argv[0]}"
        raise ProgramProjectionError(msg)
    if (
        "{0}" in argv
        and invocation.kind == "external"
        and classify_interpreter(argv[: argv.index("{0}")]).kind == "stdin"
    ):
        shell = unwrap_command(argv)[0].rsplit("/", 1)[-1].casefold()
        return (
            _shell_embeds_program(block.source, parse_shell) if shell in {"sh", "bash", "dash", "zsh", "ksh"} else True
        )
    return _argv_embeds_program(argv, parse_shell)
