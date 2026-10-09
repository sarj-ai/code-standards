from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import re
import string
import sys
import tomllib
from typing import TYPE_CHECKING, override

from sarj_python_lint.interpreter_argv import classify_interpreter
import yaml
from yaml.events import AliasEvent, MappingStartEvent, ScalarEvent, SequenceStartEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from sarj_standards.libs.json_boundary import parse_json
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
            self.add_recipe(line[1:].lstrip("@-+"), number)
            return
        if self.oneshell and not line.strip():
            return
        self.flush()

    def add_recipe(self, command: str, number: int) -> None:
        if not self.pending:
            self.start = number
        self.pending.append(command)
        if not self.oneshell and not command.endswith("\\"):
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        self.blocks.append(
            ExecutionBlock(
                self.start,
                _make_source("\n".join(self.pending), self.variables),
                interpreter=self.variables.get("SHELL", "shell"),
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


@dataclass(slots=True)
class _DockerCursor:
    lines: Sequence[str]
    escape: str
    index: int = 0

    def read_instruction(self) -> _DockerInstruction | None:
        start = self.index + 1
        line = self.read_line()
        match = re.match(r"\s*(?:ONBUILD\s+)?(FROM|RUN|CMD|ENTRYPOINT|SHELL)\s+(.+)", line, re.IGNORECASE)
        if match is None:
            return None
        command = re.sub(r"^(?:--[a-z-]+=\S+\s+)+", "", match[2])
        if match[1].casefold() != "from" and not command.startswith("["):
            command = self.read_heredoc(command)
        return _DockerInstruction(
            match[1].casefold(), command, start, SourceEnd(self.index, len(self.lines[self.index - 1]) + 1)
        )

    def read_line(self) -> str:
        line = self.lines[self.index]
        self.index += 1
        while line.endswith(self.escape) and self.index < len(self.lines):
            line = line[:-1] + " " + self.lines[self.index].lstrip()
            self.index += 1
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
        document: Mapping[str, object] = tomllib.loads(source)
    except tomllib.TOMLDecodeError as error:
        msg = "invalid selected mise configuration"
        raise ProgramProjectionError(msg) from error
    _mise_environment(document.get("env"))
    _mise_environment(document.get("vars"))
    tasks = document.get("tasks")
    if not is_object_mapping(tasks):
        return []
    blocks: list[ExecutionBlock] = []
    task_config = document.get("task_config")
    default_shell = _mise_shell(task_config.get("shell", "shell") if is_object_mapping(task_config) else "shell")
    run_lines = [number for number, line in enumerate(source.splitlines(), 1) if re.match(r"\s*run\s*=", line)]
    cursor = 0
    for task_value in tasks.values():
        task = _mise_task_fields(task_value)
        if task is None:
            continue
        line = run_lines[cursor] if cursor < len(run_lines) else 1
        blocks.extend(_mise_task_blocks(task, line, default_shell))
        cursor += 1
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


def _docker_blocks(source: str) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    shell_argv: tuple[str, ...] = ()
    escape = "`" if re.search(r"(?im)^\s*#\s*escape\s*=\s*`\s*$", source) else "\\"
    cursor = _DockerCursor(source.splitlines(), escape)
    while cursor.index < len(cursor.lines):
        instruction = cursor.read_instruction()
        if instruction is None:
            continue
        if instruction.name == "from":
            shell_argv = ()
            continue
        words = _docker_json_argv(instruction.command)
        if instruction.name == "shell":
            if words is None:
                msg = "Docker SHELL requires JSON argv"
                raise ProgramProjectionError(msg)
            shell_argv = words
            continue
        blocks.append(_docker_execution(instruction, shell_argv, words))
    return blocks


def _docker_execution(
    instruction: _DockerInstruction, shell_argv: tuple[str, ...], words: tuple[str, ...] | None
) -> ExecutionBlock:
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
    recipes = _MakeRecipes(oneshell, _make_variables(lines))
    for number, line in enumerate(lines, 1):
        recipes.consume(line, number)
    recipes.flush()
    return recipes.blocks


def _make_variables(lines: Sequence[str]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for line in lines:
        assignment = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*([?:+]?=)\s*(.*)", line)
        if assignment is not None:
            name, operator, value = assignment.groups()
            # Make comments are independent of shell quoting; an unescaped #
            # terminates the assignment before recipe expansion.
            value = re.split(r"(?<!\\)#", value, maxsplit=1)[0].rstrip()
            if operator == "+=" and name in variables:
                variables[name] += " " + value
            elif operator != "?=" or name not in variables:
                variables[name] = value
    return variables


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
        healthcheck = _table(fields.get("healthcheck"))
        test = healthcheck.get("test")
        if test is not None:
            value, argv = _scalar(test), _argv(test)
            if value is not None:
                blocks.append(_block(test))
            elif argv and argv[0] == "CMD-SHELL":
                blocks.append(
                    ExecutionBlock(
                        test.start_mark.line + 1,
                        source=" ".join(argv[1:]),
                        end_line=test.end_mark.line + 1,
                        end_column=test.end_mark.column + 1,
                    )
                )
            elif argv and argv[0] == "CMD":
                blocks.append(_argv_block(test, argv[1:]))
    return [
        replace(
            block, source=block.source.replace("$$", "$"), argv=tuple(word.replace("$$", "$") for word in block.argv)
        )
        for block in blocks
    ]


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
    steps = [step for job in _table(top.get("jobs")).values() for step in _items(_table(job).get("steps"))]
    steps.extend(_items(_table(top.get("runs")).get("steps")))
    blocks: list[ExecutionBlock] = []
    for step in steps:
        fields = _table(step)
        if (run := fields.get("run")) is not None:
            blocks.append(_block(run, interpreter=_scalar(fields.get("shell")) or "shell"))
    return blocks


def _kubernetes_blocks(document: Node) -> list[ExecutionBlock]:
    blocks: list[ExecutionBlock] = []
    for node in _walk(document):
        blocks.extend(_kubernetes_execution_fields(_table(node)))
    return blocks


def _kubernetes_execution_fields(fields: Mapping[str, Node]) -> list[ExecutionBlock]:
    blocks = [
        block
        for key in ("containers", "initContainers", "ephemeralContainers")
        for container in _items(fields.get(key))
        for block in _container(container)
    ]
    hooks = [
        *_table(fields.get("lifecycle")).values(),
        *(fields.get(probe) for probe in ("livenessProbe", "readinessProbe", "startupProbe")),
    ]
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
    argv: Sequence[str], parse_shell: ShellParser, depth: int = 0, *, stdin_program: bool = False
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
        return stdin_program
    if invocation.kind == "shell":
        if invocation.payload is None or "${dynamic}" in invocation.payload:
            msg = "shell -c payload cannot be proven statically"
            raise ProgramProjectionError(msg)
        return _shell_embeds_program(invocation.payload, parse_shell, depth + 1, forwarded=invocation.forwarded)
    return False


def _shell_embeds_program(
    source: str, parse_shell: ShellParser, depth: int = 0, *, forwarded: tuple[str, ...] | None = None
) -> bool:
    # Workflow expressions are evaluated by Actions before shell parsing. Treat
    # each expression as an opaque word, never interpret its contents as shell.
    source = re.sub(r"\$\{\{.*?\}\}", "workflow_expression", source, flags=re.DOTALL)
    tree = parse_shell(source)
    if tree.get("Type") != "File":
        msg = "shfmt did not return a File AST"
        raise ProgramProjectionError(msg)
    statements = _nodes(tree.get("Stmts"))
    if not statements:
        return False
    if len(statements) != 1:
        return True
    statement = statements[0]
    if any(statement.get(key) for key in ("Negated", "Background", "Coprocess", "Disown")):
        return True
    command = _mapping(statement.get("Cmd"))
    if command.get("Type") != "CallExpr" or _contains_execution(statement):
        return True
    words = tuple(_word(argument) for argument in _nodes(command.get("Args")))
    argv = tuple(
        item
        for word in words
        for item in (forwarded if forwarded is not None and word == "${forwarded-arguments}" else (word,))
    )
    if not argv:
        return True  # Assignment-only blocks are programs, not invocations.
    redirections = _nodes(statement.get("Redirs"))
    stdin_program = any(
        redirection.get("Hdoc") is not None or redirection.get("Op") == "<<<" for redirection in redirections
    )
    return _argv_embeds_program(argv, parse_shell, depth, stdin_program=stdin_program)


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


def _word(node: Mapping[str, object], *, quoted: bool = False) -> str:
    pieces: list[str] = []
    for part in _nodes(node.get("Parts")):
        kind = part.get("Type")
        if kind in {"Lit", "SglQuoted"}:
            value = part.get("Value")
            if not isinstance(value, str):
                msg = "invalid shfmt literal"
                raise ProgramProjectionError(msg)
            pieces.append(
                _literal(value, quoted=quoted)
                if kind == "Lit"
                else _ansi_literal(value)
                if part.get("Dollar")
                else value
            )
        elif kind == "DblQuoted":
            pieces.append(_word(part, quoted=True))
        elif kind == "ParamExp" and quoted and _mapping(part.get("Param")).get("Value") == "@":
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
    if block.source.startswith("#!") and re.search(
        r"\b(?:python[23]?(?:\.\d+)?|node|perl|ruby|php)\b", block.source.splitlines()[0]
    ):
        return True
    shell = block.interpreter.split()[0].rsplit("/", 1)[-1].casefold()
    if shell not in {"shell", "sh", "bash", "dash", "zsh", "ksh"}:
        # Actions shell: python executes the run field as source regardless of
        # whether that source happens to look like a shell command.
        if re.fullmatch(r"python(?:[23](?:\.\d+)?)?|node|perl|ruby|php", shell):
            return True
        msg = f"unsupported configuration execution shell: {shell}"
        raise ProgramProjectionError(msg)
    return _shell_embeds_program(block.source, parse_shell)
