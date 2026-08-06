"""Safe structured adapters for Ruff, BasedPyright, and trusted ESLint."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, no shell, bounded timeout.
from typing import TYPE_CHECKING, Protocol

from sarj_lint_configs.libs.adoption.lifecycle import selected_eslint_commands
from sarj_lint_configs.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Region,
    Severity,
    SourceDocument,
    ToolReport,
    TrustMode,
)

from .runner import group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence


_TIMEOUT_SECONDS = 120
_ESLINT_ERROR = 2


class _ExternalSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    """Captured external analyzer output."""

    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    def __call__(self, argv: Sequence[str], *, cwd: Path) -> ProcessOutput: ...


def analyze_external(
    files: Sequence[str],
    *,
    root: Path,
    trust: TrustMode,
    runner: ProcessRunner | None = None,
) -> tuple[ToolReport, ...]:
    """Run installed analyzers; executable repository config requires explicit trust."""
    execute = run_process if runner is None else runner
    grouped = group_paths(files)
    reports: list[ToolReport] = []
    if grouped.python:
        reports.extend(
            (
                _invoke(
                    "ruff",
                    _ruff_argv(grouped.python),
                    cwd=root,
                    root=root,
                    runner=execute,
                    parser=parse_ruff,
                ),
                _invoke(
                    "basedpyright",
                    ("basedpyright", "--outputjson", *grouped.python),
                    cwd=root,
                    root=root,
                    runner=execute,
                    parser=parse_basedpyright,
                ),
            )
        )
    eslint_commands = selected_eslint_commands(root, files, label="analysis")
    for command in eslint_commands:
        if trust is TrustMode.SAFE:
            issue = ExecutionIssue(
                "eslint",
                "trust-required",
                "ESLint config is executable repository code; retry with TrustMode.TRUSTED",
            )
            reports.append(ToolReport("eslint", Completion.FAILED, issues=(issue,)))
            continue
        reports.append(
            _invoke(
                "eslint",
                _eslint_json_argv(command.argv),
                cwd=command.cwd,
                root=root,
                runner=execute,
                parser=parse_eslint,
            )
        )
    return tuple(reports)


def run_process(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    executable = shutil.which(argv[0])
    if executable is None:
        msg = f"required analyzer executable is missing: {argv[0]}"
        raise FileNotFoundError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv and shell stays disabled.
        [executable, *argv[1:]],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return ProcessOutput(completed.returncode, completed.stdout, completed.stderr)


def _invoke(
    name: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    runner: ProcessRunner,
    parser: ProtocolParser,
) -> ToolReport:
    try:
        return _invoke_unchecked(name, argv, cwd=cwd, root=root, runner=runner, parser=parser)
    except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        issue = ExecutionIssue(name, "tool-failure", f"{type(exc).__name__}: {exc}")
        return ToolReport(name, Completion.FAILED, issues=(issue,))


def _invoke_unchecked(
    name: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    runner: ProcessRunner,
    parser: ProtocolParser,
) -> ToolReport:
    output = runner(argv, cwd=cwd)
    if output.returncode > 1:
        message = output.stderr.strip() or f"{name} exited {output.returncode}"
        issue = ExecutionIssue(name, "tool-failure", message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    diagnostics = parser(output.stdout, root=root)
    return ToolReport(name, Completion.COMPLETE, diagnostics=diagnostics)


class ProtocolParser(Protocol):
    def __call__(self, payload: str, *, root: Path) -> tuple[Diagnostic, ...]: ...


def parse_ruff(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    values = _array(_loads(payload), "Ruff output")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for value in values:
        item = _table(value, "Ruff diagnostic")
        path = _path(item, "filename", root)
        start = _one_based_position(_table(item.get("location"), "Ruff location"), path, documents)
        end_value = item.get("end_location")
        end = _one_based_position(_table(end_value, "Ruff end location"), path, documents)
        code = _text(item, "code")
        url_value = item.get("url")
        help_url = url_value if isinstance(url_value, str) else None
        diagnostics.append(
            Diagnostic(
                code,
                _text(item, "message"),
                Severity.ERROR,
                "ruff",
                Location(_relative(path, root), region=Region(start, end)),
                rule_id=code,
                help_url=help_url,
            )
        )
    return tuple(diagnostics)


def parse_basedpyright(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    document = _table(_loads(payload), "BasedPyright output")
    values = _array(document.get("generalDiagnostics"), "BasedPyright diagnostics")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for value in values:
        item = _table(value, "BasedPyright diagnostic")
        path = _path(item, "file", root)
        range_value = _table(item.get("range"), "BasedPyright range")
        start = _zero_based_position(_table(range_value.get("start"), "BasedPyright start"), path, documents)
        end = _zero_based_position(_table(range_value.get("end"), "BasedPyright end"), path, documents)
        rule_value = item.get("rule")
        rule = rule_value if isinstance(rule_value, str) else "basedpyright"
        diagnostics.append(
            Diagnostic(
                rule,
                _text(item, "message"),
                _severity_text(_text(item, "severity")),
                "basedpyright",
                Location(_relative(path, root), region=Region(start, end)),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def parse_eslint(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    values = _array(_loads(payload), "ESLint output")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for value in values:
        result = _table(value, "ESLint file result")
        path = _path(result, "filePath", root)
        for raw_message in _array(result.get("messages"), "ESLint messages"):
            item = _table(raw_message, "ESLint diagnostic")
            start = _required_eslint_position(item, path, documents)
            end = _eslint_position(item, path, documents, line_key="endLine", column_key="endColumn")
            rule_value = item.get("ruleId")
            rule = rule_value if isinstance(rule_value, str) else "eslint/fatal"
            location = (
                Location(_relative(path, root), region=Region(start, end))
                if end is not None
                else Location(_relative(path, root), position=start)
            )
            diagnostics.append(
                Diagnostic(
                    rule,
                    _text(item, "message"),
                    Severity.ERROR if item.get("severity") == _ESLINT_ERROR else Severity.WARNING,
                    "eslint",
                    location,
                    rule_id=rule,
                )
            )
    return tuple(diagnostics)


def _ruff_argv(files: Sequence[str]) -> tuple[str, ...]:
    return ("ruff", "check", "--output-format", "json", "--no-cache", "--", *files)


def _eslint_json_argv(argv: Sequence[str]) -> tuple[str, ...]:
    values = list(argv)
    index = values.index("--") if "--" in values else len(values)
    values[index:index] = ["--format", "json"]
    return tuple(values)


def _loads(payload: str) -> object:
    return json.loads(payload or "[]")  # pyright: ignore[reportAny] -- narrowed immediately.


def _table(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{label} must be an object"
        raise TypeError(msg)
    table: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType] -- dynamic JSON narrowed here.
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        table[key] = item
    return table


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        msg = f"{label} must be an array"
        raise TypeError(msg)
    return list(value)  # pyright: ignore[reportUnknownArgumentType] -- elements stay opaque.


def _text(table: dict[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        msg = f"{key} must be a non-empty string"
        raise TypeError(msg)
    return value


def _integer(table: dict[str, object], key: str) -> int:
    value = table.get(key)
    if not isinstance(value, int):
        msg = f"{key} must be an integer"
        raise TypeError(msg)
    return value


def _path(table: dict[str, object], key: str, root: Path) -> Path:
    path = Path(_text(table, key))
    return path if path.is_absolute() else root / path


def _document(path: Path, cache: dict[Path, SourceDocument | None]) -> SourceDocument:
    resolved = path.resolve()
    if resolved not in cache:
        cache[resolved] = SourceDocument.read(resolved)
    document = cache[resolved]
    if document is None:
        msg = f"cannot read analyzer source: {resolved}"
        raise OSError(msg)
    return document


def _one_based_position(value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]) -> Position:
    position = _document(path, cache).point(line=_integer(value, "row"), column=_integer(value, "column"))
    if position is None:
        msg = f"analyzer position is outside source: {path}"
        raise ValueError(msg)
    return position


def _zero_based_position(value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]) -> Position:
    position = _document(path, cache).utf16_point(line=_integer(value, "line"), character=_integer(value, "character"))
    if position is None:
        msg = f"analyzer position is outside source: {path}"
        raise ValueError(msg)
    return position


def _eslint_position(
    value: dict[str, object],
    path: Path,
    cache: dict[Path, SourceDocument | None],
    *,
    line_key: str,
    column_key: str,
) -> Position | None:
    line = value.get(line_key)
    column = value.get(column_key)
    if not isinstance(line, int) or not isinstance(column, int):
        return None
    return _zero_based_position({"line": line - 1, "character": column - 1}, path, cache)


def _required_eslint_position(
    value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]
) -> Position:
    position = _eslint_position(value, path, cache, line_key="line", column_key="column")
    if position is None:
        msg = "ESLint diagnostic is missing its start position"
        raise TypeError(msg)
    return position


def _severity_text(value: str) -> Severity:
    try:
        severity = _ExternalSeverity(value)
    except ValueError:
        return Severity.INFO
    match severity:
        case _ExternalSeverity.ERROR:
            return Severity.ERROR
        case _ExternalSeverity.WARNING:
            return Severity.WARNING
        case _ExternalSeverity.INFORMATION:
            return Severity.INFO


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
