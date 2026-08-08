"""Safe structured adapters for Ruff, BasedPyright, and trusted ESLint."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, no shell, bounded timeout.
import sys
import threading
import time
from typing import TYPE_CHECKING, Protocol

from sarj_lint_configs.libs.adoption.lifecycle import select_eslint_commands
from sarj_lint_configs.libs.diagnostics import (
    AnalyzerId,
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Position,
    Region,
    Severity,
    SourceDocument,
    ToolReport,
    TrustMode,
)

from .runner import GroupedPaths, group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import BinaryIO

    from .policy import Policy


_TIMEOUT_SECONDS = 120
_ESLINT_ERROR = 2
_MAX_STDOUT_BYTES = 16 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_READ_BYTES = 64 * 1024
_MAX_ESLINT_PROJECTS = 32
_MAX_PYTHON_PROJECTS = 32
_ANALYSIS_DEADLINE_SECONDS = 300
_SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "PATH",
        "SHELL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)


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


class OutputLimitError(OSError):
    """An analyzer exceeded the memory-safe structured-output contract."""


class ProcessRunner(Protocol):
    def __call__(self, argv: Sequence[str], *, cwd: Path) -> ProcessOutput: ...


def analyze_external(
    files: Sequence[str],
    *,
    root: Path,
    trust: TrustMode | str,
    runner: ProcessRunner | None = None,
    policy: Policy | None = None,
    capabilities: frozenset[str] | None = None,
    grouped: GroupedPaths | None = None,
) -> tuple[ToolReport, ...]:
    """Run installed analyzers; executable repository config requires explicit trust."""
    execute = run_process if runner is None else runner
    try:
        normalized_trust = TrustMode(trust)
        root, _contained, routed = _prepare_inputs(files, root, policy=policy, grouped=grouped)
    except (OSError, ValueError) as exc:
        issue = ExecutionIssue("external", "invalid-input", str(exc))
        return (ToolReport("external", Completion.FAILED, issues=(issue,)),)
    reports: list[ToolReport] = []
    if routed.python:
        if capabilities is None or "ruff" in capabilities:
            reports.append(
                _invoke(
                    "ruff",
                    _ruff_argv(routed.python),
                    cwd=root,
                    root=root,
                    runner=execute,
                    parser=parse_ruff,
                    file_count=len(routed.python),
                )
            )
        if capabilities is None or "pyright" in capabilities:
            reports.extend(
                _invoke_python_projects(
                    "basedpyright",
                    routed.python,
                    root=root,
                    runner=execute,
                    parser=parse_basedpyright,
                )
            )
    if capabilities is not None and "eslint" not in capabilities:
        eslint_commands = ()
        unowned_eslint = 0
    else:
        try:
            eslint_commands, unowned_eslint = select_eslint_commands(root, routed.typescript, label="analysis")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            message = _redact_message(f"{type(exc).__name__}: {exc}", root)
            issue = ExecutionIssue("eslint", "configuration-failure", message)
            reports.append(ToolReport("eslint", Completion.FAILED, issues=(issue,)))
            return tuple(reports)
    if unowned_eslint:
        issue = ExecutionIssue(
            "eslint",
            "coverage-missing",
            f"no TypeScript project accepts {unowned_eslint} selected JavaScript/TypeScript path(s)",
        )
        reports.append(
            ToolReport(
                "eslint",
                Completion.FAILED,
                issues=(issue,),
                analyzer_id=AnalyzerId("eslint"),
                invocation_id=InvocationId("eslint:unowned"),
                file_count=unowned_eslint,
            )
        )
    if len(eslint_commands) > _MAX_ESLINT_PROJECTS:
        issue = ExecutionIssue(
            "eslint",
            "project-limit",
            f"selected {len(eslint_commands)} ESLint projects; maximum is {_MAX_ESLINT_PROJECTS}",
        )
        reports.append(ToolReport("eslint", Completion.FAILED, issues=(issue,)))
        eslint_commands = ()
    analysis_started = time.monotonic()
    for command in eslint_commands:
        if time.monotonic() - analysis_started >= _ANALYSIS_DEADLINE_SECONDS:
            issue = ExecutionIssue("eslint", "aggregate-timeout", "ESLint aggregate analysis exceeded 300 seconds")
            reports.append(ToolReport("eslint", Completion.FAILED, issues=(issue,)))
            break
        if normalized_trust is TrustMode.SAFE:
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
                invocation_id=command.cwd.relative_to(root).as_posix() or ".",
                file_count=_argv_file_count(command.argv),
            )
        )
    if policy is None:
        return tuple(reports)
    return tuple(
        ToolReport(
            report.name,
            report.completion,
            diagnostics=policy.filter_diagnostics(report.diagnostics),
            issues=report.issues,
            analyzer_id=report.analyzer_id,
            invocation_id=report.invocation_id,
            version=report.version,
            duration_ms=report.duration_ms,
            file_count=report.file_count,
            cache_status=report.cache_status,
        )
        for report in reports
    )


def _invoke_python_projects(
    name: str,
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessRunner,
    parser: ProtocolParser,
) -> tuple[ToolReport, ...]:
    projects = _group_python_projects(files, root)
    if len(projects) > _MAX_PYTHON_PROJECTS:
        issue = ExecutionIssue(
            name,
            "project-limit",
            f"selected {len(projects)} Python projects; maximum is {_MAX_PYTHON_PROJECTS}",
        )
        return (ToolReport(name, Completion.FAILED, issues=(issue,), analyzer_id=AnalyzerId(name)),)
    reports: list[ToolReport] = []
    for project, scoped_files in projects:
        argv = ("basedpyright", "--outputjson", *scoped_files)
        project_id = project.relative_to(root).as_posix() or "."
        reports.append(
            _invoke(
                name,
                argv,
                cwd=project,
                root=root,
                runner=runner,
                parser=parser,
                invocation_id=project_id,
                file_count=len(scoped_files),
            )
        )
    return tuple(reports)


def _group_python_projects(files: Sequence[str], root: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    markers = ("pyrightconfig.json", "pyproject.toml")
    grouped: dict[Path, list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        project = _nearest_project(path.parent, root, markers)
        grouped.setdefault(project, []).append(str(path))
    return tuple(
        (project, tuple(sorted(scoped_files)))
        for project, scoped_files in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _nearest_project(start: Path, root: Path, markers: Sequence[str]) -> Path:
    current = start
    while current.is_relative_to(root):
        if any((current / marker).is_file() for marker in markers):
            return current
        if current == root:
            break
        current = current.parent
    return root


def run_process(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    executable = _analyzer_executable(argv[0])
    if executable is None:
        msg = f"required analyzer executable is missing: {argv[0]}"
        raise FileNotFoundError(msg)
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv and shell stays disabled.
        [executable, *argv[1:]],
        cwd=cwd,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
        env=_analysis_environment(),
    )
    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:  # pragma: no cover - PIPE guarantees streams.
        process.kill()
        msg = "analyzer process did not expose output pipes"
        raise OSError(msg)
    exceeded = threading.Event()
    captures: list[bytes | None] = [None, None]
    threads = (
        threading.Thread(target=_capture_stream, args=(stdout, _MAX_STDOUT_BYTES, exceeded, captures, 0), daemon=True),
        threading.Thread(target=_capture_stream, args=(stderr, _MAX_STDERR_BYTES, exceeded, captures, 1), daemon=True),
    )
    try:
        _start_capture_threads(threads)
        returncode = _wait_for_process(process, threads, exceeded, argv)
    except BaseException:
        if process.poll() is None:
            _terminate_process(process)
        try:
            _ = process.wait(timeout=5)
        except OSError, subprocess.SubprocessError:
            process.kill()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=5)
        raise
    if exceeded.is_set():
        msg = "analyzer output exceeded the 16 MiB stdout or 64 KiB stderr limit"
        raise OutputLimitError(msg)
    stdout_bytes, stderr_bytes = captures
    if stdout_bytes is None or stderr_bytes is None:  # pragma: no cover - drain threads always assign.
        msg = "analyzer process output could not be captured"
        raise OSError(msg)
    return ProcessOutput(
        returncode,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


def _analyzer_executable(name: str) -> str | None:
    """Prefer the analyzer bundled beside this isolated Python runtime."""
    environment_bin = str(Path(sys.executable).parent)
    return shutil.which(name, path=environment_bin) or shutil.which(name)


def _analysis_environment() -> dict[str, str]:
    """Keep analyzer discovery/locale while withholding caller credentials."""
    return {
        key: value
        for key, value in os.environ.items()  # ruff: ignore[banned-api] -- deliberately reduce inherited environment.
        if key in _SAFE_ENVIRONMENT_KEYS or key.startswith("LC_")
    }


def _start_capture_threads(threads: Sequence[threading.Thread]) -> None:
    for thread in threads:
        thread.start()


def _wait_for_process(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
    exceeded: threading.Event,
    argv: Sequence[str],
) -> int:
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while process.poll() is None and not exceeded.is_set():
        if time.monotonic() >= deadline:
            _terminate_process(process)
            _ = process.wait(timeout=5)
            _join_capture_threads(threads)
            raise subprocess.TimeoutExpired(argv, _TIMEOUT_SECONDS)
        time.sleep(0.01)
    if exceeded.is_set():
        _terminate_process(process)
    returncode = process.wait(timeout=5 if exceeded.is_set() else None)
    _join_capture_threads(threads)
    return returncode


def _capture_stream(
    stream: BinaryIO,
    limit: int,
    exceeded: threading.Event,
    captures: list[bytes | None],
    index: int,
) -> None:
    data = bytearray()
    try:
        while chunk := stream.read(_READ_BYTES):
            remaining = limit - len(data)
            if remaining > 0:
                data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                exceeded.set()
                break
    finally:
        stream.close()
        captures[index] = bytes(data)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:  # pragma: no cover - Windows CI covers the process-tree strategy.
        try:
            taskkill = shutil.which("taskkill")
            if taskkill is None:
                msg = "taskkill is unavailable"
                raise FileNotFoundError(msg)
            subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- resolved system binary, fixed argv.
                (taskkill, "/PID", str(process.pid), "/T", "/F"),
                check=False,
                capture_output=True,
                shell=False,
                timeout=5,
            )
        except OSError, subprocess.SubprocessError:
            process.kill()
        if process.poll() is None:
            process.kill()


def _join_capture_threads(threads: Sequence[threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        msg = "analyzer output streams did not close after process termination"
        raise OSError(msg)


def _invoke(
    name: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    runner: ProcessRunner,
    parser: ProtocolParser,
    invocation_id: str | None = None,
    file_count: int,
) -> ToolReport:
    started = time.monotonic()
    try:
        report = _invoke_unchecked(name, argv, cwd=cwd, root=root, runner=runner, parser=parser)
        return ToolReport(
            report.name,
            report.completion,
            diagnostics=report.diagnostics,
            issues=report.issues,
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name if invocation_id is None else f"{name}:{invocation_id}"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )
    except (OSError, TypeError, ValueError, RecursionError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        message = _redact_message(f"{type(exc).__name__}: {exc}", root)
        issue = ExecutionIssue(name, "tool-failure", message)
        return ToolReport(
            name,
            Completion.FAILED,
            issues=(issue,),
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name if invocation_id is None else f"{name}:{invocation_id}"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )


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
    if output.returncode not in {0, 1}:
        message = _redact_message(output.stderr.strip() or f"{name} exited {output.returncode}", root)
        issue = ExecutionIssue(name, "tool-failure", message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    diagnostics = parser(output.stdout, root=root)
    if output.returncode == 1 and not diagnostics:
        message = _redact_message(output.stderr.strip() or f"{name} exited 1 but reported no diagnostics", root)
        issue = ExecutionIssue(name, "protocol-mismatch", message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
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
                _redact_message(_text(item, "message"), root),
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
                _redact_message(_text(item, "message"), root),
                _severity_text(_text(item, "severity")),
                "basedpyright",
                Location(_relative(path, root), region=Region(start, end)),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def parse_eslint(  # ruff: ignore[too-many-locals] -- protocol normalization keeps each ESLint field explicit.
    payload: str, *, root: Path
) -> tuple[Diagnostic, ...]:
    values = _array(_loads(payload), "ESLint output")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for value in values:
        result = _table(value, "ESLint file result")
        path = _path(result, "filePath", root)
        for raw_message in _array(result.get("messages"), "ESLint messages"):
            item = _table(raw_message, "ESLint diagnostic")
            if item.get("fatal") is True:
                detail = _text(item, "message")
                msg = f"ESLint fatal parser/configuration failure: {detail}"
                raise ValueError(msg)
            start = _eslint_start_position(item, path, documents)
            end = (
                None
                if start is None
                else _eslint_position(item, path, documents, line_key="endLine", column_key="endColumn")
            )
            rule_value = item.get("ruleId")
            rule = rule_value if isinstance(rule_value, str) else "eslint/file"
            relative_path = _relative(path, root)
            if start is None:
                location = Location(relative_path)
            elif end is not None:
                location = Location(relative_path, region=Region(start, end))
            else:
                location = Location(relative_path, position=start)
            severity_value = item.get("severity")
            if type(severity_value) is int and severity_value == _ESLINT_ERROR:
                severity = Severity.ERROR
            elif type(severity_value) is int and severity_value == 1:
                severity = Severity.WARNING
            else:
                msg = f"unsupported ESLint severity: {severity_value!r}"
                raise ValueError(msg)
            diagnostics.append(
                Diagnostic(
                    rule,
                    _redact_message(_text(item, "message"), root),
                    severity,
                    "eslint",
                    location,
                    rule_id=rule,
                )
            )
    return tuple(diagnostics)


def _ruff_argv(files: Sequence[str]) -> tuple[str, ...]:
    return ("ruff", "check", "--output-format", "json", "--", *files)


def _eslint_json_argv(argv: Sequence[str]) -> tuple[str, ...]:
    values = list(argv)
    index = values.index("--") if "--" in values else len(values)
    values[index:index] = ["--format", "json", "--no-warn-ignored"]
    return tuple(values)


def _argv_file_count(argv: Sequence[str]) -> int:
    """Count selected file arguments without mistaking flags for files."""
    if "--" not in argv:
        return 0
    return len(argv) - argv.index("--") - 1


def _loads(payload: str) -> object:
    if not payload.strip():
        msg = "analyzer returned empty structured output"
        raise ValueError(msg)
    return json.loads(payload)  # pyright: ignore[reportAny] -- narrowed immediately.


def _prepare_inputs(
    files: Sequence[str],
    root: Path,
    *,
    policy: Policy | None = None,
    grouped: GroupedPaths | None = None,
) -> tuple[Path, tuple[str, ...], GroupedPaths]:
    repository = root.resolve()
    contained = tuple(_contained_path(item, repository) for item in files)
    selected = contained if policy is None else policy.filter_paths(contained)
    return repository, selected, grouped if grouped is not None else group_paths(selected, policy=policy)


def _contained_path(value: str, root: Path) -> str:
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        msg = "analysis path is outside the repository root"
        raise ValueError(msg) from exc
    return str(resolved)


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
    if type(value) is not int:
        msg = f"{key} must be an integer"
        raise TypeError(msg)
    return value


def _path(table: dict[str, object], key: str, root: Path) -> Path:
    path = Path(_text(table, key))
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        msg = "analyzer reported a path outside the repository root"
        raise ValueError(msg) from exc
    return resolved


def _document(path: Path, cache: dict[Path, SourceDocument | None]) -> SourceDocument:
    resolved = path.resolve()
    if resolved not in cache:
        cache[resolved] = SourceDocument.read(resolved)
    document = cache[resolved]
    if document is None:
        msg = "cannot read analyzer source"
        raise OSError(msg)
    return document


def _one_based_position(value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]) -> Position:
    position = _document(path, cache).point(line=_integer(value, "row"), column=_integer(value, "column"))
    if position is None:
        msg = "analyzer position is outside source"
        raise ValueError(msg)
    return position


def _zero_based_position(value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]) -> Position:
    position = _document(path, cache).utf16_point(line=_integer(value, "line"), character=_integer(value, "character"))
    if position is None:
        msg = "analyzer position is outside source"
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
    if type(line) is not int or type(column) is not int:
        return None
    try:
        return _zero_based_position({"line": line - 1, "character": column - 1}, path, cache)
    except ValueError:
        return None


def _eslint_start_position(
    value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]
) -> Position | None:
    if isinstance(value.get("line"), bool) or isinstance(value.get("column"), bool):
        msg = "ESLint diagnostic has invalid boolean coordinates"
        raise TypeError(msg)
    if value.get("line") == 0:
        return None
    return _eslint_position(value, path, cache, line_key="line", column_key="column")


def _severity_text(value: str) -> Severity:
    try:
        severity = _ExternalSeverity(value)
    except ValueError as exc:
        msg = f"unsupported BasedPyright severity: {value!r}"
        raise ValueError(msg) from exc
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
    except ValueError as exc:
        msg = "analyzer reported a path outside the repository root"
        raise ValueError(msg) from exc


def _redact_message(value: str, root: Path) -> str:
    message = value.replace(str(root), ".")
    message = re.sub(r"(?i)\b(token|secret|password|api[_-]?key)=\S+", r"\1=<redacted>", message)
    message = re.sub(r"(?i)\b(authorization\s*:\s*bearer)\s+\S+", r"\1 <redacted>", message)
    message = re.sub(
        r"(?i)\b((?:aws|azure|gcp|github)?[_-]?(?:access[_-]?key|secret[_-]?access[_-]?key))\s+\S+",
        r"\1 <redacted>",
        message,
    )
    message = re.sub(r"(?<![\w:./])/(?:[^\s:]+/?)+", "<path>", message)
    message = re.sub(r"\b[A-Za-z]:\\[^\s]+", "<path>", message)
    return message[:1024]
