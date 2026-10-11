from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
import re
import shlex
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catches bounded native analyzer failures.
from typing import TYPE_CHECKING, Final

from sarj_python_lint.interpreter_argv import UnprovableCommandError, classify_interpreter, unwrap_command

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Region,
    SourceDocument,
    ToolReport,
)

from . import shell_format
from .devops_programs import ExecutionBlock, LiteralSource, ProgramProjectionError, execution_blocks
from .devops_tools import TOOLS, NativeToolError, checked_tool
from .external import parse_shellcheck, redact_message, run_process_input
from .policy import Policy
from .shell_policy import ACTION_EXCLUSIONS, SHELLCHECK_ARGS


if TYPE_CHECKING:
    from collections.abc import Sequence


_SHELLS: Final = {"bash": "bash", "sh": "posix", "dash": "posix", "ksh": "mksh", "zsh": "zsh"}
_EXPRESSIONS: Final = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
_OTHER_INTERPRETERS: Final = frozenset({"python", "python3", "node", "ruby", "perl", "pwsh", "powershell", "cmd"})


@dataclass(frozen=True, slots=True)
class ShellBlock:
    block: ExecutionBlock
    source: str
    dialect: str


def shell_block(block: ExecutionBlock) -> ShellBlock | None:
    if block.argv:
        words = unwrap_command(block.argv)
        invocation = classify_interpreter(words)
        if invocation.kind != "shell" or invocation.payload is None:
            return None
        shell = Path(words[0]).name
        return ShellBlock(block, invocation.payload, _SHELLS[shell])
    words = unwrap_command(tuple(shlex.split(block.runtime_shell or block.interpreter)))
    if not words:
        message = "configuration execution interpreter is empty"
        raise ProgramProjectionError(message)
    shell = Path(words[0]).name
    if shell == "shell":
        shell = "bash" if block.context == "actions" else "sh"
    if shell in _OTHER_INTERPRETERS or re.fullmatch(r"python\d+(?:\.\d+)?", shell):
        return None
    if shell not in _SHELLS:
        message = f"unsupported configuration execution shell: {block.interpreter}"
        raise ProgramProjectionError(message)
    if len(words) > 1:
        return _configured_shell_block(block, words, _SHELLS[shell])
    return ShellBlock(block, block.source, _SHELLS[shell])


def _configured_shell_block(block: ExecutionBlock, words: tuple[str, ...], dialect: str) -> ShellBlock:
    arguments = tuple(word.replace("{0}", "lint-input") for word in words)
    if "{0}" not in words and block.context != "actions":
        arguments = (*arguments, block.source)
    invocation = classify_interpreter(arguments)
    if invocation.kind == "shell" and invocation.payload is not None:
        if "{0}" in words:
            message = "configured shell command template cannot be proven to execute the authored script"
            raise ProgramProjectionError(message)
        owner = block if invocation.payload == block.source else replace(block, literal=None)
        return ShellBlock(owner, invocation.payload, dialect)
    if invocation.kind != "external" or (block.context == "actions" and "{0}" not in words):
        message = "configured shell argv cannot be proven to execute the authored script"
        raise ProgramProjectionError(message)
    return ShellBlock(block, block.source, dialect)


def source_blocks(path: Path, root: Path, *, source: str | None = None) -> tuple[ShellBlock, ...]:
    relative = path.relative_to(root).as_posix()
    if source is None:
        source = path.read_bytes().decode("utf-8")
    return tuple(
        candidate
        for block in execution_blocks(relative, source)
        if (candidate := shell_block(block)) is not None and candidate.source.strip()
    )


def _mask_expression(match: re.Match[str]) -> str:
    return "".join("_" if character.isascii() and character not in "\r\n" else character for character in match[0])


def _checked_source(candidate: ShellBlock) -> str:
    return (
        _EXPRESSIONS.sub(_mask_expression, candidate.source)
        if candidate.block.context == "actions"
        else candidate.source
    )


def analyze_sources(*, root: Path, paths: Sequence[str], selected: frozenset[str]) -> tuple[ToolReport, ...]:
    root = root.resolve()
    policy = Policy.from_manifest(root, manifest.load(root))
    reports: list[ToolReport] = []
    for raw in sorted(set(paths)):
        path = Path(raw)
        path = path if path.is_absolute() else root / path
        path.resolve().relative_to(root)
        active = _selected_analyzers(root, path, selected, policy)
        if not active:
            continue
        try:
            document = SourceDocument.read(path)
            candidates = source_blocks(path, root, source=document.text)
            if not candidates:
                continue
        except (OSError, UnicodeError, ValueError, UnprovableCommandError) as error:
            reports.extend(_failed(name, error, root, path) for name in sorted(active))
            continue
        if "shellcheck" in active and not _dockerfile(path):
            reports.append(_shellcheck_report(root, path, candidates, document))
        if "shfmt" in active:
            reports.append(_format_report(root, path, candidates, document, policy))
    return tuple(reports)


def _selected_analyzers(root: Path, path: Path, selected: frozenset[str], policy: Policy) -> frozenset[str]:
    if not policy.allows_path(path):
        return frozenset()
    finding = shell_format.format_diagnostic(path=path.relative_to(root).as_posix(), source="", formatted="")
    return selected if policy.allows_rule(finding) else selected - {"shfmt"}


def _dockerfile(path: Path) -> bool:
    name = path.name.casefold()
    return name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile")


def _failed(name: str, error: BaseException, root: Path, path: Path) -> ToolReport:
    return ToolReport(
        name,
        Completion.FAILED,
        issues=(ExecutionIssue(name, "embedded-shell-failure", redact_message(f"{path}: {error}", root)),),
        file_count=1,
    )


def _shellcheck_report(
    root: Path, path: Path, candidates: tuple[ShellBlock, ...], document: SourceDocument
) -> ToolReport:
    diagnostics: list[Diagnostic] = []
    try:
        executable = _executable("shellcheck", root)
        for candidate in candidates:
            diagnostics.extend(_check_block(root, path, candidate, document, executable))
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        return _failed("shellcheck", error, root, path)
    return ToolReport(
        "shellcheck",
        Completion.COMPLETE,
        diagnostics=tuple(diagnostics),
        version=TOOLS["shellcheck"].version,
        file_count=1,
    )


def _check_block(
    root: Path, path: Path, candidate: ShellBlock, document: SourceDocument, executable: Path
) -> tuple[Diagnostic, ...]:
    if candidate.dialect == "zsh":
        message = "ShellCheck does not support zsh"
        raise ProgramProjectionError(message)
    prefix = _runtime_prefix(candidate)
    source = prefix + _checked_source(candidate)
    dialect = "sh" if candidate.dialect == "posix" else "ksh" if candidate.dialect == "mksh" else candidate.dialect
    exclusions = (f"--exclude={ACTION_EXCLUSIONS}",) if candidate.block.context == "actions" else ()
    output = run_process_input(
        (str(executable), *SHELLCHECK_ARGS, f"--shell={dialect}", *exclusions, "--", "-"), cwd=root, source=source
    )
    findings = parse_shellcheck(output.stdout, root=root, source=SourceDocument(path, source), path=path)
    if output.returncode not in {0, 1} or output.stderr.strip() or (output.returncode == 1 and not findings):
        raise NativeToolError(output.stderr.strip() or "incomplete embedded ShellCheck protocol")
    return tuple(_map_finding(item, candidate.block, document, prefix.count("\n")) for item in findings)


def _runtime_prefix(candidate: ShellBlock) -> str:
    interpreter = (
        candidate.block.interpreter
        if candidate.block.context == "actions"
        else candidate.block.runtime_shell or candidate.block.interpreter
    )
    if candidate.block.context == "actions" and interpreter == "bash":
        return "set -e\nset -o pipefail\n"
    if candidate.block.context == "actions" and interpreter in {"shell", "sh"}:
        return "set -e\n"
    words = unwrap_command(candidate.block.argv or tuple(shlex.split(interpreter)))
    if candidate.source in words[1:]:
        words = words[: words.index(candidate.source, 1)]
    prefix = (
        "set -e\n"
        if any(word.startswith("-") and not word.startswith("--") and "e" in word[1:] for word in words[1:])
        or any(left == "-o" and right == "errexit" for left, right in pairwise(words))
        else ""
    )
    if "pipefail" in words:
        prefix += "set -o pipefail\n"
    return prefix


def _map_finding(finding: Diagnostic, block: ExecutionBlock, document: SourceDocument, prefix: int = 0) -> Diagnostic:
    if finding.location.region is not None:
        region = finding.location.region
        location = Location(
            finding.location.path,
            region=Region(
                _map_position(region.start, block, document, prefix), _map_position(region.end, block, document, prefix)
            ),
        )
    elif finding.location.position is not None:
        location = Location(
            finding.location.path, position=_map_position(finding.location.position, block, document, prefix)
        )
    else:
        location = finding.location
    notes = finding.notes
    original = finding.location.region.start if finding.location.region is not None else finding.location.position
    if block.literal is None and original is not None:
        notes = (
            *notes,
            f"Embedded shell line {max(1, original.line - prefix + 1)}, column {original.character + 1}; this executable field has no literal source mapping.",
        )
    return replace(finding, location=location, notes=notes)


def _map_position(position: Position, block: ExecutionBlock, document: SourceDocument, prefix: int) -> Position:
    origin = block.literal
    if origin is not None:
        mapped = document.utf16_point(
            line=origin.line - 1 + position.line - prefix, character=origin.indent + position.character
        )
        if mapped is not None:
            return mapped
    fallback = document.point(line=block.line, column=1)
    if fallback is None:
        message = "execution block source position is outside the authored document"
        raise ProgramProjectionError(message)
    return fallback


def _format_report(
    root: Path, path: Path, candidates: tuple[ShellBlock, ...], document: SourceDocument, policy: Policy
) -> ToolReport:
    diagnostics: list[Diagnostic] = []
    try:
        executable = _executable("shfmt", root)
        for candidate in candidates:
            finding = _format_block(root, path, candidate, document, executable)
            if finding is not None and policy.allows_rule(finding):
                diagnostics.append(finding)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        return _failed("shfmt", error, root, path)
    return ToolReport(
        "shfmt", Completion.COMPLETE, diagnostics=tuple(diagnostics), version=TOOLS["shfmt"].version, file_count=1
    )


def _executable(name: str, root: Path) -> Path:
    tool = checked_tool(name, root=root)
    if tool.executable is None:
        message = f"{name} has no attested executable"
        raise NativeToolError(message)
    return tool.executable


def _format_block(
    root: Path, path: Path, candidate: ShellBlock, document: SourceDocument, executable: Path
) -> Diagnostic | None:
    source = _checked_source(candidate)
    relative = path.relative_to(root).as_posix()
    formatted = shell_format.format_source(
        source, dialect=candidate.dialect, filename=relative, executable=executable, root=root
    )
    if formatted.rstrip("\n") == source.rstrip("\n"):
        return None
    finding = _map_finding(
        shell_format.format_diagnostic(path=relative, source=source, formatted=formatted), candidate.block, document
    )
    if not fixable(candidate):
        finding = replace(finding, help="Format this embedded shell block manually or extract it to a shell file.")
    return finding


def fixable(candidate: ShellBlock) -> bool:
    return (
        candidate.block.literal is not None
        and candidate.block.literal.fixable
        and "${{" not in candidate.source
        and not candidate.block.argv
    )


def plan_fixes(root: Path, paths: Sequence[str], executable: Path) -> list[tuple[Path, str, bytes]]:
    adopted = manifest.load(root)
    if adopted is not None and "shfmt" not in adopted.enabled_capabilities:
        return []
    policy = Policy.from_manifest(root, adopted)
    pending: list[tuple[Path, str, bytes]] = []
    for raw in sorted(set(paths)):
        path = Path(raw)
        path = path if path.is_absolute() else root / path
        relative = path.resolve().relative_to(root).as_posix()
        if not policy.allows_path(path) or not policy.allows_rule(
            shell_format.format_diagnostic(path=relative, source="", formatted="")
        ):
            continue
        before = path.read_bytes()
        rewritten = _rewrite_source(root, path, before.decode("utf-8"), executable)
        if rewritten != before.decode("utf-8"):
            pending.append((path, rewritten, before))
    return pending


def _rewrite_source(root: Path, path: Path, source: str, executable: Path) -> str:
    candidates = source_blocks(path, root, source=source)
    relative = path.relative_to(root).as_posix()
    edits: list[tuple[int, int, str]] = []
    expected: dict[int, str] = {}
    for index, candidate in enumerate(candidates):
        formatted = shell_format.format_source(
            _checked_source(candidate), dialect=candidate.dialect, filename=relative, executable=executable, root=root
        )
        if fixable(candidate) and formatted.rstrip("\n") != candidate.source.rstrip("\n"):
            origin = candidate.block.literal
            if origin is None:
                message = "fixable shell block has no verified literal location"
                raise ProgramProjectionError(message)
            trailing = len(candidate.source) - len(candidate.source.rstrip("\n"))
            expected[index] = formatted.rstrip("\n") + "\n" * trailing
            edits.append((origin.start, origin.end, _render_literal(source, origin, formatted)))
    rewritten = source
    for start, end, replacement in sorted(edits, reverse=True):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    _verify_projection(relative, rewritten, candidates, expected)
    return rewritten


def _render_literal(source: str, origin: LiteralSource, formatted: str) -> str:
    body = source[origin.start : origin.end].replace("\r\n", "\n")
    trailing = len(body) - len(body.rstrip("\n"))
    return "".join(
        " " * origin.indent + line if line.strip() else line
        for line in (formatted.rstrip("\n") + "\n" * trailing).splitlines(keepends=True)
    ).replace("\n", origin.newline)


def _verify_projection(relative: str, source: str, before: tuple[ShellBlock, ...], expected: dict[int, str]) -> None:
    after = tuple(
        candidate
        for block in execution_blocks(relative, source)
        if (candidate := shell_block(block)) is not None and candidate.source.strip()
    )
    if len(after) != len(before) or any(
        item.source != expected.get(index, before[index].source) or item.dialect != before[index].dialect
        for index, item in enumerate(after)
    ):
        message = "embedded formatting did not preserve the authored YAML execution projection"
        raise ProgramProjectionError(message)
