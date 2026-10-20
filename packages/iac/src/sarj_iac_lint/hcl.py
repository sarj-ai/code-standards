from __future__ import annotations

from dataclasses import dataclass
import re
import textwrap
from typing import Final

from . import _hcl


_TEMPLATE: Final = re.compile(r"(?<!\$)\$\{|(?<!%)%\{")
_SHELLS: Final = frozenset({"bash", "dash", "sh", "zsh", "ksh"})
_SHELL_OPTION: Final = re.compile(r"-[eux]+|--noprofile|--norc")


@dataclass(frozen=True, slots=True)
class CommandLiteral:
    source: str
    line: int
    physical_lines: bool


def local_exec_commands(source: str) -> tuple[CommandLiteral, ...]:
    commands: list[CommandLiteral] = []
    lines = source.splitlines()
    if not _balanced_structure(source):
        return ()
    try:
        resources = _hcl.blocks(source)
    except ValueError:
        return ()
    for resource in resources:
        if resource.type != "resource":
            continue
        for provisioner in resource.blocks:
            if provisioner.type != "provisioner" or provisioner.labels != ("local-exec",):
                continue
            if not _shell_interpreter(provisioner.attribute("interpreter")):
                continue
            attribute = provisioner.attribute("command")
            if attribute is not None and (command := _command_literal(attribute, lines)) is not None:
                commands.append(command)
    return tuple(commands)


def _balanced_structure(source: str) -> bool:
    closers: list[str] = []
    try:
        structural = _hcl.tokens(source)
    except ValueError:
        return False
    for token in structural:
        if token in {"{", "[", "("}:
            closers.append({"{": "}", "[": "]", "(": ")"}[token])
        elif token in {"}", "]", ")"} and (not closers or closers.pop() != token):
            return False
    return not closers


def _shell_interpreter(attribute: _hcl.Attribute | None) -> bool:
    if attribute is None:
        return True
    arguments = _literal_arguments(attribute.value)
    if not arguments:
        return False
    return (
        arguments[0].rsplit("/", 1)[-1] in _SHELLS
        and arguments[-1] == "-c"
        and all(_SHELL_OPTION.fullmatch(option) for option in arguments[1:-1])
    )


def _literal_arguments(value: str) -> tuple[str, ...]:
    parts = _hcl.strip_outer_parentheses(_hcl.tokens(value))
    if parts[:1] != ("[",) or parts[-1:] != ("]",):
        return ()
    arguments: list[str] = []
    for element in _hcl.comma_parts(parts[1:-1]):
        argument = _hcl.literal_string("".join(element))
        if argument is None:
            return ()
        arguments.append(argument)
    return tuple(arguments)


def _command_literal(attribute: _hcl.Attribute, lines: list[str]) -> CommandLiteral | None:
    value_line = attribute.value_line or attribute.line
    if marker := re.fullmatch(r"<<-?\s*([A-Za-z_]\w*)", attribute.value):
        end = next(
            (index for index in range(value_line, len(lines)) if lines[index].strip() == marker[1]),
            None,
        )
        if end is None:
            return None
        body = "\n".join(lines[value_line:end])
        if attribute.value.startswith("<<-"):
            body = textwrap.dedent(body)
        return _literal_template(body, value_line + 1, physical_lines=True)
    value = _hcl.literal_string(attribute.value)
    return CommandLiteral(value, value_line, physical_lines=False) if value is not None else None


def _literal_template(source: str, line: int, *, physical_lines: bool) -> CommandLiteral | None:
    if _TEMPLATE.search(source):
        return None
    return CommandLiteral(source.replace("$${", "${").replace("%%{", "%{"), line, physical_lines)
