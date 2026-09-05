from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import partial
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, no shell, bounded timeout.
import sys
import tempfile
import threading
import time
import tomllib
from typing import TYPE_CHECKING, ClassVar, Final, Literal, NamedTuple, Protocol
import zipfile

from pathspec import PathSpec
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
import yaml

from sarj_standards.libs.adoption import manifest, packagemanager
from sarj_standards.libs.adoption.lifecycle import select_eslint_commands
from sarj_standards.libs.diagnostics import (
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

from . import mobile_tools
from .runner import GroupedPaths, group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import BinaryIO

    from .policy import Policy


class _ReactDoctorSelection(NamedTuple):
    project: Path
    projects: tuple[Path, ...]


class _PreparedInputs(NamedTuple):
    repository: Path
    selected: tuple[str, ...]
    grouped: GroupedPaths


_TIMEOUT = timedelta(minutes=15)
_ESLINT_ERROR = 2
_DETEKT_FINDINGS = 2
_MAX_STDOUT_BYTES = 16 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_MOBILE_CONFIG_BYTES = 1024 * 1024
_PACKAGED_MOBILE_CONFIGS = Path(__file__).resolve().parents[2] / "configs"
_READ_BYTES = 64 * 1024
_MAX_ESLINT_PROJECTS = 32
_MAX_PYTHON_PROJECTS = 32
_SHELLCHECK_BATCH_SIZE = 250
_SHELLCHECK_VERSION: Final = "0.11.0"
_SHELLCHECK_VERSION_RE: Final = re.compile(r"^version:\s*(?P<version>\S+)\s*$", re.MULTILINE)
_ANALYSIS_DEADLINE = timedelta(seconds=300)
_REACT_DOCTOR_MAX_DURATION = timedelta(seconds=60)
_REACT_DOCTOR_SMALL_CHANGE_MAX_FILES = 10
_REACT_DOCTOR_MEDIUM_CHANGE_MAX_FILES = 50
_REACT_DOCTOR_SOURCE_SUFFIXES = frozenset(
    {".astro", ".cjs", ".cts", ".htm", ".html", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"}
)
_ESLINT_NODE_OPTIONS: Final = "--max-old-space-size=4096"
_ESLINT_FORMATTER: Final = Path(__file__).parents[2] / "configs" / "eslint-compact-formatter.mjs"
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])
_YAML_OBJECT_ADAPTER = TypeAdapter(object)
_REACT_RUNTIME_PACKAGES = frozenset(
    {
        "@astrojs/react",
        "@vitejs/plugin-react",
        "@vitejs/plugin-react-swc",
        "expo",
        "next",
        "preact",
        "react",
        "react-dom",
        "react-native",
    }
)
_REACT_DOCTOR_METADATA_NAMES = frozenset(
    {
        "doctor.config.json",
        "bun.lock",
        "bun.lockb",
        "eslint.config.js",
        "eslint.config.cjs",
        "eslint.config.cts",
        "eslint.config.mjs",
        "eslint.config.mts",
        "eslint.config.ts",
        "jsconfig.json",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "tsconfig.json",
        "yarn.lock",
        "yarn.lock.yml",
    }
)
_JAVASCRIPT_SCAN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".next",
        ".open-next",
        ".turbo",
        ".yarn",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "out",
        "vendor",
    }
)
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


class _ReactDoctorProtocolModel(BaseModel):
    """Strictly type every React Doctor field consumed by the adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)


class _ReactDoctorFailure(_ReactDoctorProtocolModel):
    message: str = Field(min_length=1)


class _ReactDoctorDiagnostic(_ReactDoctorProtocolModel):
    file_path: str = Field(alias="filePath", min_length=1)
    plugin: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    severity: Literal["error", "warning"]
    message: str = Field(min_length=1)
    line: int = Field(ge=0)
    column: int = Field(ge=0)
    end_line: int | None = Field(default=None, alias="endLine", ge=0)
    end_column: int | None = Field(default=None, alias="endColumn", ge=0)
    url: str | None = None


class _ReactDoctorProject(_ReactDoctorProtocolModel):
    directory: str = Field(min_length=1)
    complete: bool
    diagnostics: tuple[_ReactDoctorDiagnostic, ...] = ()
    skipped_checks: tuple[object, ...] | None = Field(default=None, alias="skippedChecks")
    analyzed_file_count: int | None = Field(default=None, alias="analyzedFileCount", ge=0)
    scanned_file_count: int | None = Field(default=None, alias="scannedFileCount", ge=0)


class _ReactDoctorDiff(_ReactDoctorProtocolModel):
    base_branch: str = Field(alias="baseBranch", min_length=1)
    changed_file_count: int = Field(alias="changedFileCount", ge=0)


class _ReactDoctorReport(_ReactDoctorProtocolModel):
    schema_version: Literal[3] = Field(alias="schemaVersion")
    version: str = Field(min_length=1)
    ok: bool
    projects: tuple[_ReactDoctorProject, ...]
    diagnostics: tuple[_ReactDoctorDiagnostic, ...] = ()
    react_detected: bool | None = Field(default=None, alias="reactDetected")
    # The v3 serializer emits this field only when degradation occurred.
    baseline_degraded: bool = Field(default=False, alias="baselineDegraded")
    diff: _ReactDoctorDiff | None = None
    skipped_projects: tuple[object, ...] = Field(default=(), alias="skippedProjects")
    error: _ReactDoctorFailure | None


class _BasedPyrightPosition(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    line: int = Field(ge=0)
    character: int = Field(ge=0)


class _BasedPyrightRange(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    start: _BasedPyrightPosition
    end: _BasedPyrightPosition


class _BasedPyrightDiagnostic(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    file: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    message: str = Field(min_length=1)
    rule: str | None = None
    # BasedPyright omits the range for project-level diagnostics such as
    # reportImportCycles. Preserve those findings with a file-only location.
    range: _BasedPyrightRange | None = None


class _BasedPyrightReport(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    general_diagnostics: tuple[_BasedPyrightDiagnostic, ...] = Field(alias="generalDiagnostics")


class _ExternalSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


class _ShellCheckLevel(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    STYLE = "style"


class _ShellCheckDiagnostic(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    end_line: int = Field(alias="endLine", ge=1)
    column: int = Field(ge=1)
    end_column: int = Field(alias="endColumn", ge=1)
    level: str = Field(min_length=1)
    code: int = Field(ge=1)
    message: str = Field(min_length=1)


class _ShellCheckReport(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    comments: tuple[_ShellCheckDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class ProcessOutput:
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
    include_react_doctor: bool = False,
    react_doctor_staged: bool = False,
    force_react_doctor: bool = False,
    react_doctor_full_scan: bool = False,
    pass_on_unpruned_eslint_suppressions: bool = False,
) -> tuple[ToolReport, ...]:
    execute = run_process if runner is None else runner
    execute_eslint = _run_eslint_process if runner is None else runner
    try:
        normalized_trust = TrustMode(trust)
        root, contained, routed = _prepare_inputs(files, root, policy=policy, grouped=grouped)
    except (OSError, ValueError) as exc:
        issue = ExecutionIssue("external", "invalid-input", str(exc))
        return (ToolReport("external", Completion.FAILED, issues=(issue,)),)
    reports: list[ToolReport] = []
    if capabilities is None or "shellcheck" in capabilities:
        reports.extend(_shellcheck_reports(routed, root=root, runner=execute, attest_version=runner is None))
    try:
        reports.extend(
            _mobile_source_reports(
                routed,
                root=root,
                runner=execute,
                capabilities=capabilities,
                managed_tools=runner is None,
            )
        )
    except (OSError, TypeError, ValueError, RecursionError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        issue = ExecutionIssue("mobile-tools", "provisioning-failure", _redact_message(str(exc), root))
        reports.append(ToolReport("mobile-tools", Completion.FAILED, issues=(issue,)))
    if routed.python:
        if capabilities is None or "ruff" in capabilities:
            reports.extend(
                _invoke_ruff_projects(
                    routed.python,
                    root=root,
                    runner=execute,
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
        if time.monotonic() - analysis_started >= _ANALYSIS_DEADLINE.total_seconds():
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
        if runner is None and (issue := _missing_eslint_issue(command.cwd, root)) is not None:
            reports.append(
                ToolReport(
                    "eslint",
                    Completion.FAILED,
                    issues=(issue,),
                    analyzer_id=AnalyzerId("eslint"),
                    invocation_id=InvocationId(f"eslint:{command.cwd.relative_to(root).as_posix() or '.'}"),
                    file_count=_argv_file_count(command.argv),
                )
            )
            continue
        reports.append(
            _invoke(
                "eslint",
                _local_eslint_argv(
                    _eslint_json_argv(
                        command.argv,
                        pass_on_unpruned_suppressions=pass_on_unpruned_eslint_suppressions,
                    ),
                    command.cwd,
                    root,
                )
                if runner is None
                else _eslint_json_argv(
                    command.argv,
                    pass_on_unpruned_suppressions=pass_on_unpruned_eslint_suppressions,
                ),
                cwd=command.cwd,
                root=root,
                runner=execute_eslint,
                parser=parse_eslint,
                invocation_id=command.cwd.relative_to(root).as_posix() or ".",
                file_count=_argv_file_count(command.argv),
            )
        )
    react_selection = _selected_react_doctor_projects(
        root,
        enabled=include_react_doctor,
        has_typescript=force_react_doctor
        or bool(routed.typescript)
        or any(_is_react_doctor_metadata(Path(item)) for item in contained),
        capabilities=capabilities,
    )
    if react_selection is not None:
        react_root, react_projects = react_selection
        reports.append(
            _invoke_react_doctor(
                react_root,
                projects=react_projects,
                root=root,
                runner=execute,
                use_local_binary=runner is None,
                file_count=max(len(routed.typescript), 1),
                staged=react_doctor_staged,
                full_scan=react_doctor_full_scan,
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


def _mobile_source_reports(
    grouped: GroupedPaths,
    *,
    root: Path,
    runner: ProcessRunner,
    capabilities: frozenset[str] | None,
    managed_tools: bool,
) -> tuple[ToolReport, ...]:
    def enabled(name: str) -> bool:
        return capabilities is not None and name in capabilities

    reports: list[ToolReport] = []
    swift_files = _mobile_language_paths(root, grouped.swift, language="swift")
    kotlin_files = _mobile_language_paths(root, grouped.kotlin, language="kotlin")
    if swift_files and enabled("swiftformat"):
        swift_root = _mobile_capability_root(root, "swiftformat")
        config = (
            _PACKAGED_MOBILE_CONFIGS / "swiftformat.strict"
            if managed_tools
            else _first_existing(swift_root, (".swiftformat", "swiftformat.strict"))
        )
        argv = (*_swift_command(root, "swiftformat", managed=managed_tools), "--lint", "--strict")
        if config is not None:
            argv = (*argv, "--config", str(config))
        reports.append(
            _invoke_text_tool(
                "swiftformat",
                (*argv, *swift_files),
                cwd=root,
                root=root,
                runner=runner,
                parser=parse_swiftformat,
                finding_codes=frozenset({1}),
                file_count=len(swift_files),
            )
        )
    if swift_files and enabled("swiftlint"):
        swift_root = _mobile_capability_root(root, "swiftlint")
        config = (
            _PACKAGED_MOBILE_CONFIGS / "swiftlint.strict.yml"
            if managed_tools
            else _first_existing(swift_root, (".swiftlint.yml", ".swiftlint.yaml", "swiftlint.strict.yml"))
        )
        argv = (*_swift_command(root, "swiftlint", managed=managed_tools), "lint", "--strict", "--reporter", "json")
        if config is not None:
            argv = (*argv, "--config", str(config))
        reports.append(
            _invoke_text_tool(
                "swiftlint",
                (*argv, *swift_files),
                cwd=root,
                root=root,
                runner=runner,
                parser=parse_swiftlint,
                finding_codes=frozenset({1, 2}),
                file_count=len(swift_files),
                empty_payload="[]",
            )
        )
    if kotlin_files and enabled("ktlint"):
        kotlin_root = _mobile_capability_root(root, "ktlint")
        editorconfig = (
            _PACKAGED_MOBILE_CONFIGS / "ktlint.strict.editorconfig"
            if managed_tools
            else _first_existing(kotlin_root, (".editorconfig", "ktlint.strict.editorconfig"))
        )
        editorconfig_arg = () if editorconfig is None else (f"--editorconfig={editorconfig}",)
        reports.append(
            _invoke_text_tool(
                "ktlint",
                (
                    *_mobile_command("ktlint", managed=managed_tools),
                    "--log-level=none",
                    "--relative",
                    "--reporter=json",
                    *editorconfig_arg,
                    *kotlin_files,
                ),
                cwd=root,
                root=root,
                runner=runner,
                parser=parse_ktlint,
                finding_codes=frozenset({1}),
                file_count=len(kotlin_files),
                empty_payload="[]",
            )
        )
    if kotlin_files and enabled("detekt"):
        kotlin_root = _mobile_capability_root(root, "detekt")
        config = (
            _PACKAGED_MOBILE_CONFIGS / "detekt.strict.yml"
            if managed_tools
            else _first_existing(kotlin_root, ("config/detekt/detekt.yml", ".detekt.yml", "detekt.yml"))
        )
        if any("," in path for path in kotlin_files):
            issue = ExecutionIssue(
                "detekt", "invalid-input", "Detekt cannot safely accept a selected path containing a comma"
            )
            reports.append(ToolReport("detekt", Completion.FAILED, issues=(issue,)))
            return tuple(reports)
        inputs = ",".join(kotlin_files)
        detekt_argv = (*_mobile_command("detekt", managed=managed_tools), "--input", inputs, "--base-path", str(root))
        if config is not None:
            detekt_argv = (*detekt_argv, "--config", str(config))
        reports.append(
            _invoke_detekt(
                detekt_argv,
                cwd=root,
                root=root,
                runner=runner,
                file_count=len(kotlin_files),
            )
        )
    mobile_files = (*kotlin_files, *swift_files)
    if mobile_files and enabled("mobile-security"):
        config = (
            _PACKAGED_MOBILE_CONFIGS / "mobsf.strict.yml"
            if managed_tools
            else _first_existing(root, (".mobsf", "mobsf.strict.yml"))
        )
        rules = mobile_tools.mobsf_rules() if managed_tools else Path("mobsfscan-rules")
        argv = _mobsfscan_argv(rules, config=config)

        def parse_mobile_security(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
            return parse_mobsfscan(payload, root=root, expected_paths=mobile_files)

        reports.append(
            _invoke_text_tool(
                "mobsfscan",
                (*argv, "--", *mobile_files),
                cwd=root,
                root=root,
                runner=runner,
                parser=parse_mobile_security,
                finding_codes=frozenset(),
                file_count=len(mobile_files),
            )
        )
    return tuple(reports)


def _first_existing(root: Path, names: Sequence[str]) -> Path | None:
    return next((root / name for name in names if (root / name).is_file()), None)


def _mobile_capability_root(root: Path, capability: str) -> Path:
    adopted = manifest.load(root)
    if adopted is None:
        return root
    if capability in {"swiftformat", "swiftlint"}:
        return (root / adopted.swift_dest).resolve()
    if capability in {"detekt", "ktlint"}:
        return (root / adopted.kotlin_dest).resolve()
    return root


def _mobile_language_paths(
    root: Path,
    paths: Sequence[str],
    *,
    language: Literal["swift", "kotlin"],
) -> tuple[str, ...]:
    adopted = manifest.load(root)
    if adopted is None:
        return tuple(paths)
    destination = adopted.swift_dest if language == "swift" else adopted.kotlin_dest
    scope = (root / destination).resolve()
    return tuple(path for path in paths if Path(path).resolve().is_relative_to(scope))


def _mobile_command(name: Literal["detekt", "ktlint"], *, managed: bool) -> tuple[str, ...]:
    return mobile_tools.command(name) if managed else (name,)


def _mobsfscan_argv(rules: Path, *, config: Path | None) -> tuple[str, ...]:
    argv = (
        "semgrep",
        "scan",
        "--metrics=off",
        "--disable-version-check",
        "--disable-nosem",
        "--no-git-ignore",
        "--max-target-bytes=2097152",
        "--quiet",
        "--no-rewrite-rule-ids",
        "--json",
        "--config",
        str(rules),
    )
    if config is None:
        return (*argv, "--severity", "WARNING", "--severity", "ERROR")
    raw = _YAML_OBJECT_ADAPTER.validate_python(yaml.safe_load(_read_mobile_config(config)))
    entries = _array(raw, "mobsfscan config")
    if len(entries) != 1:
        msg = "mobsfscan config must contain exactly one mapping"
        raise ValueError(msg)
    settings = _table(entries[0], "mobsfscan config entry")
    severities = _mobsfscan_string_list(settings.get("severity-filter"), "severity-filter")
    if not {"WARNING", "ERROR"} <= set(severities) or not set(severities) <= {"INFO", "WARNING", "ERROR"}:
        msg = "mobsfscan severity-filter must contain both WARNING and ERROR"
        raise ValueError(msg)
    for severity in severities:
        argv = (*argv, "--severity", severity)
    ignored_rules = _mobsfscan_string_list(settings.get("ignore-rules", []), "ignore-rules")
    if ignored_rules:
        msg = "mobsfscan ignore-rules must remain empty; use reviewed manifest exclusions"
        raise ValueError(msg)
    ignored_paths = (
        *_mobsfscan_string_list(settings.get("ignore-paths", []), "ignore-paths"),
        *_mobsfscan_string_list(settings.get("ignore-filenames", []), "ignore-filenames"),
    )
    for path in ignored_paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            msg = f"mobsfscan exclusion must be repository-relative: {path!r}"
            raise ValueError(msg)
        argv = (*argv, "--exclude", path)
    overrides = _table(settings.get("severity-overrides", {}), "severity-overrides")
    if overrides:
        msg = "mobsfscan severity-overrides are not supported by the managed Semgrep adapter"
        raise ValueError(msg)
    return argv


def _mobsfscan_string_list(value: object, label: str) -> tuple[str, ...]:
    values = _array(value, f"mobsfscan {label}")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        msg = f"mobsfscan {label} must contain non-empty strings"
        raise ValueError(msg)
    return tuple(item for item in values if isinstance(item, str))


def _read_mobile_config(path: Path) -> str:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        msg = f"mobile security config is not a regular file: {path.name}"
        raise OSError(msg)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_MOBILE_CONFIG_BYTES + 1)
    if len(payload) > _MAX_MOBILE_CONFIG_BYTES:
        msg = f"mobile security config exceeds {_MAX_MOBILE_CONFIG_BYTES} bytes"
        raise OutputLimitError(msg)
    return payload.decode("utf-8")


def _swift_command(root: Path, executable: Literal["swiftformat", "swiftlint"], *, managed: bool) -> tuple[str, ...]:
    mintfile = (
        _PACKAGED_MOBILE_CONFIGS / "Mintfile.mobile.strict"
        if managed
        else _first_existing(root, ("Mintfile.mobile.strict", "Mintfile"))
    )
    if mintfile is not None:
        mint = mobile_tools.command("mint") if managed else ("mint",)
        return (*mint, "run", "--silent", "--mintfile", str(mintfile), executable)
    return (executable,)


def _invoke_text_tool(
    name: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    runner: ProcessRunner,
    parser: ProtocolParser,
    finding_codes: frozenset[int],
    file_count: int,
    fatal_codes: frozenset[int] = frozenset(),
    empty_payload: str = "",
) -> ToolReport:
    started = time.monotonic()
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary normalizes process failures and diagnostics.
        output = runner(argv, cwd=cwd)
        if output.returncode in fatal_codes or output.returncode not in {0, *finding_codes}:
            message = _redact_message(output.stderr.strip() or f"{name} exited {output.returncode}", root)
            issue = ExecutionIssue(name, "tool-failure", message, output.returncode)
            return ToolReport(name, Completion.FAILED, issues=(issue,))
        payload = output.stdout.strip() or empty_payload
        if not payload:
            diagnostics: tuple[Diagnostic, ...] = ()
        else:
            diagnostics = parser(payload, root=root)
        if output.returncode in finding_codes and not diagnostics:
            message = _redact_message(output.stderr.strip() or f"{name} reported findings without diagnostics", root)
            issue = ExecutionIssue(name, "protocol-mismatch", message, output.returncode)
            return ToolReport(name, Completion.FAILED, issues=(issue,))
        return ToolReport(
            name,
            Completion.COMPLETE,
            diagnostics=diagnostics,
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )
    except (OSError, TypeError, ValueError, RecursionError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        issue = ExecutionIssue(name, "tool-failure", _redact_message(f"{type(exc).__name__}: {exc}", root))
        return ToolReport(
            name,
            Completion.FAILED,
            issues=(issue,),
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )


def _invoke_detekt(
    argv: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    runner: ProcessRunner,
    file_count: int,
) -> ToolReport:
    started = time.monotonic()
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary owns report lifecycle and protocol checks.
        with tempfile.TemporaryDirectory(prefix="code-standards-detekt-") as temporary_directory:
            report_path = Path(temporary_directory) / "report.sarif"
            output = runner((*argv, "--report", f"sarif:{report_path}"), cwd=cwd)
            if output.returncode in {1, 3} or output.returncode not in {0, _DETEKT_FINDINGS}:
                message = _redact_message(output.stderr.strip() or f"detekt exited {output.returncode}", root)
                issue = ExecutionIssue("detekt", "tool-failure", message, output.returncode)
                return ToolReport("detekt", Completion.FAILED, issues=(issue,))
            payload = _read_bounded_report(report_path)
            diagnostics = parse_sarif(payload, root=root)
            if output.returncode == _DETEKT_FINDINGS and not diagnostics:
                message = _redact_message(
                    output.stderr.strip() or "detekt reported findings without diagnostics",
                    root,
                )
                issue = ExecutionIssue("detekt", "protocol-mismatch", message, output.returncode)
                return ToolReport("detekt", Completion.FAILED, issues=(issue,))
        return ToolReport(
            "detekt",
            Completion.COMPLETE,
            diagnostics=diagnostics,
            analyzer_id=AnalyzerId("detekt"),
            invocation_id=InvocationId("detekt"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )
    except (OSError, TypeError, ValueError, RecursionError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        issue = ExecutionIssue("detekt", "tool-failure", _redact_message(f"{type(exc).__name__}: {exc}", root))
        return ToolReport(
            "detekt",
            Completion.FAILED,
            issues=(issue,),
            analyzer_id=AnalyzerId("detekt"),
            invocation_id=InvocationId("detekt"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )


def _read_bounded_report(path: Path) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        msg = "detekt did not create its SARIF report"
        raise OSError(msg) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        msg = "detekt SARIF report is not a regular file"
        raise OSError(msg)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_STDOUT_BYTES + 1)
    if len(payload) > _MAX_STDOUT_BYTES:
        msg = f"detekt SARIF report exceeded {_MAX_STDOUT_BYTES} bytes"
        raise OutputLimitError(msg)
    return payload.decode("utf-8")


def _missing_eslint_issue(project: Path, root: Path) -> ExecutionIssue | None:
    current = project.resolve()
    repository = root.resolve()
    while True:
        if (current / ".pnp.cjs").is_file() or (current / ".pnp.loader.mjs").is_file():
            return None
        binaries = current / "node_modules" / ".bin"
        if (binaries / "eslint").is_file() or (binaries / "eslint.cmd").is_file():
            return None
        if current.parent == current:
            break
        current = current.parent
    relative = project.resolve().relative_to(repository).as_posix() or "."
    message = (
        f"ESLint is not installed locally for {relative}; node_modules/.bin/eslint is missing. "
        "Run the repository's locked package install or rerun `code-standards setup`, then retry."
    )
    return ExecutionIssue("eslint", "missing-dependency", message)


def _local_eslint_argv(argv: Sequence[str], project: Path, root: Path) -> tuple[str, ...]:
    current = project.resolve()
    while True:
        if (current / ".pnp.cjs").is_file() or (current / ".pnp.loader.mjs").is_file():
            return tuple(argv)
        binaries = current / "node_modules" / ".bin"
        binary = binaries / ("eslint.cmd" if os.name == "nt" else "eslint")
        if binary.is_file():
            try:
                tail = tuple(argv[argv.index("eslint") + 1 :])
            except ValueError as exc:
                msg = "ESLint command does not contain an eslint executable"
                raise ValueError(msg) from exc
            if os.name == "nt":
                return ("cmd.exe", "/d", "/s", "/c", str(binary), *tail)
            return (str(binary), *tail)
        if current.parent == current:
            break
        current = current.parent
    # The preflight owns the user-facing missing-dependency error. Reaching
    # this branch means the filesystem changed between preflight and launch.
    relative = project.resolve().relative_to(root.resolve()).as_posix() or "."
    msg = f"local ESLint disappeared before execution for {relative}"
    raise OSError(msg)


def _selected_react_doctor_projects(
    root: Path,
    *,
    enabled: bool,
    has_typescript: bool,
    capabilities: frozenset[str] | None,
) -> _ReactDoctorSelection | None:
    if (
        not enabled
        or not has_typescript
        or (capabilities is not None and not capabilities.intersection({"eslint", "react-doctor"}))
    ):
        return None
    adopted = manifest.load(root)
    project = _react_doctor_root(root, adopted=adopted)
    excluded = () if adopted is None else adopted.doctor_excluded_paths
    if project is None or not (projects := _react_project_roots(project, repository=root, excluded=excluded)):
        return None
    return _ReactDoctorSelection(project, projects)


def _react_doctor_root(root: Path, *, adopted: manifest.Manifest | None = None) -> Path | None:
    if adopted is None:
        adopted = manifest.load(root)
    candidate = root if adopted is None else (root / adopted.typescript_dest).resolve()
    return candidate if candidate.is_dir() else None


def _react_project_roots(
    root: Path,
    *,
    repository: Path | None = None,
    excluded: Sequence[str] = (),
) -> tuple[Path, ...]:
    repository_root = root.resolve() if repository is None else repository.resolve()
    exclusions = PathSpec.from_lines("gitignore", excluded)
    projects: list[Path] = []
    for parent, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directory = Path(parent).resolve()
        relative = directory.relative_to(repository_root).as_posix()
        if relative and exclusions.match_file(relative):
            directories[:] = []
            continue
        directories[:] = sorted(name for name in directories if name not in _JAVASCRIPT_SCAN_SKIP_DIRS)
        if "package.json" not in filenames:
            continue
        package_json = directory / "package.json"
        try:
            parsed: object = json.loads(package_json.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except OSError, ValueError:
            continue
        document = manifest.as_table(parsed)
        declared: set[str] = set()
        for field in ("dependencies", "devDependencies", "peerDependencies"):
            declared.update(manifest.table_field(document, field))
        if declared.intersection(_REACT_RUNTIME_PACKAGES):
            projects.append(directory)
    return tuple(projects)


def _is_react_doctor_metadata(path: Path) -> bool:
    name = path.name.casefold()
    if name in _REACT_DOCTOR_METADATA_NAMES:
        return True
    return name.startswith(
        (
            "astro.config.",
            "doctor.config.",
            "eslint.config.",
            "jsconfig.",
            "next.config.",
            "tsconfig.",
            "vite.config.",
        )
    )


def _invoke_react_doctor(
    project: Path,
    *,
    projects: Sequence[Path],
    root: Path,
    runner: ProcessRunner,
    use_local_binary: bool,
    file_count: int,
    staged: bool,
    full_scan: bool = False,
    allow_empty_projects: bool = False,
) -> ToolReport:
    name = "react-doctor"
    # Hooks inspect the index and CI uses the native merge-base scope. A scoped
    # baseline promotion explicitly requests a full scan so existing debt can be
    # recorded even though the rollout itself changes no React source files.
    scope_base = None if staged or full_scan else change_scope_base()
    scope_args = _react_doctor_scope_args(staged=staged, full_scan=full_scan, base=scope_base)
    if scope_base and _react_doctor_changed_scope_is_disjoint(
        projects,
        root=root,
        runner=runner,
        scope_root=project,
        reported_base=scope_base,
    ):
        project_id = project.relative_to(root).as_posix() or "."
        return ToolReport(
            name,
            Completion.COMPLETE,
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(f"{name}:{project_id}"),
            file_count=0,
        )
    if use_local_binary and (issue := _missing_local_binary_issue(name, project, root)) is not None:
        return ToolReport(
            name,
            Completion.FAILED,
            issues=(issue,),
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name),
            file_count=file_count,
        )
    install_root = packagemanager.workspace_root(project, root)
    client = packagemanager.detect(install_root)
    if staged and not full_scan:
        allow_empty_projects = allow_empty_projects or _react_doctor_scope_has_no_source(
            projects,
            root=root,
            runner=runner,
            staged=True,
        )
    duration = _react_doctor_max_duration(file_count)

    def doctor_argv(selected_scope: Sequence[str]) -> tuple[str, ...]:
        selected_duration = _REACT_DOCTOR_MAX_DURATION if tuple(selected_scope) == ("--scope", "full") else duration
        argv = packagemanager.exec_argv(
            client,
            name,
            ".",
            "--project",
            ",".join(item.relative_to(project).as_posix() or "." for item in projects),
            *selected_scope,
            "--blocking",
            "error",
            "--no-warnings",
            "--no-dead-code",
            "--no-supply-chain",
            "--no-score",
            "--no-cache",
            "--max-duration",
            str(int(selected_duration.total_seconds())),
            "--json",
            "--json-compact",
            "--no-color",
        )
        return _local_node_binary_argv(name, argv, project, root) if use_local_binary else tuple(argv)

    expected_projects = frozenset(item.resolve() for item in projects)
    argv = doctor_argv(scope_args)
    parser: ProtocolParser = partial(
        parse_react_doctor,
        expected_projects=expected_projects,
        allow_empty_projects=allow_empty_projects,
    )
    if staged and not full_scan:
        parser = partial(
            _parse_react_doctor_staged_with_full_fallback,
            expected_projects=expected_projects,
            allow_empty_projects=allow_empty_projects,
            runner=runner,
            cwd=project,
            full_argv=doctor_argv(("--scope", "full")),
        )
    elif not full_scan:
        parser = partial(
            _parse_react_doctor_changed_scope,
            expected_projects=expected_projects,
            allow_empty_projects=allow_empty_projects,
            runner=runner,
            scope_root=project,
            projects=projects,
        )
    execution_runner = runner
    if scope_base and not staged and not full_scan:
        execution_runner = _react_doctor_baseline_retry_runner(
            argv,
            root=root,
            runner=runner,
            explicit_base=scope_base,
        )
    return _invoke(
        name,
        argv,
        cwd=project,
        root=root,
        runner=execution_runner,
        parser=parser,
        invocation_id=project.relative_to(root).as_posix() or None,
        file_count=file_count,
    )


def _react_doctor_baseline_retry_runner(
    doctor_argv: Sequence[str],
    *,
    root: Path,
    runner: ProcessRunner,
    explicit_base: str,
) -> ProcessRunner:
    expected_argv = tuple(doctor_argv)
    head_before = runner(("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"), cwd=root)
    expected_head = head_before.stdout.strip()
    eligible = head_before.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", expected_head) is not None
    attempted = False

    def bounded(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal attempted
        output = runner(argv, cwd=cwd)
        if attempted or tuple(argv) != expected_argv:
            return output
        attempted = True
        if not eligible or not _retryable_react_doctor_baseline(output, explicit_base=explicit_base):
            return output
        if not _react_doctor_retry_git_state_is_safe(
            root,
            runner=runner,
            explicit_base=explicit_base,
            expected_head=expected_head,
        ):
            return output
        return runner(argv, cwd=cwd)

    return bounded


def _retryable_react_doctor_baseline(output: ProcessOutput, *, explicit_base: str) -> bool:
    if output.returncode not in {0, 1} or not output.stdout.strip():
        return False
    try:
        report = _ReactDoctorReport.model_validate_json(output.stdout)
    except ValueError:
        return False
    return (
        report.baseline_degraded
        and report.version == manifest.eslint_peers()["react-doctor"]
        and report.error is None
        and report.diff is not None
        and report.diff.base_branch == explicit_base
    )


def _react_doctor_retry_git_state_is_safe(
    root: Path,
    *,
    runner: ProcessRunner,
    explicit_base: str,
    expected_head: str,
) -> bool:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", explicit_base) is None:
        return False
    if ".." in explicit_base or "@{" in explicit_base:
        return False
    base = runner(
        ("git", "rev-parse", "--verify", "--end-of-options", f"{explicit_base}^{{commit}}"),
        cwd=root,
    )
    head = runner(("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"), cwd=root)
    resolved_base = base.stdout.strip()
    resolved_head = head.stdout.strip()
    if (
        base.returncode != 0
        or head.returncode != 0
        or re.fullmatch(r"[0-9a-f]{40}", resolved_base) is None
        or resolved_head != expected_head
    ):
        return False
    ancestor = runner(("git", "merge-base", "--is-ancestor", resolved_base, resolved_head), cwd=root)
    return ancestor.returncode == 0


def _parse_react_doctor_staged_with_full_fallback(
    payload: str,
    *,
    root: Path,
    expected_projects: frozenset[Path],
    allow_empty_projects: bool,
    runner: ProcessRunner,
    cwd: Path,
    full_argv: Sequence[str],
) -> tuple[Diagnostic, ...]:
    report = _ReactDoctorReport.model_validate_json(payload)
    if report.react_detected is not False:
        return _parse_react_doctor_report(
            report,
            root=root,
            expected_projects=expected_projects,
            allow_empty_projects=allow_empty_projects,
            include_warnings=False,
            require_react_detection=True,
        )

    # Validate every staged coverage guarantee before using a full scan to
    # recover diagnostics omitted by React Doctor's scoped project metadata.
    _parse_react_doctor_report(
        report,
        root=root,
        expected_projects=expected_projects,
        allow_empty_projects=allow_empty_projects,
        include_warnings=False,
        require_react_detection=False,
    )
    staged_paths = _react_doctor_staged_paths(root, runner=runner)
    output = runner(full_argv, cwd=cwd)
    if output.returncode not in {0, 1}:
        msg = output.stderr.strip() or f"React Doctor full fallback exited {output.returncode}"
        raise OSError(msg)
    if not output.stdout.strip():
        msg = output.stderr.strip() or "React Doctor full fallback returned empty structured output"
        raise ValueError(msg)
    diagnostics = parse_react_doctor(output.stdout, root=root, expected_projects=expected_projects)
    if output.returncode == 1 and not diagnostics:
        msg = output.stderr.strip() or "React Doctor full fallback exited 1 but reported no diagnostics"
        raise ValueError(msg)
    return tuple(item for item in diagnostics if item.location.path in staged_paths)


def _parse_react_doctor_changed_scope(
    payload: str,
    *,
    root: Path,
    expected_projects: frozenset[Path],
    allow_empty_projects: bool,
    runner: ProcessRunner,
    scope_root: Path,
    projects: Sequence[Path],
) -> tuple[Diagnostic, ...]:
    report = _ReactDoctorReport.model_validate_json(payload)
    allow_empty_projects = allow_empty_projects or _react_doctor_degraded_scope_has_no_source(
        report,
        projects=projects,
        root=root,
        runner=runner,
        scope_root=scope_root,
    )
    return _parse_react_doctor_report(
        report,
        root=root,
        expected_projects=expected_projects,
        allow_empty_projects=allow_empty_projects,
        include_warnings=False,
        require_react_detection=True,
    )


def _react_doctor_degraded_scope_has_no_source(
    report: _ReactDoctorReport,
    *,
    projects: Sequence[Path],
    root: Path,
    runner: ProcessRunner,
    scope_root: Path,
) -> bool:
    if not report.baseline_degraded or report.projects or report.diagnostics or report.diff is None:
        return False
    return _react_doctor_scope_has_no_source(
        projects,
        root=root,
        runner=runner,
        staged=False,
        scope_root=scope_root,
        reported_base=report.diff.base_branch,
        reported_changed_file_count=report.diff.changed_file_count,
    )


def _react_doctor_staged_paths(root: Path, *, runner: ProcessRunner) -> frozenset[str]:
    output = runner(
        ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--"),
        cwd=root,
    )
    if output.returncode != 0:
        msg = output.stderr.strip() or "git diff --cached failed while recovering React Doctor coverage"
        raise OSError(msg)
    paths: set[str] = set()
    for value in (item for item in output.stdout.split("\0") if item):
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            msg = f"git diff --cached returned an unsafe path: {value!r}"
            raise ValueError(msg)
        paths.add(path.as_posix())
    return frozenset(paths)


def _react_doctor_changed_scope_is_disjoint(
    projects: Sequence[Path],
    *,
    root: Path,
    runner: ProcessRunner,
    scope_root: Path,
    reported_base: str,
) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", reported_base):
        return False
    if ".." in reported_base or "@{" in reported_base:
        return False
    resolved_base_output = runner(
        ("git", "rev-parse", "--verify", "--end-of-options", f"{reported_base}^{{commit}}"),
        cwd=root,
    )
    resolved_head_output = runner(
        ("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
        cwd=root,
    )
    resolved_base = resolved_base_output.stdout.strip()
    resolved_head = resolved_head_output.stdout.strip()
    if (
        resolved_base_output.returncode != 0
        or resolved_head_output.returncode != 0
        or re.fullmatch(r"[0-9a-f]{40}", resolved_base) is None
        or re.fullmatch(r"[0-9a-f]{40}", resolved_head) is None
    ):
        return False
    ancestor = runner(("git", "merge-base", "--is-ancestor", resolved_base, resolved_head), cwd=root)
    if ancestor.returncode != 0:
        return False
    changed = runner(
        (
            "git",
            "diff",
            f"{resolved_base}...{resolved_head}",
            "--name-only",
            "--no-renames",
            "-z",
            "--",
        ),
        cwd=root,
    )
    if changed.returncode != 0:
        return False
    resolved_root = root.resolve()
    resolved_scope = scope_root.resolve()
    resolved_projects = tuple(project.resolve() for project in projects)
    if (
        not resolved_scope.is_relative_to(resolved_root)
        or not resolved_projects
        or any(
            not project.is_relative_to(resolved_root) or not project.is_relative_to(resolved_scope)
            for project in resolved_projects
        )
    ):
        return False
    for relative in (item for item in changed.stdout.split("\0") if item):
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return False
        candidate = resolved_root / relative_path
        if any(candidate.is_relative_to(project) for project in resolved_projects):
            return False
        if _is_react_doctor_metadata(candidate) and any(
            project.is_relative_to(candidate.parent) for project in resolved_projects
        ):
            return False
    status = runner(("git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--"), cwd=root)
    if status.returncode != 0 or status.stdout:
        return False
    final_head = runner(("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"), cwd=root)
    return final_head.returncode == 0 and final_head.stdout.strip() == resolved_head


def _react_doctor_max_duration(file_count: int) -> timedelta:
    if file_count <= _REACT_DOCTOR_SMALL_CHANGE_MAX_FILES:
        return timedelta(seconds=12)
    if file_count <= _REACT_DOCTOR_MEDIUM_CHANGE_MAX_FILES:
        return timedelta(seconds=20)
    return _REACT_DOCTOR_MAX_DURATION


def _react_doctor_scope_args(
    *,
    staged: bool,
    full_scan: bool = False,
    base: str | None = None,
) -> tuple[str, ...]:
    if full_scan:
        return ("--scope", "full")
    if staged:
        return ("--staged",)
    selected_base = change_scope_base() if base is None else base
    if selected_base:
        return ("--scope", "changed", "--base", selected_base)
    return ("--scope", "changed")


def _react_doctor_scope_has_no_source(
    projects: Sequence[Path],
    *,
    root: Path,
    runner: ProcessRunner,
    staged: bool,
    scope_root: Path | None = None,
    reported_base: str | None = None,
    reported_changed_file_count: int | None = None,
) -> bool:
    if staged:
        diff_args = ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
    else:
        base = reported_base or change_scope_base()
        if not base:
            return False
        if reported_base is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", base) or ".." in base or "@{" in base:
                return False
            resolved = runner(
                ("git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"),
                cwd=root,
            )
            resolved_base = resolved.stdout.strip()
            if resolved.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", resolved_base) is None:
                return False
            ancestor = runner(("git", "merge-base", "--is-ancestor", resolved_base, "HEAD"), cwd=root)
            if ancestor.returncode != 0:
                return False
            base = resolved_base
        diff_args = ("git", "diff", f"{base}...HEAD", "--name-only", "--diff-filter=ACMR", "-z", "--")
    changed = runner(
        diff_args,
        cwd=root,
    )
    if changed.returncode != 0:
        return False
    resolved_root = root.resolve()
    resolved_scope = resolved_root if scope_root is None else scope_root.resolve()
    if not resolved_scope.is_relative_to(resolved_root):
        return False
    resolved_projects = tuple(project.resolve() for project in projects)
    changed_paths = tuple(item for item in changed.stdout.split("\0") if item)
    scoped_changed_file_count = 0
    for relative in changed_paths:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return False
        # Keep containment lexical: resolving a changed symlink could move its
        # apparent path outside the React project and incorrectly waive it.
        candidate = resolved_root / relative_path
        if candidate.is_relative_to(resolved_scope):
            scoped_changed_file_count += 1
        within_project = any(candidate.is_relative_to(project) for project in resolved_projects)
        if candidate.suffix.casefold() not in _REACT_DOCTOR_SOURCE_SUFFIXES:
            continue
        if within_project:
            return False
    return reported_changed_file_count is None or scoped_changed_file_count == reported_changed_file_count


def change_scope_base() -> str:
    explicit = os.environ.get(  # ruff: ignore[banned-api] -- explicit CI workflow boundary, not application settings.
        "SARJ_STANDARDS_BASE", ""
    ).strip()
    if not explicit:
        explicit = os.environ.get(  # ruff: ignore[banned-api] -- compatibility with pre-v2 managed workflows.
            "SARJ_REACT_DOCTOR_BASE", ""
        ).strip()
    if explicit:
        return explicit
    event_path = os.environ.get(  # ruff: ignore[banned-api] -- GitHub owns this path in Actions.
        "GITHUB_EVENT_PATH", ""
    ).strip()
    if not event_path:
        return ""
    try:
        payload: object = json.loads(Path(event_path).read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except OSError, json.JSONDecodeError:
        return ""
    pull_request = manifest.as_table(manifest.as_table(payload).get("pull_request"))
    base = manifest.as_table(pull_request.get("base"))
    sha = manifest.text_field(base, "sha")
    return sha if sha is not None and re.fullmatch(r"[0-9a-f]{40}", sha) else ""


def is_non_default_github_push() -> bool:
    event_name = os.environ.get(  # ruff: ignore[banned-api] -- GitHub owns this value in Actions.
        "GITHUB_EVENT_NAME", ""
    ).strip()
    if event_name != "push":
        return False
    event_path = os.environ.get(  # ruff: ignore[banned-api] -- GitHub owns this path in Actions.
        "GITHUB_EVENT_PATH", ""
    ).strip()
    if not event_path:
        return False
    try:
        payload: object = json.loads(Path(event_path).read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except OSError, json.JSONDecodeError:
        return False
    event = manifest.as_table(payload)
    if manifest.as_table(event.get("pull_request")):
        return False
    ref = manifest.text_field(event, "ref")
    repository = manifest.as_table(event.get("repository"))
    default_branch = manifest.text_field(repository, "default_branch")
    prefix = "refs/heads/"
    return bool(ref and default_branch and ref.startswith(prefix) and ref.removeprefix(prefix) != default_branch)


def _missing_local_binary_issue(name: str, project: Path, root: Path) -> ExecutionIssue | None:
    current = project.resolve()
    repository = root.resolve()
    while current.is_relative_to(repository):
        if (current / ".pnp.cjs").is_file() or (current / ".pnp.loader.mjs").is_file():
            return None
        binaries = current / "node_modules" / ".bin"
        if (binaries / name).is_file() or (binaries / f"{name}.cmd").is_file():
            return None
        if current == repository:
            break
        current = current.parent
    relative = project.relative_to(repository).as_posix() or "."
    message = (
        f"{name} is not installed locally for {relative}; node_modules/.bin/{name} is missing. "
        "Run the repository's locked package install or rerun `code-standards setup`, then retry."
    )
    return ExecutionIssue(name, "missing-dependency", message)


def _local_node_binary_argv(name: str, argv: Sequence[str], project: Path, root: Path) -> tuple[str, ...]:
    current = project.resolve()
    repository = root.resolve()
    while current.is_relative_to(repository):
        if (current / ".pnp.cjs").is_file() or (current / ".pnp.loader.mjs").is_file():
            return tuple(argv)
        binary = current / "node_modules" / ".bin" / (f"{name}.cmd" if os.name == "nt" else name)
        if binary.is_file():
            try:
                tail = tuple(argv[argv.index(name) + 1 :])
            except ValueError as exc:
                msg = f"analyzer command does not contain {name!r}"
                raise ValueError(msg) from exc
            if os.name == "nt":
                return ("cmd.exe", "/d", "/s", "/c", str(binary), *tail)
            return (str(binary), *tail)
        if current == repository:
            break
        current = current.parent
    msg = f"local {name} disappeared before execution"
    raise OSError(msg)


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
        argv = (_project_analyzer(project, "basedpyright"), "--outputjson")
        project_id = project.relative_to(root).as_posix() or None
        report = _invoke(
            name,
            argv,
            cwd=project,
            root=root,
            runner=runner,
            parser=parser,
            invocation_id=project_id,
            file_count=len(scoped_files),
        )
        selected = frozenset(_relative(Path(path), root) for path in scoped_files)
        reports.append(
            ToolReport(
                report.name,
                report.completion,
                diagnostics=tuple(
                    diagnostic for diagnostic in report.diagnostics if diagnostic.location.path in selected
                ),
                issues=report.issues,
                analyzer_id=report.analyzer_id,
                invocation_id=report.invocation_id,
                version=report.version,
                duration_ms=report.duration_ms,
                file_count=report.file_count,
                cache_status=report.cache_status,
            )
        )
    return tuple(reports)


def _invoke_ruff_projects(
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessRunner,
) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    for project, config, scoped_files in _group_ruff_projects(files, root):
        project_id = None if project == root else project.relative_to(root).as_posix()
        reports.append(
            _invoke(
                "ruff",
                _ruff_argv(scoped_files, config=config),
                cwd=project,
                root=root,
                runner=runner,
                parser=parse_ruff,
                invocation_id=project_id,
                file_count=len(scoped_files),
            )
        )
    return tuple(reports)


def _shellcheck_reports(
    grouped: GroupedPaths, *, root: Path, runner: ProcessRunner, attest_version: bool
) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    if grouped.unsupported_shell:
        issue = ExecutionIssue(
            "shellcheck",
            "coverage-missing",
            f"ShellCheck does not support zsh; {len(grouped.unsupported_shell)} selected zsh path(s) were not analyzed",
        )
        reports.append(
            ToolReport(
                "shellcheck",
                Completion.FAILED,
                issues=(issue,),
                analyzer_id=AnalyzerId("shellcheck"),
                invocation_id=InvocationId("shellcheck:zsh"),
                file_count=len(grouped.unsupported_shell),
            )
        )
    if not grouped.shellcheck:
        return tuple(reports)
    version_issue = _shellcheck_version_issue(root) if attest_version else None
    if version_issue is not None:
        reports.append(
            ToolReport(
                "shellcheck",
                Completion.FAILED,
                issues=(version_issue,),
                analyzer_id=AnalyzerId("shellcheck"),
                invocation_id=InvocationId("shellcheck:version"),
                file_count=len(grouped.shellcheck),
            )
        )
        return tuple(reports)
    for batch_number, start in enumerate(range(0, len(grouped.shellcheck), _SHELLCHECK_BATCH_SIZE), start=1):
        batch = tuple(sorted(grouped.shellcheck[start : start + _SHELLCHECK_BATCH_SIZE]))
        reports.append(_invoke_shellcheck(batch, root=root, runner=runner, invocation_id=str(batch_number)))
    return tuple(reports)


def _invoke_shellcheck(files: Sequence[str], *, root: Path, runner: ProcessRunner, invocation_id: str) -> ToolReport:
    report = _invoke(
        "shellcheck",
        (
            "shellcheck",
            "--norc",
            "--extended-analysis=true",
            "--severity=info",
            "--source-path=SCRIPTDIR",
            "--format=json1",
            "--",
            *files,
        ),
        cwd=root,
        root=root,
        runner=runner,
        parser=parse_shellcheck,
        invocation_id=invocation_id,
        file_count=len(files),
    )
    return ToolReport(
        report.name,
        report.completion,
        diagnostics=report.diagnostics,
        issues=report.issues,
        analyzer_id=report.analyzer_id,
        invocation_id=report.invocation_id,
        version=_SHELLCHECK_VERSION,
        duration_ms=report.duration_ms,
        file_count=report.file_count,
        cache_status=report.cache_status,
    )


def _shellcheck_version_issue(root: Path) -> ExecutionIssue | None:
    try:
        output = run_process(("shellcheck", "--version"), cwd=root)
    except (OSError, subprocess.SubprocessError) as exc:
        return ExecutionIssue("shellcheck", "missing-dependency", _redact_message(str(exc), root))
    match = _SHELLCHECK_VERSION_RE.search(output.stdout)
    actual = None if match is None else match.group("version")
    if output.returncode != 0 or actual != _SHELLCHECK_VERSION:
        displayed = actual or "unknown"
        return ExecutionIssue(
            "shellcheck",
            "version-mismatch",
            f"ShellCheck {displayed} is installed; exact version {_SHELLCHECK_VERSION} is required",
            output.returncode,
        )
    return None


def _project_analyzer(project: Path, name: str) -> str:
    candidates = (
        project / ".venv" / "bin" / name,
        project / ".venv" / "Scripts" / f"{name}.exe",
    )
    return str(next((candidate for candidate in candidates if candidate.is_file()), name))


def _group_python_projects(files: Sequence[str], root: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    fallback = _adopted_python_project(root)
    grouped: dict[Path, list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        project = _nearest_analyzer_project(path.parent, root, fallback=fallback)
        grouped.setdefault(project, []).append(str(path))
    return tuple(
        (project, tuple(sorted(scoped_files)))
        for project, scoped_files in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _nearest_analyzer_project(start: Path, root: Path, *, fallback: Path | None = None) -> Path:
    configured = _nearest_configured_python_project(start, root, names=("pyright", "basedpyright"))
    if configured is not None:
        return configured
    current = start
    while current.is_relative_to(root):
        if any(
            candidate.is_file()
            for candidate in (
                current / ".venv" / "bin" / "basedpyright",
                current / ".venv" / "Scripts" / "basedpyright.exe",
            )
        ):
            return current
        if current == root:
            break
        current = current.parent
    return fallback or _nearest_project(start, root, ("pyproject.toml",))


def _group_ruff_projects(files: Sequence[str], root: Path) -> tuple[tuple[Path, Path | None, tuple[str, ...]], ...]:
    fallback = _adopted_python_config(root)
    grouped: dict[tuple[Path, Path | None], list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        config = _nearest_ruff_config(path.parent, root) or fallback
        project = root if config is None else config.parent
        grouped.setdefault((project, config), []).append(str(path))
    return tuple(
        (project, config, tuple(sorted(scoped_files)))
        for (project, config), scoped_files in sorted(grouped.items(), key=lambda item: str(item[0][0]))
    )


def _nearest_ruff_config(start: Path, root: Path) -> Path | None:
    current = start
    while current.is_relative_to(root):
        for name in (".ruff.toml", "ruff.toml"):
            candidate = current / name
            if candidate.is_file():
                return candidate
        pyproject = current / "pyproject.toml"
        if pyproject.is_file() and _pyproject_has_tool(pyproject, ("ruff",)):
            return pyproject
        if current == root:
            break
        current = current.parent
    return None


def _adopted_python_config(root: Path) -> Path | None:
    project = _adopted_python_project(root)
    return None if project is None else _nearest_ruff_config(project, root)


def _adopted_python_project(root: Path) -> Path | None:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return None
    if adopted is None:
        return None
    project = (root / adopted.python_dest).resolve()
    return project if project.is_dir() else None


def _nearest_configured_python_project(start: Path, root: Path, *, names: Sequence[str]) -> Path | None:
    current = start
    while current.is_relative_to(root):
        if (current / "pyrightconfig.json").is_file() or (current / "pyrightconfig.jsonc").is_file():
            return current
        pyproject = current / "pyproject.toml"
        if pyproject.is_file() and _pyproject_has_tool(pyproject, names):
            return current
        if current == root:
            break
        current = current.parent
    return None


def _pyproject_has_tool(path: Path, names: Sequence[str]) -> bool:
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return False
    document = manifest.as_table(parsed)
    tool = manifest.as_table(document.get("tool"))
    return any(isinstance(tool.get(name), dict) for name in names)


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
    return _run_process(argv, cwd=cwd, environment=_analysis_environment())


def _run_eslint_process(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    environment = _analysis_environment()
    environment["NODE_OPTIONS"] = _ESLINT_NODE_OPTIONS
    return _run_process(argv, cwd=cwd, environment=environment)


def _run_process(argv: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> ProcessOutput:
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
        env=environment,
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
    environment_bin = str(Path(sys.executable).parent)
    return shutil.which(name, path=environment_bin) or shutil.which(name)


def _analysis_environment() -> dict[str, str]:
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
    deadline = time.monotonic() + _TIMEOUT.total_seconds()
    while process.poll() is None and not exceeded.is_set():
        if time.monotonic() >= deadline:
            _terminate_process(process)
            _ = process.wait(timeout=5)
            _join_capture_threads(threads)
            raise subprocess.TimeoutExpired(argv, _TIMEOUT.total_seconds())
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
    if not output.stdout.strip():
        stderr = output.stderr.strip()
        kind = "tool-failure" if stderr else "protocol-mismatch"
        message = _redact_message(stderr or f"{name} returned empty structured output", root)
        issue = ExecutionIssue(name, kind, message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    try:
        diagnostics = parser(output.stdout, root=root)
    except json.JSONDecodeError as exc:
        stderr = output.stderr.strip()
        message = stderr or f"{name} returned invalid structured JSON at line {exc.lineno}, column {exc.colno}"
        issue = ExecutionIssue(name, "protocol-mismatch", _redact_message(message, root), output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
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


_SWIFTFORMAT_LINE: Final = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<column>\d+))?:\s*(?:warning|error):\s*"
    r"(?P<message>.*?)(?:\s+\((?P<rule>[^()]+)\))?$"
)


def parse_swiftformat(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    documents: dict[Path, SourceDocument | None] = {}
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("Running SwiftFormat", "SwiftFormat completed")):
            continue
        match = _SWIFTFORMAT_LINE.fullmatch(line)
        if match is None:
            msg = f"unsupported SwiftFormat diagnostic: {line!r}"
            raise ValueError(msg)
        path = _reported_path(match.group("file"), root)
        position = _one_based_position(
            {"row": int(match.group("line")), "column": int(match.group("column") or "1")},
            path,
            documents,
        )
        rule = match.group("rule") or "format"
        diagnostics.append(
            Diagnostic(
                rule,
                _redact_message(match.group("message"), root),
                Severity.ERROR,
                "swiftformat",
                Location(_relative(path, root), position=position),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def parse_swiftlint(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    values = _array(_loads(payload), "SwiftLint output")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for value in values:
        item = _table(value, "SwiftLint diagnostic")
        path = _reported_path(_text(item, "file"), root)
        line = _positive_int(item, "line")
        column = 1 if item.get("character") is None else _positive_int(item, "character")
        position = _one_based_position({"row": line, "column": column}, path, documents)
        rule = _text(item, "rule_id")
        raw_severity = _text(item, "severity").casefold()
        try:
            severity_value = _ExternalSeverity(raw_severity)
        except ValueError as exc:
            msg = f"unsupported SwiftLint severity: {raw_severity!r}"
            raise ValueError(msg) from exc
        if severity_value is _ExternalSeverity.ERROR:
            severity = Severity.ERROR
        elif severity_value is _ExternalSeverity.WARNING:
            severity = Severity.WARNING
        else:
            msg = f"unsupported SwiftLint severity: {raw_severity!r}"
            raise ValueError(msg)
        diagnostics.append(
            Diagnostic(
                rule,
                _redact_message(_text(item, "reason"), root),
                severity,
                "swiftlint",
                Location(_relative(path, root), position=position),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def parse_ktlint(  # ruff: ignore[too-many-locals] -- protocol normalization keeps every untyped field explicit.
    payload: str, *, root: Path
) -> tuple[Diagnostic, ...]:
    decoded = _loads(payload)
    records = _array(decoded, "ktlint output")
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for record in records:
        result = _table(record, "ktlint file result")
        path_value = result.get("file") or result.get("filePath")
        if not isinstance(path_value, str) or not path_value:
            msg = "ktlint file result must contain file or filePath"
            raise TypeError(msg)
        path = _reported_path(path_value, root)
        raw_errors = result.get("errors")
        errors = _array(raw_errors, "ktlint errors") if raw_errors is not None else (result,)
        for raw_error in errors:
            item = _table(raw_error, "ktlint diagnostic")
            line = _positive_int(item, "line")
            column = _positive_int(item, "column", default=1)
            position = _one_based_position({"row": line, "column": column}, path, documents)
            rule_value = item.get("rule") or item.get("ruleId")
            rule = rule_value if isinstance(rule_value, str) and rule_value else "ktlint"
            message_value = item.get("message") or item.get("detail")
            if not isinstance(message_value, str) or not message_value:
                msg = "ktlint diagnostic must contain a message"
                raise TypeError(msg)
            diagnostics.append(
                Diagnostic(
                    rule,
                    _redact_message(message_value, root),
                    Severity.ERROR,
                    "ktlint",
                    Location(_relative(path, root), position=position),
                    rule_id=rule,
                )
            )
    return tuple(diagnostics)


def parse_mobsfscan(  # ruff: ignore[too-many-locals] -- protocol normalization keeps untyped fields explicit.
    payload: str, *, root: Path, expected_paths: Sequence[str] | None = None
) -> tuple[Diagnostic, ...]:
    report = _JSON_OBJECT_ADAPTER.validate_json(payload, strict=True)
    errors = _array(report.get("errors", []), "mobsfscan errors")
    if expected_paths is not None:
        paths = _table(report.get("paths"), "mobsfscan paths")
        scanned_values = _array(paths.get("scanned"), "mobsfscan scanned paths")
        if any(not isinstance(value, str) or not value for value in scanned_values):
            msg = "mobsfscan scanned paths must contain non-empty strings"
            raise TypeError(msg)
        scanned = {_reported_path(value, root) for value in scanned_values if isinstance(value, str)}
        expected = {Path(value).resolve() for value in expected_paths}
        if scanned != expected:
            msg = f"mobsfscan coverage mismatch: expected {len(expected)} selected file(s), scanned {len(scanned)}"
            raise ValueError(msg)
    # Semgrep 1.175.0 does not yet parse Swift's `#Preview` macro. It reports a
    # warning-only PartialParsing record while still scanning the complete file.
    # Permit only that exact, known parser limitation and only when the caller
    # requested and proved exact selected-file coverage above. Every other
    # engine error remains fatal.
    tolerated_partial_parsing = expected_paths is not None and all(
        _is_tolerated_swift_partial_parsing(raw_error) for raw_error in errors
    )
    if errors and not tolerated_partial_parsing:
        msg = f"mobsfscan Semgrep engine reported {len(errors)} error(s)"
        raise ValueError(msg)
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for raw_result in _array(report.get("results"), "mobsfscan results"):
        result = _table(raw_result, "mobsfscan result")
        rule = _text(result, "check_id")
        path = _reported_path(_text(result, "path"), root)
        start = _table(result.get("start"), "mobsfscan start")
        line = _positive_int(start, "line", default=1)
        column = _positive_int(start, "col", default=1)
        position = _one_based_position({"row": line, "column": column}, path, documents)
        extra = _table(result.get("extra"), "mobsfscan extra")
        severity_value = _text(extra, "severity")
        match severity_value:
            case "ERROR":
                severity = Severity.ERROR
            case "WARNING":
                severity = Severity.WARNING
            case _:
                msg = f"unsupported mobsfscan severity: {severity_value!r}"
                raise ValueError(msg)
        diagnostics.append(
            Diagnostic(
                rule,
                _redact_message(_text(extra, "message"), root),
                severity,
                "mobsfscan",
                Location(_relative(path, root), position=position),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def _is_tolerated_swift_partial_parsing(value: object) -> bool:
    try:
        error = _table(value, "mobsfscan error")
    except TypeError:
        return False
    error_type = error.get("type")
    message = error.get("message")
    if not isinstance(error_type, list):
        return False
    fields = _array(error.get("type"), "mobsfscan error type")
    return (
        fields[:1] == ["PartialParsing"]
        and len(fields[1:]) == 1
        and isinstance(fields[1], list)
        and error.get("level") == "warn"
        and isinstance(message, str)
        and bool(message)
    )


def parse_sarif(  # ruff: ignore[too-many-locals] -- protocol normalization keeps SARIF containment explicit.
    payload: str, *, root: Path
) -> tuple[Diagnostic, ...]:
    report = _JSON_OBJECT_ADAPTER.validate_json(payload, strict=True)
    diagnostics: list[Diagnostic] = []
    documents: dict[Path, SourceDocument | None] = {}
    for raw_run in _array(report.get("runs"), "SARIF runs"):
        run = _table(raw_run, "SARIF run")
        for raw_result in _array(run.get("results", []), "SARIF results"):
            result = _table(raw_result, "SARIF result")
            rule = _text(result, "ruleId")
            message_table = _table(result.get("message"), "SARIF message")
            message = _text(message_table, "text")
            level = result.get("level")
            if level == "error":
                severity = Severity.ERROR
            elif level in {None, "warning", "note", "none"}:
                severity = Severity.WARNING
            else:
                msg = f"unsupported SARIF severity: {level!r}"
                raise ValueError(msg)
            locations = _array(result.get("locations"), "SARIF locations")
            if not locations:
                msg = "SARIF result must contain at least one location"
                raise ValueError(msg)
            physical = _table(_table(locations[0], "SARIF location").get("physicalLocation"), "SARIF physical location")
            artifact = _table(physical.get("artifactLocation"), "SARIF artifact location")
            path = _reported_path(_text(artifact, "uri"), root)
            region = _table(physical.get("region"), "SARIF region")
            line = _positive_int(region, "startLine", default=1)
            column = _positive_int(region, "startColumn", default=1)
            position = _one_based_position({"row": line, "column": column}, path, documents)
            diagnostics.append(
                Diagnostic(
                    rule,
                    _redact_message(message, root),
                    severity,
                    "detekt",
                    Location(_relative(path, root), position=position),
                    rule_id=rule,
                )
            )
    return tuple(diagnostics)


def parse_basedpyright(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    report = _BasedPyrightReport.model_validate_json(payload)
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for item in report.general_diagnostics:
        path = _reported_path(item.file, root)
        location = Location(_relative(path, root))
        if item.range is not None:
            start = _basedpyright_position(item.range.start, path, documents)
            end = _basedpyright_position(item.range.end, path, documents)
            location = Location(_relative(path, root), region=Region(start, end))
        rule = item.rule or "basedpyright"
        diagnostics.append(
            Diagnostic(
                rule,
                _redact_message(item.message, root),
                _severity_text(item.severity),
                "basedpyright",
                location,
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def parse_shellcheck(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    report = _ShellCheckReport.model_validate_json(payload)
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for item in report.comments:
        path = _reported_path(item.file, root)
        rule = f"SC{item.code}"
        try:
            level = _ShellCheckLevel(item.level)
        except ValueError as exc:
            msg = f"unsupported ShellCheck severity: {item.level!r}"
            raise ValueError(msg) from exc
        severity = Severity.ERROR if level is _ShellCheckLevel.ERROR else Severity.WARNING
        start = _one_based_position({"row": item.line, "column": item.column}, path, documents)
        end = _one_based_position({"row": item.end_line, "column": item.end_column}, path, documents)
        if (end.line, end.character) < (start.line, start.character):
            msg = "ShellCheck diagnostic end precedes its start"
            raise ValueError(msg)
        diagnostics.append(
            Diagnostic(
                rule,
                _redact_message(item.message, root),
                severity,
                "shellcheck",
                Location(_relative(path, root), region=Region(start, end)),
                rule_id=rule,
            )
        )
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.location.path,
                -1 if item.location.region is None else item.location.region.start.line,
                -1 if item.location.region is None else item.location.region.start.character,
                item.code,
                item.message,
            ),
        )
    )


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


def parse_react_doctor(
    payload: str,
    *,
    root: Path,
    expected_projects: frozenset[Path] | None = None,
    allow_empty_projects: bool = False,
    include_warnings: bool = False,
) -> tuple[Diagnostic, ...]:
    report = _ReactDoctorReport.model_validate_json(payload)
    return _parse_react_doctor_report(
        report,
        root=root,
        expected_projects=expected_projects,
        allow_empty_projects=allow_empty_projects,
        include_warnings=include_warnings,
        require_react_detection=True,
    )


def _parse_react_doctor_report(
    report: _ReactDoctorReport,
    *,
    root: Path,
    expected_projects: frozenset[Path] | None,
    allow_empty_projects: bool,
    include_warnings: bool,
    require_react_detection: bool,
) -> tuple[Diagnostic, ...]:
    expected_version = manifest.eslint_peers()["react-doctor"]
    if report.version != expected_version:
        msg = f"React Doctor reported version {report.version!r}; expected {expected_version!r}"
        raise ValueError(msg)
    if report.error is not None:
        msg = f"React Doctor scan failed: {report.error.message}"
        raise ValueError(msg)
    if not report.ok:
        msg = "React Doctor report did not complete successfully"
        raise ValueError(msg)
    if report.skipped_projects:
        msg = f"React Doctor skipped {len(report.skipped_projects)} project(s) before analysis"
        raise ValueError(msg)
    if report.react_detected is False and require_react_detection:
        msg = "React Doctor did not detect React in an expected project"
        raise ValueError(msg)
    if not report.projects and allow_empty_projects:
        if report.diagnostics:
            msg = "React Doctor returned diagnostics without an analyzed project"
            raise ValueError(msg)
        return ()
    if report.baseline_degraded:
        msg = "React Doctor changed-scope baseline degraded"
        raise ValueError(msg)
    if not report.projects:
        msg = "React Doctor returned no analyzed projects"
        raise ValueError(msg)
    if expected_projects is not None:
        if (report.react_detected is not True and require_react_detection) or report.baseline_degraded is not False:
            msg = "React Doctor omitted required v3 detection or baseline-completeness metadata"
            raise ValueError(msg)
        reported_projects = frozenset(_contained_report_directory(item, root) for item in report.projects)
        if reported_projects != expected_projects:
            msg = "React Doctor did not return exactly the requested project set"
            raise ValueError(msg)

    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for project in report.projects:
        if not project.complete:
            msg = f"React Doctor project did not complete: {project.directory!r}"
            raise ValueError(msg)
        if project.skipped_checks:
            msg = f"React Doctor skipped checks for project: {project.directory!r}"
            raise ValueError(msg)
        if expected_projects is not None and (
            project.skipped_checks is None or project.analyzed_file_count is None or project.scanned_file_count is None
        ):
            msg = f"React Doctor omitted completeness metadata for project: {project.directory!r}"
            raise ValueError(msg)
        if project.analyzed_file_count == 0 or project.scanned_file_count == 0:
            msg = f"React Doctor analyzed no files for project: {project.directory!r}"
            raise ValueError(msg)
        directory = _contained_report_directory(project, root)
        for item in project.diagnostics:
            # The 0.9.x compact JSON protocol can retain warning diagnostics
            # even when both config and argv disable warnings. Standards only
            # promotes React Doctor's error surface, so enforce that boundary
            # after validating the complete upstream report.
            if item.severity == "warning" and not include_warnings:
                continue
            path = _react_doctor_path(item, directory, root)
            location = _react_doctor_location(item, path, root, documents)
            rule = f"{item.plugin}/{item.rule}"
            diagnostics.append(
                Diagnostic(
                    rule,
                    _redact_message(item.message, root),
                    Severity.ERROR,
                    "react-doctor",
                    location,
                    rule_id=rule,
                    help_url=item.url,
                )
            )
    return tuple(diagnostics)


def _contained_report_directory(project: _ReactDoctorProject, root: Path) -> Path:
    directory = Path(project.directory)
    resolved = (directory if directory.is_absolute() else root / directory).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        msg = "React Doctor reported a project outside the repository root"
        raise ValueError(msg) from exc
    return resolved


def _react_doctor_path(item: _ReactDoctorDiagnostic, directory: Path, root: Path) -> Path:
    raw_path = Path(item.file_path)
    resolved = (raw_path if raw_path.is_absolute() else directory / raw_path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        msg = "React Doctor reported a path outside the repository root"
        raise ValueError(msg) from exc
    return resolved


def _react_doctor_location(
    item: _ReactDoctorDiagnostic,
    path: Path,
    root: Path,
    documents: dict[Path, SourceDocument | None],
) -> Location:
    relative_path = _relative(path, root)
    # React Doctor uses the protocol sentinel (0, 0) for project-level
    # diagnostics that truthfully identify a file but no source position.
    if item.line == 0 or item.column == 0:
        return Location(relative_path)
    start = _one_based_position(
        {"row": item.line, "column": item.column},
        path,
        documents,
    )
    if item.end_line is not None and item.end_column is not None:
        try:
            end = _one_based_position({"row": item.end_line, "column": item.end_column}, path, documents)
        except ValueError:
            end = None
        if end is not None and (end.line, end.character) >= (start.line, start.character):
            return Location(relative_path, region=Region(start, end))
    return Location(relative_path, position=start)


def _ruff_argv(files: Sequence[str], *, config: Path | None = None) -> tuple[str, ...]:
    config_args = () if config is None else ("--config", str(config))
    return ("ruff", "check", "--output-format", "json", *config_args, "--", *files)


def _eslint_json_argv(argv: Sequence[str], *, pass_on_unpruned_suppressions: bool = False) -> tuple[str, ...]:
    values = list(argv)
    try:
        index = values.index("eslint") + 1
    except ValueError as exc:
        msg = "ESLint command does not contain an eslint executable"
        raise ValueError(msg) from exc
    suppression_args = ("--pass-on-unpruned-suppressions",) if pass_on_unpruned_suppressions else ()
    values[index:index] = [
        "--format",
        str(_ESLINT_FORMATTER),
        "--no-warn-ignored",
        "--no-cache",
        *suppression_args,
    ]
    return tuple(values)


def _argv_file_count(argv: Sequence[str]) -> int:
    if "--" not in argv:
        return 0
    # npm has both a package-manager delimiter and ESLint's file delimiter.
    # The final delimiter is the analyzer boundary for every supported client.
    index = max(position for position, value in enumerate(argv) if value == "--")
    return len(argv) - index - 1


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
) -> _PreparedInputs:
    repository = root.resolve()
    contained = tuple(_contained_path(item, repository) for item in files)
    selected = contained if policy is None else policy.filter_paths(contained)
    return _PreparedInputs(
        repository, selected, grouped if grouped is not None else group_paths(selected, policy=policy)
    )


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


def _positive_int(table: dict[str, object], key: str, *, default: int | None = None) -> int:
    value = table.get(key, default)
    if type(value) is not int or value < 1:
        msg = f"{key} must be a positive integer"
        raise TypeError(msg)
    return value


def _path(table: dict[str, object], key: str, root: Path) -> Path:
    return _reported_path(_text(table, key), root)


def _reported_path(value: str, root: Path) -> Path:
    path = Path(value)
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


def _basedpyright_position(
    value: _BasedPyrightPosition, path: Path, cache: dict[Path, SourceDocument | None]
) -> Position:
    position = _document(path, cache).utf16_point(line=value.line, character=value.character)
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


def _zero_based_position(value: dict[str, object], path: Path, cache: dict[Path, SourceDocument | None]) -> Position:
    position = _document(path, cache).utf16_point(line=_integer(value, "line"), character=_integer(value, "character"))
    if position is None:
        msg = "analyzer position is outside source"
        raise ValueError(msg)
    return position


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
