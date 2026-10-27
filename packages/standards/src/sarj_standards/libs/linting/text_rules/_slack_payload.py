from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from pydantic import JsonValue

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.shell_ast import ShellSyntaxError, parse_shell


_BUILDER_STATEMENTS = 2
_BUILDER_WITH_SETUP_STATEMENTS = 3
_PRINTF_ARGUMENTS = 3
_IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*")
_MAX_SOURCE = 131_072
_MAX_DEPTH = 32
_MAX_VALUES = 2_048


@dataclass(frozen=True, slots=True)
class _String:
    value: str
    variables: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Variable:
    name: str


type _Value = _String | _Variable | dict[str, _Value] | list[_Value] | bool | int | None


@dataclass(frozen=True, slots=True)
class _BuilderStatements:
    assignment: Mapping[str, JsonValue]
    writer: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _PayloadBinding:
    name: str
    call: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _JqBindings:
    bound: frozenset[str]
    tainted: frozenset[str]


@dataclass(frozen=True, slots=True)
class _JqPayload:
    value: _Value
    tainted: frozenset[str]


class _UnsupportedError(ValueError):
    pass


@dataclass(slots=True)
class _Constructor:
    source: str
    cursor: int = 0
    values: int = 0

    def parse(self) -> _Value:
        value = self.value(0)
        self.whitespace()
        if self.cursor != len(self.source):
            raise _UnsupportedError
        return value

    def whitespace(self) -> None:
        while self.cursor < len(self.source) and self.source[self.cursor] in " \n\t":
            self.cursor += 1

    def take(self, token: str) -> bool:
        self.whitespace()
        if self.source.startswith(token, self.cursor):
            self.cursor += len(token)
            return True
        return False

    def identifier(self) -> str:
        self.whitespace()
        match = _IDENTIFIER.match(self.source, self.cursor)
        if match is None:
            raise _UnsupportedError
        self.cursor = match.end()
        return match.group()

    def value(self, depth: int) -> _Value:
        self.values += 1
        if depth > _MAX_DEPTH or self.values > _MAX_VALUES:
            raise _UnsupportedError
        self.whitespace()
        if self.cursor >= len(self.source):
            raise _UnsupportedError
        match self.source[self.cursor]:
            case '"':
                return self.string()
            case "$":
                self.cursor += 1
                return _Variable(self.identifier())
            case "{":
                return self.object(depth + 1)
            case "[":
                return self.array(depth + 1)
            case _:
                return self.scalar()

    def array(self, depth: int) -> list[_Value]:
        self.cursor += 1
        values: list[_Value] = []
        if self.take("]"):
            return values
        while True:
            values.append(self.value(depth))
            if self.take("]"):
                return values
            if not self.take(","):
                raise _UnsupportedError

    def scalar(self) -> bool | int | None:
        for token, value in (("true", True), ("false", False), ("null", None)):
            if self.take(token):
                return value
        match = re.match(r"-?(?:0|[1-9][0-9]*)", self.source[self.cursor :])
        if match is None:
            raise _UnsupportedError
        self.cursor += match.end()
        return int(match.group())

    def object(self, depth: int) -> dict[str, _Value]:
        self.cursor += 1
        fields: dict[str, _Value] = {}
        if self.take("}"):
            return fields
        while True:
            self.whitespace()
            key = self.string() if self.source.startswith('"', self.cursor) else _String(self.identifier())
            if key.variables or key.value in fields or not self.take(":"):
                raise _UnsupportedError
            fields[key.value] = self.value(depth)
            if self.take("}"):
                return fields
            if not self.take(","):
                raise _UnsupportedError

    def string(self) -> _String:
        self.cursor += 1
        parts = ['"']
        variables: set[str] = set()
        while self.cursor < len(self.source):
            character = self.source[self.cursor]
            self.cursor += 1
            if character == '"':
                parts.append(character)
                decoded = parse_json("".join(parts))
                if not isinstance(decoded, str):
                    raise _UnsupportedError
                return _String(decoded, frozenset(variables))
            if character == "\\":
                self.escape(parts, variables)
            else:
                parts.append(character)
        raise _UnsupportedError

    def escape(self, parts: list[str], variables: set[str]) -> None:
        if self.cursor >= len(self.source):
            raise _UnsupportedError
        escaped = self.source[self.cursor]
        self.cursor += 1
        if escaped != "(":
            parts.extend(("\\", escaped))
            return
        if not self.take("$"):
            raise _UnsupportedError
        variables.add(self.identifier())
        if not self.take(")"):
            raise _UnsupportedError


def _mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    return dict(value) if isinstance(value, dict) else {}


def _nodes(value: JsonValue) -> list[Mapping[str, JsonValue]]:
    return [_mapping(item) for item in value] if isinstance(value, list) else []


def _literal(word: Mapping[str, JsonValue]) -> str | None:
    parts = _nodes(word.get("Parts"))
    if len(parts) != 1:
        return None
    part = parts[0]
    if part.get("Type") in {"Lit", "SglQuoted"} and not part.get("Dollar"):
        value = part.get("Value")
        return value if isinstance(value, str) else None
    return _literal(part) if part.get("Type") == "DblQuoted" else None


def _parameter(word: Mapping[str, JsonValue]) -> str | None:
    parts = _nodes(word.get("Parts"))
    if len(parts) != 1:
        return None
    part = parts[0]
    if part.get("Type") != "DblQuoted":
        return None
    parts = _nodes(part.get("Parts"))
    if len(parts) != 1:
        return None
    part = parts[0]
    if part.get("Type") != "ParamExp":
        return None
    admitted = {"Type", "Pos", "End", "Dollar", "Rbrace", "Short", "Param", "Exp"}
    expansion = _mapping(part.get("Exp"))
    if part.keys() - admitted or (expansion and expansion.get("Op") not in {"?", ":?"}):
        return None
    value = _mapping(part.get("Param")).get("Value")
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def payload_markup_uses(program: str, *, output: str, tainted_environment: frozenset[str]) -> int:
    if len(program) > _MAX_SOURCE or not tainted_environment or "jq" not in program:
        return 0
    statements = _builder_statements(program)
    if statements is None:
        return 0
    binding = _payload_binding(statements.assignment)
    if binding is None:
        return 0
    parsed = _jq(binding.call, tainted_environment)
    if parsed is None or not _writes_output(statements.writer, output=output, name=binding.name):
        return 0
    return sum(bool(variables & parsed.tainted) for variables in _markup_uses(parsed.value))


def references_github_environment(program: str) -> bool:
    if "GITHUB_ENV" not in program:
        return False
    if len(program) > _MAX_SOURCE:
        return True
    try:
        pending = [parse_shell(program)]
    except ShellSyntaxError:
        return True
    while pending:
        node = pending.pop()
        if node.get("Type") == "ParamExp" and _mapping(node.get("Param")).get("Value") == "GITHUB_ENV":
            return True
        for value in node.values():
            if isinstance(value, dict):
                pending.append(_mapping(value))
            elif isinstance(value, list):
                pending.extend(_nodes(value))
    return False


def _builder_statements(program: str) -> _BuilderStatements | None:
    try:
        statements = _nodes(parse_shell(program).get("Stmts"))
    except ShellSyntaxError:
        return None
    if len(statements) == _BUILDER_WITH_SETUP_STATEMENTS:
        setup = _mapping(statements[0].get("Cmd"))
        words = tuple(_literal(item) for item in _nodes(setup.get("Args")))
        if words != ("set", "-euo", "pipefail") or setup.get("Assigns"):
            return None
        statements = statements[1:]
    if len(statements) != _BUILDER_STATEMENTS or any(
        statement.get("Negated") or statement.get("Background") for statement in statements
    ):
        return None
    return _BuilderStatements(statements[0], statements[1])


def _payload_binding(assignment: Mapping[str, JsonValue]) -> _PayloadBinding | None:
    command = _mapping(assignment.get("Cmd"))
    assignments = _nodes(command.get("Assigns"))
    if command.get("Type") != "CallExpr" or command.get("Args") or assignment.get("Redirs") or len(assignments) != 1:
        return None
    binding = assignments[0]
    if binding.get("Append") or binding.get("Index") or binding.get("Array"):
        return None
    name = _mapping(binding.get("Name")).get("Value")
    if not isinstance(name, str):
        return None
    parts = _nodes(_mapping(binding.get("Value")).get("Parts"))
    if len(parts) != 1 or parts[0].get("Type") != "CmdSubst":
        return None
    nested = _nodes(parts[0].get("Stmts"))
    if len(nested) != 1 or nested[0].get("Redirs") or nested[0].get("Negated") or nested[0].get("Background"):
        return None
    return _PayloadBinding(name, _mapping(nested[0].get("Cmd")))


def _jq(call: Mapping[str, JsonValue], tainted_environment: frozenset[str]) -> _JqPayload | None:
    if call.get("Type") != "CallExpr" or call.get("Assigns"):
        return None
    arguments = _nodes(call.get("Args"))
    if not arguments or _literal(arguments[0]) != "jq":
        return None
    bindings = _jq_bindings(arguments, tainted_environment)
    if bindings is None:
        return None
    source = _literal(arguments[-1])
    if source is None or len(source) > _MAX_SOURCE:
        return None
    try:
        payload = _Constructor(source).parse()
    except ValueError, RecursionError:
        return None
    if not _constructor_variables(payload).issubset(bindings.bound):
        return None
    return _JqPayload(payload, bindings.tainted)


def _jq_bindings(arguments: list[Mapping[str, JsonValue]], tainted_environment: frozenset[str]) -> _JqBindings | None:
    tainted: set[str] = set()
    bound: set[str] = set()
    null_input = False
    index = 1
    while index < len(arguments) - 1:
        option = _literal(arguments[index])
        if option in {"-n", "-c", "-nc", "-cn", "--null-input", "--compact-output"}:
            null_input |= option in {"-n", "-nc", "-cn", "--null-input"}
            index += 1
            continue
        if option != "--arg" or index + 2 >= len(arguments) - 1:
            return None
        name = _literal(arguments[index + 1])
        value = arguments[index + 2]
        if name is None or not _IDENTIFIER.fullmatch(name) or name in bound:
            return None
        bound.add(name)
        parameter = _parameter(value)
        if parameter is None and _literal(value) is None:
            return None
        if parameter in tainted_environment:
            tainted.add(name)
        index += 3
    if index != len(arguments) - 1 or not null_input or not tainted:
        return None
    return _JqBindings(frozenset(bound), frozenset(tainted))


def _constructor_variables(value: _Value) -> frozenset[str]:
    pending = [value]
    variables: set[str] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, _Variable):
            variables.add(item.name)
        elif isinstance(item, _String):
            variables.update(item.variables)
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return frozenset(variables)


def _writes_output(writer: Mapping[str, JsonValue], *, output: str, name: str) -> bool:
    write_call = _mapping(writer.get("Cmd"))
    arguments = _nodes(write_call.get("Args"))
    redirects = _nodes(writer.get("Redirs"))
    if (
        write_call.get("Type") != "CallExpr"
        or write_call.get("Assigns")
        or len(arguments) != _PRINTF_ARGUMENTS
        or len(redirects) != 1
    ):
        return False
    if (_literal(arguments[0]), _literal(arguments[1]), _parameter(arguments[2])) != (
        "printf",
        f"{output}=%s\\n",
        name,
    ):
        return False
    return redirects[0].get("Op") == ">>" and _parameter(_mapping(redirects[0].get("Word"))) == "GITHUB_OUTPUT"


def _markup_uses(payload: _Value) -> tuple[frozenset[str], ...]:
    if not isinstance(payload, dict):
        return ()
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return ()
    uses: list[frozenset[str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == _String("section"):
            uses.append(_sink_variables(block.get("text")))
        if kind == _String("section") and isinstance(fields := block.get("fields"), list):
            uses.extend(_sink_variables(item) for item in fields)
    return tuple(uses)


def _sink_variables(value: _Value) -> frozenset[str]:
    if not isinstance(value, dict) or value.get("type") != _String("mrkdwn"):
        return frozenset()
    text = value.get("text")
    if isinstance(text, _Variable):
        return frozenset({text.name})
    return text.variables if isinstance(text, _String) else frozenset()
