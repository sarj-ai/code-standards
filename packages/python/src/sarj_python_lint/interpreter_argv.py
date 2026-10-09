from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal


if TYPE_CHECKING:
    from collections.abc import Sequence


_SHORT_ATTACHED_LENGTH = 2


ProgramKind = Literal["external", "inline", "shell", "stdin", "other", "unknown"]


@dataclass(frozen=True, slots=True)
class InterpreterInvocation:
    kind: ProgramKind
    payload: str | None = None
    forwarded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedOption:
    invocation: InterpreterInvocation | None = None
    consumed: int = 1


_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh"})
_NODE_VALUE_FLAGS = frozenset(
    {
        "--require",
        "--import",
        "--loader",
        "--experimental-loader",
        "--input-type",
        "--conditions",
        "--inspect-port",
        "--openssl-config",
        "--icu-data-dir",
        "--title",
    }
)
_JQ_VALUE_FLAGS = MappingProxyType(
    {"--arg": 2, "--argjson": 2, "--slurpfile": 2, "--rawfile": 2, "--indent": 1, "-L": 1}
)
_RUBY_VALUE_FLAGS = frozenset({"I", "r", "C", "X", "E"})
_RUBY_LONG_VALUE_FLAGS = frozenset(
    {"--encoding", "--external-encoding", "--internal-encoding", "--backtrace-limit", "--enable", "--disable"}
)
_WRAPPER_VALUES = MappingProxyType(
    {
        "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
        "sudo": frozenset(
            {
                "-u",
                "--user",
                "-g",
                "--group",
                "-h",
                "--host",
                "-p",
                "--prompt",
                "-C",
                "--close-from",
                "-T",
                "--command-timeout",
                "-R",
                "--chroot",
                "-D",
                "--chdir",
            }
        ),
        "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    }
)
_MAX_WRAPPERS = 8


class UnprovableCommandError(ValueError):
    """A wrapper executable position cannot be established safely."""


def unwrap_command(argv: Sequence[str]) -> tuple[str, ...]:
    current = tuple(argv)
    for _ in range(_MAX_WRAPPERS):
        if not current:
            return ()
        command = PurePosixPath(current[0]).name
        if command in {"exec", "command"}:
            if command == "command" and any(argument in {"-v", "-V"} for argument in current[1:2]):
                return current
            current = current[_command_wrapper_index(current, command) :]
            continue
        if command not in _WRAPPER_VALUES:
            return current
        current = current[_value_wrapper_index(current, command) :]
    msg = "command wrapper nesting exceeds analysis bound"
    raise UnprovableCommandError(msg)


def _command_wrapper_index(arguments: Sequence[str], command: str) -> int:
    index = 1
    while index < len(arguments) and arguments[index].startswith("-"):
        argument = arguments[index]
        if argument == "--":
            return index + 1
        if command == "exec" and argument == "-a":
            index += 2
            continue
        if argument not in {"-p", "-c", "-l"}:
            msg = "unsupported command wrapper option"
            raise UnprovableCommandError(msg)
        index += 1
    return index


def _value_wrapper_index(arguments: Sequence[str], command: str) -> int:
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            break
        if command == "env" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argument):
            index += 1
            continue
        if not argument.startswith("-") or argument == "-":
            break
        if command == "env" and argument in {"-S", "--split-string"}:
            msg = "env split-string has a separate unproven quoting grammar"
            raise UnprovableCommandError(msg)
        index += 2 if argument in _WRAPPER_VALUES[command] else 1
    # Timeout's positional duration precedes its executable.
    return index + int(command == "timeout")


def classify_interpreter(argv: Sequence[str]) -> InterpreterInvocation:
    try:
        arguments = unwrap_command(argv)
    except UnprovableCommandError:
        return InterpreterInvocation("unknown")
    if not arguments:
        return InterpreterInvocation("other")
    executable = PurePosixPath(arguments[0]).name
    if re.fullmatch(r"python(?:[23](?:\.\d+)?)?", executable):
        return _python(arguments[1:])
    if executable in _SHELLS:
        return _short_options(arguments[1:], source="c", values=frozenset({"o", "O"}), shell_mode=True)
    if executable in {"node", "nodejs"}:
        return _node(arguments[1:])
    if executable == "jq":
        return _jq(arguments[1:])
    if executable in {"awk", "gawk", "mawk", "nawk"}:
        return _awk(arguments[1:])
    if executable == "ruby":
        return _ruby(arguments[1:])
    if executable in {"perl", "php"}:
        return _short_options(arguments[1:], source={"perl": "eE", "php": "r"}[executable], values=frozenset({"I"}))
    return InterpreterInvocation("other")


def _python(arguments: Sequence[str]) -> InterpreterInvocation:
    index = 0
    while index < len(arguments):
        boundary = _external_boundary(arguments, index)
        if boundary is not None:
            return boundary
        argument = arguments[index]
        if argument.startswith("--"):
            return InterpreterInvocation(
                "external"
                if argument in {"--help", "--version", "--help-env", "--help-xoptions", "--help-all"}
                else "unknown"
            )
        parsed = _python_short_option(argument, _following_operand(arguments, index))
        if parsed.invocation is not None:
            return parsed.invocation
        index += parsed.consumed
    return InterpreterInvocation("stdin")


def _python_short_option(argument: str, following: str | None) -> ParsedOption:
    for cursor, flag in enumerate(argument[1:], 1):
        if flag in {"h", "V"}:
            return ParsedOption(InterpreterInvocation("external"))
        if flag in {"c", "m", "W", "X"}:
            attached = argument[cursor + 1 :]
            operand = attached or following
            if operand is None:
                return ParsedOption(InterpreterInvocation("unknown"))
            if flag == "c":
                return ParsedOption(InterpreterInvocation("inline", operand))
            if flag == "m":
                return ParsedOption(InterpreterInvocation("external", operand))
            return ParsedOption(consumed=1 + int(not attached))
        if flag not in "bBdEhiIOPqRsSuvVx":
            return ParsedOption(InterpreterInvocation("unknown"))
    return ParsedOption()


def _ruby(arguments: Sequence[str]) -> InterpreterInvocation:
    index = 0
    while index < len(arguments):
        boundary = _external_boundary(arguments, index)
        if boundary is not None:
            return boundary
        parsed = _ruby_option(arguments, index)
        if parsed.invocation is not None:
            return parsed.invocation
        index += parsed.consumed
    return InterpreterInvocation("stdin")


def _ruby_option(arguments: Sequence[str], index: int) -> ParsedOption:
    argument = arguments[index]
    if argument.startswith("--"):
        return _ruby_long_option(argument, _following_operand(arguments, index))
    if re.fullmatch(r"-(?:0[0-7]{0,3}|W[0-2]?)", argument):
        return ParsedOption()
    for cursor, flag in enumerate(argument[1:], 1):
        if flag == "h":
            return ParsedOption(InterpreterInvocation("external"))
        if flag in "Fix":
            # These operands are attached only and consume the rest of this word.
            return ParsedOption()
        if flag == "e" or flag in _RUBY_VALUE_FLAGS:
            if cursor + 1 == len(argument) and _following_operand(arguments, index) is None:
                return ParsedOption(InterpreterInvocation("unknown"))
            return _short_option(arguments, index, source="e", values=_RUBY_VALUE_FLAGS, shell_mode=False)
        if flag not in "acdlnpsSvwU":
            return ParsedOption(InterpreterInvocation("unknown"))
    return ParsedOption()


def _ruby_long_option(argument: str, following: str | None) -> ParsedOption:
    if argument in {"--help", "--version"}:
        return ParsedOption(InterpreterInvocation("external"))
    if argument in {"--debug", "--verbose", "--copyright"}:
        return ParsedOption()
    name, separator, _operand = argument.partition("=")
    if name in _RUBY_LONG_VALUE_FLAGS and (separator or following is not None):
        return ParsedOption(consumed=1 + int(not separator))
    return ParsedOption(InterpreterInvocation("unknown"))


def _short_options(
    arguments: Sequence[str], *, source: str, values: frozenset[str], shell_mode: bool = False
) -> InterpreterInvocation:
    index = 0
    while index < len(arguments):
        boundary = _external_boundary(arguments, index, plus_options=True)
        if boundary is not None:
            return boundary
        argument = arguments[index]
        if argument.startswith("--"):
            index += 2 if shell_mode and argument in {"--rcfile", "--init-file"} else 1
            continue
        parsed = _short_option(arguments, index, source=source, values=values, shell_mode=shell_mode)
        if parsed.invocation is not None:
            return parsed.invocation
        index += parsed.consumed
    return InterpreterInvocation("stdin")


def _short_option(
    arguments: Sequence[str], index: int, *, source: str, values: frozenset[str], shell_mode: bool
) -> ParsedOption:
    argument = arguments[index]
    for cursor, flag in enumerate(argument[1:], 1):
        if flag in source:
            # Shell -c always consumes the next word, including inside -ceu.
            attached = "" if shell_mode else argument[cursor + 1 :]
            operand = attached or _following_operand(arguments, index)
            forwarded = tuple(arguments[index + 3 :]) if shell_mode else ()
            return ParsedOption(InterpreterInvocation("shell" if shell_mode else "inline", operand, forwarded))
        if flag in values:
            return ParsedOption(consumed=1 + int(cursor + 1 == len(argument)))
    return ParsedOption()


def _node(arguments: Sequence[str]) -> InterpreterInvocation:
    index = 0
    while index < len(arguments):
        boundary = _external_boundary(arguments, index)
        if boundary is not None:
            return boundary
        argument = arguments[index]
        inline = _node_source_option(argument, _following_operand(arguments, index))
        if inline is not None:
            return inline
        index += 2 if argument in _NODE_VALUE_FLAGS or argument in {"-r", "-C"} else 1
    return InterpreterInvocation("stdin")


def _node_source_option(argument: str, following: str | None) -> InterpreterInvocation | None:
    if argument.split("=", 1)[0] in {"--eval", "--print"}:
        operand = argument.split("=", 1)[1] if "=" in argument else following
        return InterpreterInvocation("inline", operand)
    if argument.startswith("--"):
        return None
    for flag in argument[1:]:
        if flag in "ep":
            return InterpreterInvocation("inline")
        if flag in "rC":
            break
    return None


def _external_boundary(
    arguments: Sequence[str], index: int, *, plus_options: bool = False
) -> InterpreterInvocation | None:
    argument = arguments[index]
    if argument == "--":
        return InterpreterInvocation("external" if index + 1 < len(arguments) else "stdin")
    if argument == "-":
        return InterpreterInvocation("stdin")
    prefixes = ("-", "+") if plus_options else ("-",)
    return None if argument.startswith(prefixes) else InterpreterInvocation("external")


def _following_operand(arguments: Sequence[str], index: int) -> str | None:
    return arguments[index + 1] if index + 1 < len(arguments) else None


def _jq(arguments: Sequence[str]) -> InterpreterInvocation:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if (
            argument in {"-f", "--from-file"}
            or argument.startswith("--from-file=")
            or (argument.startswith("-f") and len(argument) > _SHORT_ATTACHED_LENGTH)
        ):
            return InterpreterInvocation("external")
        if argument.startswith("-") and not argument.startswith("--") and "f" in argument[1:]:
            return InterpreterInvocation("external")
        if argument == "--":
            return InterpreterInvocation("inline" if index + 1 < len(arguments) else "other")
        if not argument.startswith("-"):
            return InterpreterInvocation("inline", argument)
        index += 1 + _JQ_VALUE_FLAGS.get(argument, 0)
    return InterpreterInvocation("other")


def _awk(arguments: Sequence[str]) -> InterpreterInvocation:
    index = 0
    external = False
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-f", "--file", "-E", "--exec"}:
            external = True
            index += 2
            continue
        if argument.startswith(("--file=", "--exec=")) or (
            argument.startswith(("-f", "-E")) and len(argument) > _SHORT_ATTACHED_LENGTH
        ):
            external = True
        elif (
            argument in {"-e", "--source"}
            or argument.startswith("--source=")
            or (argument.startswith("-e") and len(argument) > _SHORT_ATTACHED_LENGTH)
        ):
            return InterpreterInvocation("inline")
        elif argument in {"-F", "-v", "--field-separator", "--assign"}:
            index += 2
            continue
        elif argument == "--":
            return InterpreterInvocation("external" if external else "inline")
        elif not argument.startswith("-"):
            return InterpreterInvocation("external" if external else "inline", argument)
        index += 1
    return InterpreterInvocation("external" if external else "other")
