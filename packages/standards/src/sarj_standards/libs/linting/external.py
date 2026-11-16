from __future__ import annotations

import ast
import contextlib
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from functools import cache, partial
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv, no shell, bounded timeout.
import sys
import tempfile
import threading
import time
import tokenize
import tomllib
from typing import TYPE_CHECKING, ClassVar, Final, Literal, NamedTuple, Protocol
import zipfile

from pathspec import PathSpec
from pydantic import BaseModel, ConfigDict, Field, RootModel
from sarj_rule_contracts import RuleEngine, RuleSelection
import yaml

from sarj_standards.libs.adoption import manifest, packagemanager
from sarj_standards.libs.adoption.configs import OXLINT_CONFIG_NAMES, OXLINT_SUPPRESSIONS
from sarj_standards.libs.adoption.lifecycle import TYPESCRIPT_CAPABILITY, Command
from sarj_standards.libs.diagnostics import (
    AnalyzerId,
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Position,
    Region,
    RuleExecution,
    RuleExecutionState,
    Severity,
    SourceDocument,
    ToolReport,
    TrustMode,
)
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.staged_git import staged_environment
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml

from . import mobile_tools, oxlint, security_tools, stylelint
from .execution_plan import RuffProjectPlan, ShellCheckFamilyPlan
from .process import (
    OutputLimitError as OutputLimitError,
    ProcessCapabilities,
    ProcessExecutor as ProcessExecutor,
    ProcessOutput as ProcessOutput,
    ProcessRequest as ProcessRequest,
    RequestExecutor,
    ToolResolution,
    executor_capabilities,
    raise_if_cancelled,
)
from .result_cache import (
    CachedResult,
    UnknownInputsError,
    cached_analysis,
    cached_python_analysis,
    environment_parts,
    executable_identity,
    file_identity,
)
from .runner import GroupedPaths, accepts_hook_path, group_paths
from .shell_policy import SHELLCHECK_ARGS


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from typing import BinaryIO

    from pydantic import JsonValue

    from .policy import Policy


type ProcessRunner = ProcessExecutor


class _ReactDoctorSelection(NamedTuple):
    project: Path
    projects: tuple[Path, ...]


class _DeptryPackage(NamedTuple):
    path: Path
    import_root: str


class _PreparedInputs(NamedTuple):
    repository: Path
    selected: tuple[str, ...]
    grouped: GroupedPaths


@dataclass(frozen=True, slots=True)
class UpstreamRules:
    ids: frozenset[str] = frozenset()
    warning_only: bool = False


_NO_UPSTREAM_RULES = UpstreamRules()


_TIMEOUT = timedelta(minutes=15)
# Serialize Oxlint suppression ledger access between baseline workers.
_SUPPRESSIONS_LOCK = threading.Lock()
_DETEKT_FINDINGS = 2
_MAX_STDOUT_BYTES = 16 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_MOBILE_CONFIG_BYTES = 1024 * 1024
_PACKAGED_MOBILE_CONFIGS = Path(__file__).resolve().parents[2] / "configs"
_READ_BYTES = 64 * 1024
_SECURITY_BATCH_SIZE = 250
_MAX_OXLINT_PROJECTS = 128
_MAX_PYTHON_PROJECTS = 32
_SHELLCHECK_BATCH_SIZE = 250
_SHELLCHECK_VERSION: Final = "0.11.0"
_SHELLCHECK_VERSION_RE: Final = re.compile(r"^version:\s*(?P<version>\S+)\s*$", re.MULTILINE)
_BASEDPYRIGHT_BASELINE_SHRINK_RE: Final = re.compile(
    r"updated [^\r\n]+ with (?:1 error|(?:0|[2-9]|[1-9][0-9]+) errors) "
    r"\(went down by [1-9][0-9]*\)"
)
_BASEDPYRIGHT_BASELINE_DISCARD_RE: Final = re.compile(
    r"baseline file is outdated, run without `--baselinemode=discard` to update it\. "
    r"\(went down by [1-9][0-9]*\)"
)
_DEPTRY_ANNOTATION_RE: Final = re.compile(
    r"^::warning file=(?P<file>.*?),line=(?P<line>[1-9][0-9]*)"
    r"(?:,col=(?P<column>[1-9][0-9]*))?,title=(?P<code>DEP00[123])::(?P<message>.*)$"
)
_ANALYSIS_DEADLINE = timedelta(seconds=300)
_NODE_OPTIONS: Final = "--max-old-space-size=4096"
_LARGE_NODE_OPTIONS: Final = "--max-old-space-size=8192"
_LARGE_HOST_MEMORY: Final = 12 * 1024**3
_CGROUP_ROOT: Final = Path("/sys/fs/cgroup")
_PROCESS_CGROUPS: Final = Path("/proc/self/cgroup")
_CGROUP_RECORD_FIELDS: Final = 3
_CGROUP_MEMORY_LIMIT_FILES: Final = (
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
)
_PYTHON_TEST_PATHS: Final = PathSpec.from_lines(
    "gitignore", ("**/test/**", "**/tests/**", "**/test_*.py", "**/*_test.py", "**/conftest.py")
)


class _JsonToolReport(RootModel[dict[str, object]]):
    pass


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
# Files whose change can move React Doctor's findings; `is_react_doctor_metadata` adds the
# config prefixes. PR scoping and analysis share this one list.
_REACT_DOCTOR_METADATA_NAMES = frozenset(
    {
        *OXLINT_CONFIG_NAMES,
        OXLINT_SUPPRESSIONS,
        "bun.lock",
        "bun.lockb",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
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
        # Native supervisors' scalar worker budgets must reach their analyzers.
        "GOMAXPROCS",
        "HOME",
        "LANG",
        "MISE_DATA_DIR",
        "MISE_INSTALLS_DIR",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "PATH",
        "RAYON_NUM_THREADS",
        "REACT_DOCTOR_PARALLEL",
        "SHELL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
        "UV_CACHE_DIR",
        "UV_CONCURRENT_BUILDS",
        "UV_PYTHON_INSTALL_DIR",
        "UV_TOOL_DIR",
        "XDG_DATA_HOME",
    }
)


class _ReactDoctorProtocolModel(BaseModel):
    """Strictly type every React Doctor field consumed by the adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)


class _ReactDoctorSourcePosition(_ReactDoctorProtocolModel):
    line: int = Field(ge=0)
    character: int = Field(ge=0)
    byte_offset: int = Field(alias="byteOffset", ge=0)


class _ReactDoctorDiagnostic(_ReactDoctorProtocolModel):
    file_path: str = Field(alias="filePath", min_length=1)
    plugin: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    severity: Literal["error", "warning"]
    message: str = Field(min_length=1)
    line: int = Field(ge=0)
    column: int = Field(ge=0)
    source_position: _ReactDoctorSourcePosition | None = Field(default=None, alias="sourcePosition")
    end_line: int | None = Field(default=None, alias="endLine", ge=0)
    end_column: int | None = Field(default=None, alias="endColumn", ge=0)
    url: str | None = None


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


class LocalProcessExecutor:
    capabilities = ProcessCapabilities()

    def run(self, request: ProcessRequest) -> ProcessOutput:
        return _run_process(request)


DEFAULT_EXECUTOR = LocalProcessExecutor()


def analyze_external(
    files: Sequence[str],
    *,
    root: Path,
    trust: TrustMode | str,
    runner: ProcessExecutor | None = None,
    policy: Policy | None = None,
    capabilities: frozenset[str] | None = None,
    grouped: GroupedPaths | None = None,
    include_react_doctor: bool = False,
    react_doctor_staged: bool = False,
    force_react_doctor: bool = False,
    react_doctor_full_scan: bool = False,
    pass_on_unpruned_suppressions: bool = False,
    rule_ids: frozenset[str] | None = None,
    upstream_rules: UpstreamRules = _NO_UPSTREAM_RULES,
    security_selection: RuleSelection | None = None,
    python_type_check: bool = True,
    typescript: bool = True,
) -> tuple[ToolReport, ...]:
    try:
        execute = DEFAULT_EXECUTOR if runner is None else runner
        local_tools = executor_capabilities(execute).tool_resolution is ToolResolution.LOCAL
        normalized_trust = TrustMode(trust)
        react_execute = _staged_react_runner(root, runner=runner) if react_doctor_staged else execute
        root, contained, routed = _prepare_inputs(files, root, policy=policy, grouped=grouped)
    except (OSError, TypeError, ValueError) as exc:
        issue = ExecutionIssue("external", "invalid-input", str(exc))
        return (ToolReport("external", Completion.FAILED, issues=(issue,)),)
    reports: list[ToolReport] = []
    reports.extend(
        _security_reports(
            routed.iac,
            root=root,
            runner=execute,
            capabilities=capabilities,
            security_selection=security_selection,
        )
    )
    reports.extend(
        _shell_source_reports(routed, root=root, runner=execute, capabilities=capabilities, attest_version=local_tools)
    )
    try:
        reports.extend(
            _mobile_source_reports(
                routed,
                root=root,
                runner=execute,
                capabilities=capabilities,
                managed_tools=local_tools,
            )
        )
    except (OSError, TypeError, ValueError, RecursionError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        issue = ExecutionIssue("mobile-tools", "provisioning-failure", redact_message(str(exc), root))
        reports.append(ToolReport("mobile-tools", Completion.FAILED, issues=(issue,)))

    def collect_python_reports() -> None:
        if routed.python:
            if capabilities is None or "ruff" in capabilities:
                ruff = cached_python_analysis(
                    "ruff",
                    root,
                    selected=routed.python,
                    parameters=(
                        f"runner={type(execute).__qualname__}:{executor_capabilities(execute).tool_resolution}",
                    ),
                    compute=lambda: CachedResult(_invoke_ruff_projects(routed.python, root=root, runner=execute)),
                )
                reports.extend(ruff.reports)
            if capabilities is not None and "deptry" in capabilities:
                reports.extend(
                    _invoke_deptry_projects(
                        routed.python,
                        root=root,
                        runner=execute,
                        trust=normalized_trust,
                    )
                )
            if python_type_check and (capabilities is None or "pyright" in capabilities):
                reports.extend(
                    _invoke_python_projects(
                        "basedpyright",
                        routed.python,
                        root=root,
                        runner=execute,
                        parser=parse_basedpyright,
                        project_mode=any(Path(path).is_dir() for path in contained),
                        trust=normalized_trust,
                    )
                )

    collect_python_reports()
    from .devops_source import SUPPORTED, analyze_sources  # ruff: ignore[import-outside-top-level] -- native catalog uses the bounded runner defined in this module.

    reports.extend(
        analyze_sources(
            root=root,
            paths=tuple(dict.fromkeys((*routed.text, *routed.iac))),
            selected=SUPPORTED if capabilities is None else SUPPORTED.intersection(capabilities),
            trust_repository_code=normalized_trust is TrustMode.TRUSTED,
            runner=execute,
            shared_shellcheck=capabilities is None or "shellcheck" in capabilities,
            scope=contained,
            policy=policy,
        )
    )
    reports.extend(
        _quality_reports(root, capabilities=capabilities, policy=policy, trust=normalized_trust, runner=execute)
    )
    if capabilities is None or "devops-schema" in capabilities:
        from .devops_schema import analyze_source_schemas  # ruff: ignore[import-outside-top-level] -- schema validation is a selected local runtime adapter.

        reports.extend(analyze_source_schemas(root=root, paths=tuple(routed.text)))
    typescript_enabled = typescript and (capabilities is None or TYPESCRIPT_CAPABILITY in capabilities)
    reports.extend(
        _typescript_reports(
            routed.typescript,
            contained,
            root=root,
            runner=execute,
            local_tools=local_tools,
            trust=normalized_trust,
            enabled=typescript_enabled,
            request=_oxlint_request(rule_ids, upstream_rules),
            pass_on_unpruned_suppressions=pass_on_unpruned_suppressions,
        )
    )
    reports.extend(
        _stylesheet_reports(
            routed.css,
            root=root,
            runner=execute,
            local_tools=local_tools,
            trust=normalized_trust,
            enabled=typescript_enabled and rule_ids is None and not upstream_rules.ids,
        )
    )
    react_selection = _selected_react_doctor_projects(
        root,
        enabled=include_react_doctor,
        has_typescript=force_react_doctor
        or bool(routed.typescript)
        or any(is_react_doctor_metadata(Path(item)) for item in contained),
        capabilities=capabilities,
    )
    if react_selection is not None:
        react_root, react_projects = react_selection
        reports.append(
            _invoke_react_doctor(
                react_root,
                projects=react_projects,
                root=root,
                runner=react_execute,
                file_count=max(len(routed.typescript), 1),
                staged=react_doctor_staged,
                full_scan=react_doctor_full_scan,
                paths=contained,
                trust_repository_code=normalized_trust is TrustMode.TRUSTED,
                include_compiler=not (typescript and (capabilities is None or TYPESCRIPT_CAPABILITY in capabilities)),
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
            rule_executions=report.rule_executions,
        )
        for report in reports
    )


def _staged_react_runner(root: Path, *, runner: ProcessExecutor | None) -> ProcessExecutor:
    environment = staged_environment(root)
    if runner is not None:
        return runner
    if (index_file := environment.get("GIT_INDEX_FILE")) is not None:
        return RequestExecutor(partial(_run_staged_process, index_file=index_file), DEFAULT_EXECUTOR.capabilities)
    return DEFAULT_EXECUTOR


def _oxlint_request(rule_ids: frozenset[str] | None, upstream: UpstreamRules) -> oxlint.OxlintRequest:
    if rule_ids is None and not upstream.ids:
        return oxlint.OxlintRequest()
    # Advisories run at error so bulk suppressions still apply; the report downgrades them to warnings.
    advisories = dict.fromkeys(upstream.ids, "error") if upstream.warning_only else {}
    return oxlint.OxlintRequest(
        rules=frozenset({*(f"@sarj/{rule}" for rule in rule_ids or ()), *upstream.ids}),
        forced={**oxlint.REQUIRED_RULES, **advisories},
    )


def _stylesheet_reports(
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
    local_tools: bool,
    trust: TrustMode,
    enabled: bool,
) -> tuple[ToolReport, ...]:
    if not enabled or not files:
        return ()
    if trust is not TrustMode.TRUSTED:
        issue = ExecutionIssue("stylelint", "trust-required", "CSS analysis requires trusted local Node tooling")
        return (ToolReport("stylelint", Completion.FAILED, issues=(issue,)),)
    adopted = manifest.load(root)
    project = root / adopted.typescript_dest if adopted is not None else root
    if local_tools and (issue := _missing_local_binary_issue("stylelint", project, root)) is not None:
        return (ToolReport("stylelint", Completion.FAILED, issues=(issue,)),)
    config = Path(__file__).resolve().parents[2] / "configs"
    reports: list[ToolReport] = []
    for offset in range(0, len(files), _SECURITY_BATCH_SIZE):
        batch = tuple(files[offset : offset + _SECURITY_BATCH_SIZE])
        argv = (
            "stylelint",
            "--config",
            str(config / "stylelint.strict.json"),
            "--config-basedir",
            str(project),
            "--ignore-path",
            str(config / "stylelint.ignore"),
            "--formatter",
            "json",
            "--",
            *(str(root / path) for path in batch),
        )
        if local_tools:
            argv = tuple(packagemanager.exec_argv(packagemanager.detect(project), *argv))
            argv = _local_node_binary_argv("stylelint", argv, project, root)
        reports.append(
            _invoke_text_tool(
                "stylelint",
                argv,
                cwd=project,
                root=root,
                runner=runner,
                parser=partial(stylelint.parse, selected=batch),
                finding_codes=frozenset({2}),
                file_count=len(batch),
                empty_payload="[]",
                report_stream="stderr",
            )
        )
    return tuple(reports)


def _typescript_reports(
    files: Sequence[str],
    inputs: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
    local_tools: bool,
    trust: TrustMode,
    enabled: bool,
    request: oxlint.OxlintRequest,
    pass_on_unpruned_suppressions: bool,
) -> list[ToolReport]:
    if not enabled:
        return []
    try:
        commands, unowned = oxlint.select_oxlint_commands(root, files, label="analysis")
    except (OSError, TypeError, ValueError) as exc:
        message = redact_message(f"{type(exc).__name__}: {exc}", root)
        return [
            ToolReport(
                "oxlint", Completion.FAILED, issues=(ExecutionIssue("oxlint", "configuration-failure", message),)
            )
        ]
    reports: list[ToolReport] = []
    if unowned:
        issue = ExecutionIssue(
            "oxlint",
            "coverage-missing",
            f"no TypeScript project accepts {unowned} selected JavaScript/TypeScript path(s)",
        )
        reports.append(_oxlint_failure(issue, InvocationId("oxlint:unowned"), unowned))
    if len(commands) > _MAX_OXLINT_PROJECTS:
        message = f"selected {len(commands)} Oxlint projects; maximum is {_MAX_OXLINT_PROJECTS}"
        reports.append(
            ToolReport("oxlint", Completion.FAILED, issues=(ExecutionIssue("oxlint", "project-limit", message),))
        )
        commands = ()
    deadline = time.monotonic() + _ANALYSIS_DEADLINE.total_seconds()
    environment = {**_analysis_environment(), "NODE_OPTIONS": _node_options()}
    for command in commands:
        with _SUPPRESSIONS_LOCK:
            report = _invoke_oxlint(
                command,
                root=root,
                runner=runner,
                local_tools=local_tools,
                trust=trust,
                request=request,
                environment=environment,
                deadline=deadline,
            )
        if pass_on_unpruned_suppressions:
            report = replace(
                report,
                diagnostics=tuple(item for item in report.diagnostics if item.rule_id != oxlint.UNUSED_SUPPRESSION),
            )
        reports.append(report)
    if request.rules is None:
        from . import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports this module's process helpers.

        projects = tuple(oxlint.config_directory(command) for command in commands)
        reports.extend(oxfmt.reports(inputs, projects, root=root, runner=runner, trust=trust))
    return reports


def _invoke_oxlint(
    command: Command,
    *,
    root: Path,
    runner: ProcessExecutor,
    local_tools: bool,
    trust: TrustMode,
    request: oxlint.OxlintRequest,
    environment: Mapping[str, str],
    deadline: float,
) -> ToolReport:
    invocation = InvocationId(f"oxlint:{command.cwd.relative_to(root).as_posix() or '.'}")
    file_count = len(oxlint.command_files(command))
    if trust is TrustMode.SAFE:
        message = "Oxlint configs and JS plugins are executable repository code; retry with TrustMode.TRUSTED"
        return _oxlint_failure(ExecutionIssue("oxlint", "trust-required", message), invocation, file_count)
    if local_tools and (issue := _missing_local_binary_issue("oxlint", command.cwd, root)) is not None:
        return _oxlint_failure(issue, invocation, file_count)
    started = time.monotonic()
    if started >= deadline:
        message = f"Oxlint aggregate analysis exceeded {_ANALYSIS_DEADLINE.total_seconds():g} seconds"
        return _oxlint_failure(ExecutionIssue("oxlint", "aggregate-timeout", message), invocation, file_count)
    try:
        if local_tools:
            command = Command(
                command.label, _local_node_binary_argv("oxlint", command.argv, command.cwd, root), command.cwd
            )
        report = oxlint.run_oxlint(
            command,
            root=root,
            runner=runner,
            environment=environment,
            request=request,
            timeout_seconds=deadline - started,
        )
    except (OSError, TypeError, ValueError, RecursionError, subprocess.SubprocessError) as exc:
        message = redact_message(f"{type(exc).__name__}: {exc}", root)
        report = ToolReport("oxlint", Completion.FAILED, issues=(ExecutionIssue("oxlint", "tool-failure", message),))
    return replace(
        report,
        analyzer_id=AnalyzerId("oxlint"),
        invocation_id=invocation,
        duration_ms=round((time.monotonic() - started) * 1_000),
        file_count=report.file_count or file_count,
    )


def _oxlint_failure(issue: ExecutionIssue, invocation: InvocationId, file_count: int) -> ToolReport:
    return ToolReport(
        "oxlint",
        Completion.FAILED,
        issues=(issue,),
        analyzer_id=AnalyzerId("oxlint"),
        invocation_id=invocation,
        file_count=file_count,
    )


def _quality_reports(
    root: Path, *, capabilities: frozenset[str] | None, policy: Policy | None, trust: TrustMode, runner: ProcessExecutor
) -> tuple[ToolReport, ...]:
    if capabilities is None or capabilities.isdisjoint(manifest.QUALITY_ANALYZERS):
        return ()
    from .duplicate_code import analyze_duplicates  # ruff: ignore[import-outside-top-level] -- whole-tree adapters reuse this module's bounded runner.
    from .unused_modules import analyze_application_modules  # ruff: ignore[import-outside-top-level] -- application ownership depends on the whole native production graph.

    allows_path: Callable[[str], bool] = (lambda _path: True) if policy is None else policy.allows_path
    reports: list[ToolReport] = []
    # Both adapters require unchanged source, so neither uses the changed-file selection.
    if "jscpd" in capabilities:
        adopted = manifest.load(root)
        reports.append(
            analyze_duplicates(
                root=root,
                paths=(".",) if adopted is None else adopted.verify_paths,
                allows_path=allows_path,
                runner=runner,
            )
        )
    if "knip" in capabilities:
        reports.append(analyze_application_modules(root=root, trust=trust, allows_path=allows_path, runner=runner))
    return tuple(reports)


def _security_reports(
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
    capabilities: frozenset[str] | None,
    security_selection: RuleSelection | None = None,
) -> tuple[ToolReport, ...]:
    if capabilities is not None and capabilities.isdisjoint({"zizmor", "checkov"}):
        return ()
    checkov_checks = security_selection.native_ids_for(RuleEngine.CHECKOV) if security_selection is not None else None
    zizmor_selected = security_selection is not None and RuleEngine.ZIZMOR in security_selection.engines
    try:
        selected = security_tools.select_inputs(
            files, root=root, capabilities=capabilities, checkov_rule_ids=checkov_checks
        )
    except (OSError, TypeError, ValueError) as exc:
        issue = ExecutionIssue("security-tools", "invalid-input", redact_message(str(exc), root))
        return (ToolReport("security-tools", Completion.FAILED, issues=(issue,)),)
    reports: list[ToolReport] = []
    if selected.workflows and (capabilities is None or "zizmor" in capabilities):
        for start in range(0, len(selected.workflows), _SECURITY_BATCH_SIZE):
            batch = selected.workflows[start : start + _SECURITY_BATCH_SIZE]
            reports.append(
                _invoke(
                    "zizmor",
                    (
                        *security_tools.command("zizmor"),
                        "--offline",
                        *(("--persona", "auditor") if zizmor_selected else ()),
                        "--collect=all",
                        "--format=sarif",
                        "--no-exit-codes",
                        "--strict-collection",
                        "--no-ignores",
                        "--config",
                        str(_PACKAGED_MOBILE_CONFIGS / "zizmor.strict.yml"),
                        "--",
                        *batch,
                    ),
                    cwd=root,
                    root=root,
                    runner=RequestExecutor(
                        partial(_security_runner, runner, name="zizmor"), executor_capabilities(runner)
                    ),
                    parser=security_tools.parse_zizmor,
                    version=security_tools.VERSIONS["zizmor"],
                    invocation_id=InvocationId(f"batch-{start // _SECURITY_BATCH_SIZE + 1}"),
                    file_count=len(batch),
                )
            )
    if capabilities is None or "checkov" in capabilities:
        reports.extend(_checkov_reports(selected, root=root, runner=runner, checkov_checks=checkov_checks))
    return tuple(reports)


def _checkov_reports(
    selected: security_tools.SecurityInputs,
    *,
    root: Path,
    runner: ProcessExecutor,
    checkov_checks: frozenset[str] | None,
) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    for framework, paths in (("terraform", selected.terraform), ("kubernetes", selected.kubernetes)):
        checks = security_tools.CHECKOV_CHECKS if checkov_checks is None else checkov_checks
        if framework == "kubernetes":
            checks = checks.intersection(security_tools.KUBERNETES_CHECKS)
        if not checks:
            continue
        for start in range(0, len(paths), _SECURITY_BATCH_SIZE):
            batch = paths[start : start + _SECURITY_BATCH_SIZE]
            reports.append(
                _invoke(
                    "checkov",
                    (
                        *security_tools.command("checkov"),
                        "--config-file",
                        str(_PACKAGED_MOBILE_CONFIGS / "checkov.strict.yml"),
                        "--framework",
                        framework,
                        "--check",
                        ",".join(sorted(checks)),
                        "--skip-download",
                        "--output",
                        "json",
                        "--file",
                        *batch,
                    ),
                    cwd=root,
                    root=root,
                    runner=RequestExecutor(
                        partial(_security_runner, runner, name="checkov"), executor_capabilities(runner)
                    ),
                    parser=security_tools.parse_checkov,
                    version=security_tools.VERSIONS["checkov"],
                    invocation_id=InvocationId(f"{framework}:batch-{start // _SECURITY_BATCH_SIZE + 1}"),
                    file_count=len(batch),
                )
            )

    return tuple(reports)


def _security_runner(runner: ProcessExecutor, request: ProcessRequest, *, name: str) -> ProcessOutput:
    output = runner.run(replace(request, timeout_seconds=min(request.timeout_seconds, 300)))
    if name == "zizmor" and output.returncode != 0:
        msg = f"zizmor audit failed with exit {output.returncode}"
        raise OSError(msg)
    return output


def _mobile_source_reports(
    grouped: GroupedPaths,
    *,
    root: Path,
    runner: ProcessExecutor,
    capabilities: frozenset[str] | None,
    managed_tools: bool,
) -> tuple[ToolReport, ...]:
    def enabled(name: str) -> bool:
        return capabilities is not None and name in capabilities

    reports: list[ToolReport] = []
    swift_files = _mobile_language_paths(root, grouped.swift, language="swift")
    kotlin_files = _mobile_language_paths(root, grouped.kotlin, language="kotlin")

    def collect_swift_reports() -> None:
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

    collect_swift_reports()
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

    def collect_mobile_security() -> None:
        if mobile_files and enabled("mobile-security"):
            config = (
                _PACKAGED_MOBILE_CONFIGS / "mobsf.strict.yml"
                if managed_tools
                else _first_existing(root, (".mobsf", "mobsf.strict.yml"))
            )
            rules = mobile_tools.mobsf_rules() if managed_tools else Path("mobsfscan-rules")
            argv = _mobsfscan_argv(rules, config=config, managed=managed_tools)

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

    collect_mobile_security()
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


def _mobsfscan_argv(rules: Path, *, config: Path | None, managed: bool = False) -> tuple[str, ...]:
    argv = (
        *(mobile_tools.semgrep_command() if managed else ("semgrep",)),
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
    raw = parse_yaml(_read_mobile_config(config))
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
    runner: ProcessExecutor,
    parser: ProtocolParser,
    finding_codes: frozenset[int],
    file_count: int,
    fatal_codes: frozenset[int] = frozenset(),
    empty_payload: str = "",
    report_stream: Literal["stdout", "stderr"] = "stdout",
) -> ToolReport:
    started = time.monotonic()
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary normalizes process failures and diagnostics.
        request = process_request(argv, cwd=cwd)
        if report_stream == "stderr":
            request = replace(request, max_stderr_bytes=request.max_stdout_bytes)
        output = runner.run(request)
        if output.returncode in fatal_codes or output.returncode not in {0, *finding_codes}:
            message = redact_message(output.stderr.strip() or f"{name} exited {output.returncode}", root)
            issue = ExecutionIssue(name, "tool-failure", message, output.returncode)
            return ToolReport(name, Completion.FAILED, issues=(issue,))
        payload = (output.stderr if report_stream == "stderr" else output.stdout).strip() or empty_payload
        if not payload:
            diagnostics: tuple[Diagnostic, ...] = ()
        else:
            diagnostics = parser(payload, root=root)
        if output.returncode in finding_codes and not diagnostics:
            message = redact_message(output.stderr.strip() or f"{name} reported findings without diagnostics", root)
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
        issue = ExecutionIssue(name, "tool-failure", redact_message(f"{type(exc).__name__}: {exc}", root))
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
    runner: ProcessExecutor,
    file_count: int,
) -> ToolReport:
    started = time.monotonic()
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary owns report lifecycle and protocol checks.
        with tempfile.TemporaryDirectory(prefix="code-standards-detekt-") as temporary_directory:
            report_path = Path(temporary_directory) / "report.sarif"
            output = runner.run(process_request((*argv, "--report", f"sarif:{report_path}"), cwd=cwd))
            if output.returncode in {1, 3} or output.returncode not in {0, _DETEKT_FINDINGS}:
                message = redact_message(output.stderr.strip() or f"detekt exited {output.returncode}", root)
                issue = ExecutionIssue("detekt", "tool-failure", message, output.returncode)
                return ToolReport("detekt", Completion.FAILED, issues=(issue,))
            payload = read_bounded_report(report_path, tool="detekt", format_name="SARIF")
            diagnostics = parse_sarif(payload, root=root)
            if output.returncode == _DETEKT_FINDINGS and not diagnostics:
                message = redact_message(
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
        issue = ExecutionIssue("detekt", "tool-failure", redact_message(f"{type(exc).__name__}: {exc}", root))
        return ToolReport(
            "detekt",
            Completion.FAILED,
            issues=(issue,),
            analyzer_id=AnalyzerId("detekt"),
            invocation_id=InvocationId("detekt"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
        )


def read_bounded_report(path: Path, *, tool: str, format_name: str = "JSON") -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        msg = f"{tool} did not create its {format_name} report"
        raise OSError(msg) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        msg = f"{tool} {format_name} report is not a regular file"
        raise OSError(msg)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_STDOUT_BYTES + 1)
    if len(payload) > _MAX_STDOUT_BYTES:
        msg = f"{tool} {format_name} report exceeded {_MAX_STDOUT_BYTES} bytes"
        raise OutputLimitError(msg)
    return payload.decode("utf-8")


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
        or (capabilities is not None and not capabilities.intersection({TYPESCRIPT_CAPABILITY, "react-doctor"}))
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
            parsed: object = parse_json(package_json.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        document = manifest.as_table(parsed)
        declared: set[str] = set()
        for field in ("dependencies", "devDependencies", "peerDependencies"):
            declared.update(manifest.table_field(document, field))
        if declared.intersection(_REACT_RUNTIME_PACKAGES):
            projects.append(directory)
    return tuple(projects)


def is_react_doctor_metadata(path: Path) -> bool:
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
            "oxlint.config.",
            "tsconfig.",
            "vite.config.",
        )
    )


def _invoke_react_doctor(
    project: Path,
    *,
    projects: Sequence[Path],
    root: Path,
    runner: ProcessExecutor,
    file_count: int,
    staged: bool,
    full_scan: bool = False,
    paths: Sequence[str] = (),
    include_compiler: bool = True,
    trust_repository_code: bool = False,
) -> ToolReport:
    # Project discovery and staged execution stay in Standards. The adapter invokes
    # only the official native plugin and its public project-security callbacks.
    adopted = manifest.load(root)
    config = next(
        (
            project / f"doctor.config.{suffix}"
            for suffix in ("ts", "mts", "js", "mjs", "cts", "cjs", "json")
            if (project / f"doctor.config.{suffix}").is_file()
        ),
        _PACKAGED_MOBILE_CONFIGS / "doctor.config.json",
    )
    request = {
        "installRoot": str(packagemanager.workspace_root(project, root)),
        "config": str(config),
        "trustRepositoryCode": trust_repository_code,
        "repositoryRoot": str(root),
        "includeCompiler": include_compiler,
        "staged": staged,
        "excludedDirectories": _react_doctor_excluded_directories(
            root, () if adopted is None else adopted.doctor_excluded_paths
        ),
        "fullScan": full_scan,
        "metadataPaths": [str(root / path) for path in paths if is_react_doctor_metadata(Path(path))],
        "paths": [str(root / path) for path in paths],
        "projects": [
            {
                "root": str(item),
                "excluded": [str(other) for other in projects if other != item and other.is_relative_to(item)],
            }
            for item in projects
        ],
    }
    # Yarn supplies the loader for its virtual dependency tree. A bare Node
    # process cannot resolve managed peers in a Plug'n'Play installation.
    node = ("yarn", "node") if _uses_plug_n_play(project, root) else ("node",)
    return _invoke(
        "react-doctor",
        (*node, str(_PACKAGED_MOBILE_CONFIGS / "react-doctor-runner.mjs")),
        cwd=project,
        root=root,
        runner=runner,
        parser=parse_react_doctor,
        file_count=file_count,
        version=manifest.typescript_peers()["oxlint-plugin-react-doctor"],
        input_bytes=json.dumps(request).encode("utf-8"),
    )


def _react_doctor_excluded_directories(root: Path, patterns: Sequence[str]) -> list[str]:
    if not patterns:
        return []
    exclusions = PathSpec.from_lines("gitignore", patterns)
    excluded: list[str] = []
    for parent, directories, _filenames in os.walk(root, topdown=True, followlinks=False):
        directory = Path(parent).resolve()
        if exclusions.match_file(directory.relative_to(root).as_posix()):
            excluded.append(str(directory))
            directories[:] = []
            continue
        directories[:] = sorted(name for name in directories if name not in _JAVASCRIPT_SCAN_SKIP_DIRS)
    return excluded


class _NativeReactDoctorReport(_ReactDoctorProtocolModel):
    complete: Literal[True]
    diagnostics: tuple[_ReactDoctorDiagnostic, ...]


def parse_react_doctor(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    report = _NativeReactDoctorReport.model_validate_json(payload)
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for item in report.diagnostics:
        path = _react_doctor_path(item, root, root)
        rule = f"{item.plugin}/{item.rule}"
        diagnostics.append(
            Diagnostic(
                rule,
                redact_message(item.message, root),
                Severity.WARNING if item.severity == "warning" else Severity.ERROR,
                "react-doctor",
                _react_doctor_location(item, path, root, documents),
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


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
        payload: object = parse_json(Path(event_path).read_text(encoding="utf-8"))
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
        payload: object = parse_json(Path(event_path).read_text(encoding="utf-8"))
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
    if oxlint.local_binary(name, project, root) is not None or _uses_plug_n_play(project, root):
        return None
    return ExecutionIssue(name, "missing-dependency", oxlint.missing_binary_message(name, project, root))


def _uses_plug_n_play(project: Path, root: Path) -> bool:
    repository = root.resolve()
    current = project.resolve()
    while current.is_relative_to(repository):
        if (current / ".pnp.cjs").is_file() or (current / ".pnp.loader.mjs").is_file():
            return True
        if current == repository:
            break
        current = current.parent
    return False


def local_node_binary_argv(name: str, argv: Sequence[str], project: Path, root: Path) -> tuple[str, ...] | None:
    try:
        return _local_node_binary_argv(name, argv, project, root)
    except OSError:
        return None


def _local_node_binary_argv(name: str, argv: Sequence[str], project: Path, root: Path) -> tuple[str, ...]:
    binary = oxlint.local_binary(name, project, root)
    if binary is None:
        if _uses_plug_n_play(project, root):
            return tuple(argv)
        msg = f"local {name} disappeared before execution"
        raise OSError(msg)
    # A command for a project without its own install already names the binary by path.
    position = next((index for index, part in enumerate(argv) if part in {name, str(binary)}), None)
    if position is None:
        msg = f"analyzer command does not contain {name!r}"
        raise ValueError(msg)
    tail = tuple(argv[position + 1 :])
    if os.name == "nt":
        return ("cmd.exe", "/d", "/s", "/c", str(binary), *tail)
    return (str(binary), *tail)


def _invoke_python_projects(
    name: str,
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
    parser: ProtocolParser,
    project_mode: bool,
    trust: TrustMode,
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
        argv = _basedpyright_argv(project, scoped_files, project_mode=project_mode)
        project_id = InvocationId(project.relative_to(root).as_posix()) or None
        if (issue := _project_executable_trust_issue(name, argv, trust=trust, runner=runner)) is not None:
            reports.append(
                ToolReport(
                    name,
                    Completion.FAILED,
                    issues=(issue,),
                    analyzer_id=AnalyzerId(name),
                    invocation_id=InvocationId(name if project_id is None else f"{name}:{project_id}"),
                    file_count=len(scoped_files),
                )
            )
            continue
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
        reports.append(_bound_python_project_report(report, scoped_files, root=root))
    return tuple(reports)


def _bound_python_project_report(report: ToolReport, files: Sequence[str], *, root: Path) -> ToolReport:
    selected = frozenset(_relative(Path(path), root) for path in files)
    unused_helpers: dict[Path, frozenset[int] | None] = {}
    diagnostics = tuple(
        bounded
        for diagnostic in report.diagnostics
        if diagnostic.location.path in selected
        and (bounded := _bounded_python_diagnostic(diagnostic, root=root, helpers=unused_helpers)) is not None
    )
    helper_issues = tuple(
        ExecutionIssue(
            report.name,
            "helper-source-inconclusive",
            f"Cannot bound unused helper evidence for {_relative(path, root)}",
        )
        for path, lines in unused_helpers.items()
        if lines is None
    )
    return replace(
        report,
        completion=Completion.PARTIAL
        if helper_issues and report.completion is Completion.COMPLETE
        else report.completion,
        diagnostics=diagnostics,
        issues=(*report.issues, *helper_issues),
    )


def _basedpyright_argv(project: Path, files: Sequence[str], *, project_mode: bool) -> tuple[str, ...]:
    arguments = (_project_analyzer(project, "basedpyright"), "--outputjson")
    if project_mode:
        return arguments
    return (*arguments, "--baselinemode=discard", *files)


def _invoke_ruff_projects(
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    for project, config, scoped_files in ruff_project_groups(files, root):
        project_id = None if project == root else InvocationId(project.relative_to(root).as_posix())
        plan = RuffProjectPlan(root, project, config, scoped_files, project_id, runner)
        reports.append(_execute_ruff_project(plan))
    return tuple(reports)


def _execute_ruff_project(plan: RuffProjectPlan) -> ToolReport:
    report = _invoke(
        "ruff",
        _ruff_argv(plan.files, config=plan.config),
        cwd=plan.project,
        root=plan.root,
        runner=plan.executor,
        parser=parse_ruff,
        invocation_id=plan.invocation_id,
        file_count=len(plan.files),
    )
    required_files = _ruff_required_files(plan.files)
    if required_files:
        cast_report = _invoke(
            "ruff",
            _ruff_required_argv(required_files),
            cwd=plan.project,
            root=plan.root,
            runner=plan.executor,
            parser=parse_ruff,
            invocation_id=plan.invocation_id,
            file_count=len(required_files),
        )
        cast_report = _with_indirect_cast_findings(cast_report, required_files, root=plan.root)
        report = _merge_ruff_reports(report, cast_report)
    return report


def _ruff_required_files(files: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for raw_path in files:
        try:
            # Native Ruff owns binding and suppression syntax; retain every comment-bearing source.
            source = Path(raw_path).read_bytes()
            if source.isascii() and b"cast" not in source and b"typing" not in source and b"#" not in source:
                continue
        except OSError:
            pass
        selected.append(raw_path)
    return tuple(selected)


def _merge_ruff_reports(report: ToolReport, cast_report: ToolReport) -> ToolReport:
    complete = report.completion is cast_report.completion is Completion.COMPLETE
    protected = tuple(
        replace(
            finding,
            tags=(
                *finding.tags,
                "non-baselineable",
                "required-source-policy",
                *(("required-cast-policy",) if finding.rule_id in {"TID251", "banned-api"} else ()),
            ),
        )
        if finding.rule_id in {"TID251", "banned-api", "PGH003", "PGH004", "blanket-type-ignore", "blanket-noqa"}
        else finding
        for finding in cast_report.diagnostics
    )
    protected_starts = {_ruff_finding_start(finding) for finding in protected}
    findings = {
        (finding.code, finding.location): finding
        for finding in (
            *(
                finding
                for finding in report.diagnostics
                if finding.rule_id not in {"B009", "getattr-with-constant", "F403", "wildcard-import"}
                or _ruff_finding_start(finding) is None
                or _ruff_finding_start(finding) not in protected_starts
            ),
            *protected,
        )
    }
    return replace(
        report,
        completion=Completion.COMPLETE if complete else Completion.FAILED,
        diagnostics=tuple(findings.values()),
        issues=tuple(dict.fromkeys((*report.issues, *cast_report.issues))),
        duration_ms=(report.duration_ms or 0) + (cast_report.duration_ms or 0),
    )


def _ruff_finding_start(finding: Diagnostic) -> tuple[str, int, int] | None:
    region = finding.location.region
    return None if region is None else (finding.location.path, region.start.line, region.start.character)


def _with_indirect_cast_findings(report: ToolReport, files: Sequence[str], *, root: Path) -> ToolReport:
    if report.completion is not Completion.COMPLETE:
        return report
    try:
        findings = _indirect_cast_findings(files, root=root)
    except (OSError, SyntaxError, UnicodeError, ValueError, RecursionError) as exc:
        issue = ExecutionIssue("ruff", "source-proof-failure", redact_message(str(exc), root))
        return replace(report, completion=Completion.FAILED, issues=(*report.issues, issue))
    return replace(report, diagnostics=(*report.diagnostics, *findings))


def _indirect_cast_findings(files: Sequence[str], *, root: Path) -> tuple[Diagnostic, ...]:
    from sarj_python_lint.cast_access import indirect_typing_cast_accesses  # ruff: ignore[import-outside-top-level] -- only Python cast-policy inputs need source facts.

    findings: list[Diagnostic] = []
    for raw_path in files:
        path = Path(raw_path)
        raw = path.read_bytes()
        if raw.isascii() and b"typing" not in raw:
            continue
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
        document = SourceDocument(path, source)
        for access in indirect_typing_cast_accesses(path, source):
            node = access.node
            start = document.byte_point(line=node.lineno, column=node.col_offset + 1)
            end = document.byte_point(
                line=node.end_lineno or node.lineno,
                column=(node.end_col_offset if node.end_col_offset is not None else node.col_offset + 1) + 1,
            )
            if start is None or end is None:
                msg = "indirect cast access did not have a valid source region"
                raise ValueError(msg)
            if encoding != "utf-8":
                utf8 = source.encode("utf-8")
                start = replace(start, byte_offset=len(utf8[: start.byte_offset].decode("utf-8").encode(encoding)))
                end = replace(end, byte_offset=len(utf8[: end.byte_offset].decode("utf-8").encode(encoding)))
            message = (
                f"Wildcard import also imports prohibited `{access.qualified_api}`; import the required names explicitly."
                if access.kind == "wildcard"
                else f"`{access.qualified_api}` is banned even through a literal getattr lookup; use explicit narrowing or a typed contract."
            )
            findings.append(
                Diagnostic(
                    "banned-api",
                    message,
                    Severity.ERROR,
                    "ruff",
                    Location(_relative(path, root), region=Region(start, end)),
                    rule_id="banned-api",
                    notes=("Standards source proof supplements native Ruff resolution for this indirect access.",),
                )
            )
    return tuple(findings)


def _invoke_deptry_projects(
    files: Sequence[str],
    *,
    root: Path,
    runner: ProcessExecutor,
    trust: TrustMode,
) -> tuple[ToolReport, ...]:
    projects = _group_deptry_projects(files, root)
    if len(projects) > _MAX_PYTHON_PROJECTS:
        issue = ExecutionIssue(
            "deptry",
            "project-limit",
            f"selected {len(projects)} Python projects; maximum is {_MAX_PYTHON_PROJECTS}",
        )
        return (ToolReport("deptry", Completion.FAILED, issues=(issue,), analyzer_id=AnalyzerId("deptry")),)
    reports: list[ToolReport] = []
    for project, scoped_files in projects:
        started = time.monotonic()
        project_id = project.relative_to(root).as_posix() or None
        invocation_id = InvocationId("deptry" if project_id is None else f"deptry:{project_id}")
        try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary preserves complete per-project telemetry.
            argv = _deptry_argv(project, scoped_files)
            if (issue := _project_executable_trust_issue("deptry", argv, trust=trust, runner=runner)) is not None:
                reports.append(
                    ToolReport(
                        "deptry",
                        Completion.FAILED,
                        issues=(issue,),
                        analyzer_id=AnalyzerId("deptry"),
                        invocation_id=invocation_id,
                        duration_ms=round((time.monotonic() - started) * 1_000),
                        file_count=len(scoped_files),
                    )
                )
                continue
            output = runner.run(process_request(argv, cwd=project))
            payload = "\n".join(value for value in (output.stdout, output.stderr) if value)
            diagnostics = parse_deptry(payload, root=root, project=project)
            if output.returncode not in {0, 1} or (output.returncode == 1 and not diagnostics):
                message = redact_message(output.stderr.strip() or f"deptry exited {output.returncode}", root)
                issue = ExecutionIssue("deptry", "tool-failure", message, output.returncode)
                reports.append(
                    ToolReport(
                        "deptry",
                        Completion.FAILED,
                        issues=(issue,),
                        analyzer_id=AnalyzerId("deptry"),
                        invocation_id=invocation_id,
                        duration_ms=round((time.monotonic() - started) * 1_000),
                        file_count=len(scoped_files),
                    )
                )
                continue
            reports.append(
                ToolReport(
                    "deptry",
                    Completion.COMPLETE,
                    diagnostics=diagnostics,
                    analyzer_id=AnalyzerId("deptry"),
                    invocation_id=invocation_id,
                    duration_ms=round((time.monotonic() - started) * 1_000),
                    file_count=len(scoped_files),
                )
            )
        except (OSError, TypeError, ValueError, RecursionError, subprocess.SubprocessError) as exc:
            issue = ExecutionIssue("deptry", "tool-failure", redact_message(f"{type(exc).__name__}: {exc}", root))
            reports.append(
                ToolReport(
                    "deptry",
                    Completion.FAILED,
                    issues=(issue,),
                    analyzer_id=AnalyzerId("deptry"),
                    invocation_id=invocation_id,
                    duration_ms=round((time.monotonic() - started) * 1_000),
                    file_count=len(scoped_files),
                )
            )
    return tuple(reports)


def _shell_source_reports(
    grouped: GroupedPaths,
    *,
    root: Path,
    runner: ProcessExecutor,
    capabilities: frozenset[str] | None,
    attest_version: bool,
) -> tuple[ToolReport, ...]:
    from .shell_format import (  # ruff: ignore[import-outside-top-level] -- formatter reuses the bounded input runner without introducing an import cycle.
        analyze_sources as analyze_shell_format,
        attested_executable as shell_format_executable,
    )

    shellcheck = capabilities is None or "shellcheck" in capabilities
    shfmt = capabilities is None or "shfmt" in capabilities

    def shell_files() -> CachedResult:
        reports: list[ToolReport] = []
        if shellcheck:
            reports.extend(_shellcheck_reports(grouped, root=root, runner=runner, attest_version=attest_version))
        if shfmt:
            reports.extend(analyze_shell_format(root=root, paths=(*grouped.shellcheck, *grouped.unsupported_shell)))
        return CachedResult(tuple(reports))

    def shell_file_inputs() -> Iterator[str]:
        # ShellCheck follows sources only among its inputs (no -x) and shfmt
        # ignores EditorConfig when given printer flags, so these files are all
        # either tool reads.
        if executor_capabilities(runner).tool_resolution is not ToolResolution.LOCAL:
            msg = "only locally resolved shell tools have a provable identity"
            raise UnknownInputsError(msg)
        yield f"runner={type(runner).__qualname__}"
        yield f"selected=shellcheck:{shellcheck},shfmt:{shfmt},attest:{attest_version}"
        yield f"manifest={file_identity(root / manifest.MANIFEST_NAME)}"
        yield from environment_parts(_analysis_environment())
        for label, names in (("shell", grouped.shellcheck), ("zsh", grouped.unsupported_shell)):
            for name in names:
                path = Path(name) if Path(name).is_absolute() else root / name
                yield f"{label}={path.resolve().relative_to(root.resolve()).as_posix()}"
                yield file_identity(path)
        if shellcheck:
            yield f"tool=shellcheck={_tool_identity('shellcheck')}"
        if shfmt:
            yield f"tool=shfmt={executable_identity(shell_format_executable(root))}"

    reports: list[ToolReport] = []
    if grouped.shellcheck or grouped.unsupported_shell:
        reports.extend(cached_analysis("shell-files", inputs=shell_file_inputs, compute=shell_files).reports)
    reports.extend(_embedded_shell_reports(grouped, root=root, capabilities=capabilities))
    return tuple(reports)


def _tool_identity(name: str) -> str:
    executable = _analyzer_executable(name)
    if executable is None:
        msg = f"{name} is not installed"
        raise UnknownInputsError(msg)
    return executable_identity(Path(executable))


def _embedded_shell_reports(
    grouped: GroupedPaths, *, root: Path, capabilities: frozenset[str] | None
) -> tuple[ToolReport, ...]:
    from .embedded_shell import analyze_sources as analyze_embedded  # ruff: ignore[import-outside-top-level] -- stdin adapters reuse this module's protocol parser and bounded process runner.

    selected = frozenset({"shellcheck", "shfmt"}) if capabilities is None else capabilities & {"shellcheck", "shfmt"}
    if not selected:
        return ()
    paths = tuple(path for path in grouped.text if path not in {*grouped.shellcheck, *grouped.unsupported_shell})
    return analyze_embedded(root=root, paths=paths, selected=selected)


def _shellcheck_reports(
    grouped: GroupedPaths, *, root: Path, runner: ProcessExecutor, attest_version: bool
) -> tuple[ToolReport, ...]:
    plan = ShellCheckFamilyPlan(
        root, tuple(grouped.shellcheck), tuple(grouped.unsupported_shell), attest_version, runner
    )
    return _execute_shellcheck_family(plan)


def _execute_shellcheck_family(plan: ShellCheckFamilyPlan) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    if plan.unsupported_files:
        issue = ExecutionIssue(
            "shellcheck",
            "coverage-missing",
            f"ShellCheck does not support zsh; {len(plan.unsupported_files)} selected zsh path(s) were not analyzed",
        )
        reports.append(
            ToolReport(
                "shellcheck",
                Completion.FAILED,
                issues=(issue,),
                analyzer_id=AnalyzerId("shellcheck"),
                invocation_id=InvocationId("shellcheck:zsh"),
                file_count=len(plan.unsupported_files),
            )
        )
    if not plan.files:
        return tuple(reports)
    version_issue = _shellcheck_version_issue(plan.root, runner=plan.executor) if plan.attest_version else None
    if version_issue is not None:
        reports.append(
            ToolReport(
                "shellcheck",
                Completion.FAILED,
                issues=(version_issue,),
                analyzer_id=AnalyzerId("shellcheck"),
                invocation_id=InvocationId("shellcheck:version"),
                file_count=len(plan.files),
            )
        )
        return tuple(reports)
    for batch_number, start in enumerate(range(0, len(plan.files), _SHELLCHECK_BATCH_SIZE), start=1):
        batch = tuple(sorted(plan.files[start : start + _SHELLCHECK_BATCH_SIZE]))
        reports.append(
            _invoke_shellcheck(
                batch, root=plan.root, runner=plan.executor, invocation_id=InvocationId(str(batch_number))
            )
        )
    return tuple(reports)


def _invoke_shellcheck(
    files: Sequence[str], *, root: Path, runner: ProcessExecutor, invocation_id: InvocationId
) -> ToolReport:
    report = _invoke(
        "shellcheck",
        (
            "shellcheck",
            *SHELLCHECK_ARGS,
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


def _shellcheck_version_issue(root: Path, *, runner: ProcessExecutor = DEFAULT_EXECUTOR) -> ExecutionIssue | None:
    try:
        output = runner.run(process_request(("shellcheck", "--version"), cwd=root, timeout_seconds=5))
    except (OSError, subprocess.SubprocessError) as exc:
        return ExecutionIssue("shellcheck", "missing-dependency", redact_message(str(exc), root))
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


def _project_executable_trust_issue(
    name: str, argv: Sequence[str], *, trust: TrustMode, runner: ProcessExecutor
) -> ExecutionIssue | None:
    if (
        trust is TrustMode.SAFE
        and executor_capabilities(runner).tool_resolution is ToolResolution.LOCAL
        and argv[0] != name
    ):
        return ExecutionIssue(
            name,
            "trust-required",
            f"{name} project executable runs repository code; retry with --trust-repository-code",
        )
    return None


def _group_python_projects(files: Sequence[str], root: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    fallback = _adopted_python_project(root)
    nearest = cache(
        partial(_nearest_analyzer_project, root=root, fallback=fallback, has_tool=cache(_pyproject_has_tool))
    )
    grouped: dict[Path, list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        project = nearest(path.parent)
        grouped.setdefault(project, []).append(str(path))
    return tuple(
        (project, tuple(sorted(scoped_files)))
        for project, scoped_files in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _nearest_analyzer_project(
    start: Path,
    root: Path,
    *,
    fallback: Path | None = None,
    has_tool: Callable[[Path, Sequence[str]], bool] | None = None,
) -> Path:
    configured = _nearest_configured_python_project(start, root, names=("pyright", "basedpyright"), has_tool=has_tool)
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


def ruff_project_groups(files: Sequence[str], root: Path) -> tuple[tuple[Path, Path | None, tuple[str, ...]], ...]:
    fallback = _adopted_python_config(root)
    nearest = cache(partial(_nearest_ruff_config, root=root, has_tool=cache(_pyproject_has_tool)))
    grouped: dict[tuple[Path, Path | None], list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        nearest_config = nearest(path.parent)
        config = nearest_config or fallback
        project = root if nearest_config is None else nearest_config.parent
        grouped.setdefault((project, config), []).append(str(path))
    return tuple(
        (project, config, tuple(sorted(scoped_files)))
        for (project, config), scoped_files in sorted(grouped.items(), key=lambda item: str(item[0][0]))
    )


def _group_deptry_projects(files: Sequence[str], root: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    nearest = cache(
        partial(_nearest_deptry_project, root=root, has_specification=cache(_has_deptry_dependency_specification))
    )
    grouped: dict[Path, list[str]] = {}
    for raw_file in files:
        path = Path(raw_file).resolve()
        project = nearest(path.parent)
        if project is None:
            continue
        grouped.setdefault(project, []).append(str(path))
    return tuple(
        (project, tuple(sorted(scoped_files)))
        for project, scoped_files in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _nearest_deptry_project(start: Path, root: Path, *, has_specification: Callable[[Path], bool]) -> Path | None:
    current = start
    while current.is_relative_to(root):
        if has_specification(current):
            return current
        if current == root:
            break
        current = current.parent
    return None


def _has_deptry_dependency_specification(project: Path) -> bool:
    if any((project / name).is_file() for name in ("requirements.txt", "requirements-dev.txt", "dev-requirements.txt")):
        return True
    pyproject = project / "pyproject.toml"
    try:
        parsed: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return False
    document = manifest.as_table(parsed)
    if isinstance(document.get("project"), dict):
        return True
    tool = manifest.as_table(document.get("tool"))
    if isinstance(tool.get("pdm"), dict):
        return True
    poetry = manifest.as_table(tool.get("poetry"))
    return isinstance(poetry.get("dependencies"), dict)


def _nearest_ruff_config(
    start: Path, root: Path, *, has_tool: Callable[[Path, Sequence[str]], bool] | None = None
) -> Path | None:
    probe = _pyproject_has_tool if has_tool is None else has_tool
    current = start
    while current.is_relative_to(root):
        for name in (".ruff.toml", "ruff.toml"):
            candidate = current / name
            if candidate.is_file():
                return candidate
        pyproject = current / "pyproject.toml"
        if pyproject.is_file() and probe(pyproject, ("ruff",)):
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


def _nearest_configured_python_project(
    start: Path,
    root: Path,
    *,
    names: Sequence[str],
    has_tool: Callable[[Path, Sequence[str]], bool] | None = None,
) -> Path | None:
    probe = _pyproject_has_tool if has_tool is None else has_tool
    current = start
    while current.is_relative_to(root):
        if (current / "pyrightconfig.json").is_file() or (current / "pyrightconfig.jsonc").is_file():
            return current
        pyproject = current / "pyproject.toml"
        if pyproject.is_file() and probe(pyproject, names):
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


def _run_staged_process(request: ProcessRequest, *, index_file: str) -> ProcessOutput:
    environment = dict(request.environment)
    environment["GIT_INDEX_FILE"] = index_file
    return DEFAULT_EXECUTOR.run(replace(request, environment=environment))


def run_process(argv: Sequence[str], *, cwd: Path, timeout_seconds: float = _TIMEOUT.total_seconds()) -> ProcessOutput:
    return DEFAULT_EXECUTOR.run(process_request(argv, cwd=cwd, timeout_seconds=timeout_seconds))


def process_request(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float = _TIMEOUT.total_seconds(),
    deadline: float | None = None,
    environment: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
    max_input_bytes: int | None = None,
) -> ProcessRequest:
    return ProcessRequest(
        tuple(argv),
        cwd,
        _analysis_environment() if environment is None else environment,
        timeout_seconds=timeout_seconds,
        deadline=deadline,
        input_bytes=input_bytes,
        max_input_bytes=max_input_bytes,
        max_stdout_bytes=_MAX_STDOUT_BYTES,
        max_stderr_bytes=_MAX_STDERR_BYTES,
    )


def run_process_input(argv: Sequence[str], *, cwd: Path, source: str, timeout_seconds: float = 10) -> ProcessOutput:
    if len(source.encode("utf-8")) > 1024 * 1024:
        msg = "analyzer source exceeds the 1 MiB input limit"
        raise OutputLimitError(msg)
    return DEFAULT_EXECUTOR.run(
        process_request(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=source.encode("utf-8"),
            max_input_bytes=1024 * 1024,
        )
    )


def _node_options() -> str:
    memory = _physical_memory_bytes()
    if memory is None:
        return _NODE_OPTIONS
    paths = _cgroup_memory_limit_files()
    if paths is None:
        return _NODE_OPTIONS
    found_limit = False
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        except OSError:
            return _NODE_OPTIONS
        found_limit = True
        if text == "max":
            continue
        try:
            limit = int(text)
        except ValueError:
            return _NODE_OPTIONS
        if limit <= 0:
            return _NODE_OPTIONS
        memory = min(memory, limit)
    if sys.platform == "linux" and not found_limit:
        return _NODE_OPTIONS
    return _LARGE_NODE_OPTIONS if memory >= _LARGE_HOST_MEMORY else _NODE_OPTIONS


def _cgroup_memory_limit_files() -> list[Path] | None:
    paths = list(_CGROUP_MEMORY_LIMIT_FILES)
    if sys.platform != "linux":
        return paths
    try:
        groups = _PROCESS_CGROUPS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in groups:
        fields = line.split(":", 2)
        if len(fields) != _CGROUP_RECORD_FIELDS:
            return None
        hierarchy, controllers, group = fields
        if hierarchy == "0" and not controllers:
            root, filename = _CGROUP_ROOT, "memory.max"
        elif "memory" in controllers.split(","):
            root, filename = _CGROUP_ROOT / "memory", "memory.limit_in_bytes"
        else:
            continue
        relative = PurePosixPath(group)
        if not relative.is_absolute() or ".." in relative.parts:
            return None
        directory = root.joinpath(*relative.parts[1:])
        paths.extend(parent / filename for parent in (directory, *directory.parents) if parent.is_relative_to(root))
    return list(dict.fromkeys(paths))


def _physical_memory_bytes() -> int | None:
    if sys.platform == "win32":
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except AttributeError, OSError, ValueError:
        return None


def _run_process(request: ProcessRequest) -> ProcessOutput:
    raise_if_cancelled(request.cancellation)
    if request.deadline is not None and time.monotonic() >= request.deadline:
        raise subprocess.TimeoutExpired(request.argv, 0)
    executable = _analyzer_executable(request.argv[0])
    if executable is None:
        msg = f"required analyzer executable is missing: {request.argv[0]}"
        raise FileNotFoundError(msg)
    with contextlib.ExitStack() as resources:
        stdin = None
        if request.input_bytes is not None:
            stdin = resources.enter_context(tempfile.TemporaryFile())
            stdin.write(request.input_bytes)
            stdin.seek(0)
        raise_if_cancelled(request.cancellation)
        process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv and shell stays disabled.
            [executable, *request.argv[1:]],
            cwd=request.cwd,
            shell=False,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Deliver available bytes so a held-open pipe cannot hide an overflow.
            bufsize=0,
            start_new_session=os.name == "posix",
            env=request.environment,
        )
    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:  # pragma: no cover - PIPE guarantees streams.
        _terminate_process(process)
        process.wait(timeout=5)
        msg = "analyzer process did not expose output pipes"
        raise OSError(msg)
    exceeded = threading.Event()
    captures: list[bytes | None] = [None, None]
    threads = (
        threading.Thread(
            target=_capture_stream,
            args=(stdout, request.max_stdout_bytes, exceeded, captures, 0),
            name=f"sarj-process-{process.pid}-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_capture_stream,
            args=(stderr, request.max_stderr_bytes, exceeded, captures, 1),
            name=f"sarj-process-{process.pid}-stderr",
            daemon=True,
        ),
    )
    try:
        _start_capture_threads(threads)
        returncode = _wait_for_process(process, threads, exceeded, request)
    except BaseException as error:
        try:
            # A completed leader wait follows stream closure. Its numeric group
            # must not be signaled again after reaping releases leader ownership.
            if process.returncode is None:
                _terminate_process(process)
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError) as cleanup_error:
            error.add_note(f"analyzer process cleanup failed: {cleanup_error}")
        try:
            _join_capture_threads(threads)
        except OSError as cleanup_error:
            error.add_note(f"analyzer stream cleanup failed: {cleanup_error}")
        raise
    if exceeded.is_set():
        msg = f"analyzer output exceeded the {request.max_stdout_bytes} byte stdout or {request.max_stderr_bytes} byte stderr limit"
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


def analysis_environment() -> dict[str, str]:
    return _analysis_environment()


def _analysis_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()  # ruff: ignore[banned-api] -- deliberately reduce inherited environment.
        if key in _SAFE_ENVIRONMENT_KEYS or key.startswith("LC_")
    }
    environment["TFLINT_DISABLE_VERSION_CHECK"] = "true"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _start_capture_threads(threads: Sequence[threading.Thread]) -> None:
    for thread in threads:
        thread.start()


def _wait_for_process(
    process: subprocess.Popen[bytes],
    threads: Sequence[threading.Thread],
    exceeded: threading.Event,
    request: ProcessRequest,
) -> int:
    started = time.monotonic()
    deadline = started + request.timeout_seconds
    if request.deadline is not None:
        deadline = min(deadline, request.deadline)
    while not exceeded.is_set():
        raise_if_cancelled(request.cancellation)
        exited = _leader_exited(process)
        if exited is not False and all(not thread.is_alive() for thread in threads):
            if exceeded.is_set():
                break
            try:
                return process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as error:
                raise subprocess.TimeoutExpired(request.argv, max(0.0, deadline - started)) from error
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(request.argv, max(0.0, deadline - started))
        _output_limit_reached = exceeded.wait(0.01)
    message = f"analyzer output exceeded the {request.max_stdout_bytes} byte stdout or {request.max_stderr_bytes} byte stderr limit"
    raise OutputLimitError(message)


def _leader_exited(process: subprocess.Popen[bytes]) -> bool | None:
    if (
        os.name == "posix"
        and hasattr(  # sarj-noqa: SARJ499 -- Probe optional POSIX wait APIs before preserving an unreaped process-group leader.
            os, "waitid"
        )
        and hasattr(  # sarj-noqa: SARJ499 -- Probe optional POSIX wait APIs before preserving an unreaped process-group leader.
            os, "WNOWAIT"
        )
    ):
        # Keep the leader unreaped while descendants can own output streams.
        # Its reserved PID makes later process-group cleanup safe from PID reuse.
        return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    # Without a non-reaping exit probe, preserve the child identity until both
    # streams close or the request fails. The caller then waits with its deadline.
    return None


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
        if thread.ident is not None:
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
    runner: ProcessExecutor,
    parser: ProtocolParser,
    execution_parser: RuleExecutionParser | None = None,
    validator: ProtocolValidator | None = None,
    invocation_id: InvocationId | None = None,
    file_count: int,
    version: str | None = None,
    input_bytes: bytes | None = None,
) -> ToolReport:
    started = time.monotonic()
    try:
        report = _invoke_unchecked(
            name,
            argv,
            cwd=cwd,
            root=root,
            runner=runner,
            parser=parser,
            validator=validator,
            execution_parser=execution_parser,
            file_count=file_count,
            input_bytes=input_bytes,
        )
        return ToolReport(
            report.name,
            report.completion,
            diagnostics=report.diagnostics,
            issues=report.issues,
            rule_executions=report.rule_executions,
            analyzer_id=AnalyzerId(name),
            invocation_id=InvocationId(name if invocation_id is None else f"{name}:{invocation_id}"),
            duration_ms=round((time.monotonic() - started) * 1_000),
            file_count=file_count,
            version=version if report.completion is Completion.COMPLETE else None,
        )
    except (OSError, TypeError, ValueError, RecursionError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        message = redact_message(f"{type(exc).__name__}: {exc}", root)
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
    runner: ProcessExecutor,
    parser: ProtocolParser,
    execution_parser: RuleExecutionParser | None = None,
    validator: ProtocolValidator | None = None,
    file_count: int | None = None,
    input_bytes: bytes | None = None,
) -> ToolReport:
    output = runner.run(process_request(argv, cwd=cwd, input_bytes=input_bytes, max_input_bytes=_MAX_STDOUT_BYTES))
    if output.returncode not in {0, 1}:
        message = redact_message(output.stderr.strip() or f"{name} exited {output.returncode}", root)
        issue = ExecutionIssue(name, "tool-failure", message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    if not output.stdout.strip():
        stderr = output.stderr.strip()
        kind = "tool-failure" if stderr else "protocol-mismatch"
        message = redact_message(stderr or f"{name} returned empty structured output", root)
        issue = ExecutionIssue(name, kind, message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    try:
        diagnostics = parser(output.stdout, root=root)
    except json.JSONDecodeError as exc:
        stderr = output.stderr.strip()
        message = stderr or f"{name} returned invalid structured JSON at line {exc.lineno}, column {exc.colno}"
        issue = ExecutionIssue(name, "protocol-mismatch", redact_message(message, root), output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    if output.returncode == 1 and not diagnostics:
        message = redact_message(output.stderr.strip() or f"{name} exited 1 but reported no diagnostics", root)
        issue = ExecutionIssue(name, "protocol-mismatch", message, output.returncode)
        return ToolReport(name, Completion.FAILED, issues=(issue,))
    if validator is not None and (issue := validator(output.stdout, root=root)) is not None:
        return ToolReport(name, Completion.FAILED, diagnostics=diagnostics, issues=(issue,))
    try:
        executions = () if execution_parser is None else execution_parser(output.stdout, file_count=file_count)
    except (TypeError, ValueError, RecursionError) as exc:
        message = redact_message(f"invalid rule execution metadata: {exc}", root)
        issue = ExecutionIssue(name, "protocol-mismatch", message, output.returncode)
        return ToolReport(name, Completion.FAILED, diagnostics=diagnostics, issues=(issue,))
    if any(item.execution is RuleExecutionState.FAILED for item in executions):
        issue = ExecutionIssue(name, "incomplete-rule-execution", "one or more requested rule executions failed")
        return ToolReport(name, Completion.FAILED, diagnostics=diagnostics, issues=(issue,), rule_executions=executions)
    return ToolReport(name, Completion.COMPLETE, diagnostics=diagnostics, rule_executions=executions)


class ProtocolParser(Protocol):
    def __call__(self, payload: str, *, root: Path) -> tuple[Diagnostic, ...]: ...


class RuleExecutionParser(Protocol):
    def __call__(self, payload: str, *, file_count: int | None = None) -> tuple[RuleExecution, ...]: ...


class ProtocolValidator(Protocol):
    def __call__(self, payload: str, *, root: Path) -> ExecutionIssue | None: ...


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
        code_value = item.get("code")
        code = code_value if isinstance(code_value, str) and code_value else _text(item, "name")
        url_value = item.get("url")
        help_url = url_value if isinstance(url_value, str) else None
        diagnostics.append(
            Diagnostic(
                code,
                redact_message(_text(item, "message"), root),
                Severity.ERROR,
                "ruff",
                Location(_relative(path, root), region=Region(start, end)),
                rule_id=code,
                help_url=help_url,
            )
        )
    return tuple(diagnostics)


def parse_deptry(payload: str, *, root: Path, project: Path | None = None) -> tuple[Diagnostic, ...]:
    documents: dict[Path, SourceDocument | None] = {}
    diagnostics: list[Diagnostic] = []
    for raw_line in payload.splitlines():
        match = _DEPTRY_ANNOTATION_RE.fullmatch(raw_line.strip())
        if match is None:
            continue
        path = ((project or root) / _github_command_unescape(match.group("file"))).resolve()
        line = int(match.group("line"))
        column = int(match.group("column") or "1")
        position = _one_based_position({"row": line, "column": column}, path, documents)
        code = match.group("code")
        diagnostics.append(
            Diagnostic(
                code,
                redact_message(_github_command_unescape(match.group("message")), root),
                Severity.WARNING,
                "deptry",
                Location(_relative(path, root), position=position),
                rule_id=code,
                help_url=f"https://deptry.com/rules-violations/#{code.casefold()}",
            )
        )
    return tuple(diagnostics)


def _github_command_unescape(value: str) -> str:
    replacements = (("%0D", "\r"), ("%0A", "\n"), ("%3A", ":"), ("%2C", ","), ("%25", "%"))
    result = value
    for encoded, decoded in replacements:
        result = result.replace(encoded, decoded).replace(encoded.casefold(), decoded)
    return result


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
                redact_message(match.group("message"), root),
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
                redact_message(_text(item, "reason"), root),
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
                    redact_message(message_value, root),
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
    report = _JsonToolReport.model_validate_json(payload, strict=True).root
    errors = _array(report.get("errors", []), "mobsfscan errors")
    if expected_paths is not None:
        _validate_mobsfscan_coverage(report, root, expected_paths)
    # Semgrep 1.177.0 does not yet parse Swift's `#Preview` macro. It reports a
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
                redact_message(_text(extra, "message"), root),
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
    report = _JsonToolReport.model_validate_json(payload, strict=True).root
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
                    redact_message(message, root),
                    severity,
                    "detekt",
                    Location(_relative(path, root), position=position),
                    rule_id=rule,
                )
            )
    return tuple(diagnostics)


def parse_basedpyright(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    notice, separator, report_payload = payload.partition("\n\n")
    if separator and (
        _BASEDPYRIGHT_BASELINE_SHRINK_RE.fullmatch(notice) or _BASEDPYRIGHT_BASELINE_DISCARD_RE.fullmatch(notice)
    ):
        payload = report_payload
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
                redact_message(item.message, root),
                _severity_text(item.severity),
                "basedpyright",
                location,
                rule_id=rule,
            )
        )
    return tuple(diagnostics)


def _bounded_python_diagnostic(
    diagnostic: Diagnostic, *, root: Path, helpers: dict[Path, frozenset[int] | None]
) -> Diagnostic | None:
    if diagnostic.rule_id != "reportUnusedFunction":
        return diagnostic
    path = root / diagnostic.location.path
    if not _PYTHON_TEST_PATHS.match_file(_relative(path, root)):
        return diagnostic
    region = diagnostic.location.region
    if not accepts_hook_path(path, root=root):
        return None
    if region is None:
        helpers[path] = None
        return None
    if path not in helpers:
        helpers[path] = _private_helper_lines(path)
    lines = helpers[path]
    if lines is None or region.start.line + 1 not in lines:
        return None
    return replace(diagnostic, severity=Severity.WARNING)


def _private_helper_lines(path: Path) -> frozenset[int] | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, SyntaxError:
        return None
    return frozenset(
        node.lineno
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_")
        and not node.name.endswith("__")
        and not node.decorator_list
    )


def parse_shellcheck(
    payload: str, *, root: Path, source: SourceDocument | None = None, path: Path | None = None
) -> tuple[Diagnostic, ...]:
    report = _ShellCheckReport.model_validate_json(payload)
    documents = _shellcheck_documents(root, source, path)
    virtual = None if path is None else path.resolve()
    diagnostics: list[Diagnostic] = []
    for item in report.comments:
        path = _shellcheck_reported_path(item.file, root, virtual)
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
                redact_message(item.message, root),
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


def _shellcheck_documents(
    root: Path, source: SourceDocument | None, path: Path | None
) -> dict[Path, SourceDocument | None]:
    if source is None and path is None:
        return {}
    if source is None or path is None:
        message = "embedded ShellCheck input requires a source document and authored path"
        raise ValueError(message)
    return {_reported_path(str(path), root): source}


def _shellcheck_reported_path(value: str, root: Path, virtual: Path | None) -> Path:
    if virtual is None:
        return _reported_path(value, root)
    if value != "-":
        message = "embedded ShellCheck output must refer to stdin"
        raise ValueError(message)
    return virtual


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
    if item.source_position is not None:
        position = item.source_position
        return Location(relative_path, position=Position(position.line, position.character, position.byte_offset))
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
    return ("ruff", "check", "--output-format", "json", *ruff_config_arguments(config), "--", *files)


def ruff_config_arguments(config: Path | None) -> tuple[str, ...]:
    return () if config is None else ("--config", str(config))


def _ruff_required_argv(files: Sequence[str]) -> tuple[str, ...]:
    return (
        "ruff",
        "check",
        "--output-format",
        "json",
        "--ignore-noqa",
        "--config",
        str(_PACKAGED_MOBILE_CONFIGS / "ruff.required.toml"),
        "--",
        *files,
    )


def _deptry_argv(project: Path, scoped_files: Sequence[str]) -> tuple[str, ...]:
    config_args = ("--config", str(project / "pyproject.toml")) if (project / "pyproject.toml").is_file() else ()
    first_party = _deptry_first_party_modules(project)
    first_party_args = tuple(value for module in first_party for value in ("--known-first-party", module))
    return (
        _project_analyzer(project, "deptry"),
        *_deptry_scan_roots(project, scoped_files),
        *config_args,
        *first_party_args,
        "--ignore",
        "DEP004,DEP005",
        "--github-output",
        "--github-warning-errors",
        "DEP001,DEP002,DEP003",
        "--no-ansi",
    )


def _deptry_scan_roots(project: Path, scoped_files: Sequence[str]) -> tuple[str, ...]:
    # DEP002 compares project dependencies with its complete import graph. A
    # selected maintenance script must also scan the package sources explicitly
    # owned by this wheel, even when those sources have a nested pyproject.
    packages = _deptry_declared_packages(project)
    roots = {package.path.relative_to(project).as_posix() for package in packages}
    for raw_file in scoped_files:
        selected = Path(raw_file).resolve()
        if any(selected.is_relative_to(package.path) for package in packages):
            continue
        relative = selected.relative_to(project)
        roots.add("." if len(relative.parts) == 1 else relative.parts[0])
    selected_roots = tuple(PurePosixPath(value) for value in roots)
    return tuple(
        sorted(
            str(path)
            for path in selected_roots
            if not any(path != other and path.is_relative_to(other) for other in selected_roots)
        )
    )


def _deptry_declared_packages(project: Path) -> tuple[_DeptryPackage, ...]:
    pyproject = project / "pyproject.toml"
    try:
        parsed: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    table = manifest.as_table(parsed)
    backend = manifest.table_field(table, "build-system").get("build-backend")
    if backend == "uv_build":
        return _deptry_uv_packages(project, table)
    if backend != "hatchling.build":
        return ()
    for key in ("tool", "hatch", "build", "targets", "wheel"):
        table = manifest.table_field(table, key)
    return tuple(
        _deptry_package(project, Path(value))
        for value in manifest.list_field(table, "packages")
        if isinstance(value, str)
    )


def _deptry_uv_packages(
    project: Path,
    table: Mapping[  # sarj-noqa: SARJ528 -- Validate raw pyproject TOML build settings.
        str, object
    ],
) -> tuple[_DeptryPackage, ...]:
    settings = manifest.table_field(manifest.table_field(table, "tool"), "uv")
    settings = manifest.table_field(settings, "build-backend")
    module_root = settings.get("module-root", "src")
    names = settings.get("module-name")
    if names is None:
        project_name = manifest.text_field(manifest.table_field(table, "project"), "name")
        if project_name is None:
            msg = "uv_build requires a project name or explicit module-name"
            raise ValueError(msg)
        names = re.sub(r"[-_.]+", "_", project_name.lower())
        if names.endswith("_stubs"):
            names = f"{names.removesuffix('_stubs')}-stubs"
    if isinstance(names, str):
        names = [names]
    if not isinstance(module_root, str) or not is_object_list(names) or not names:
        msg = "uv_build module-root must be a string and module-name a nonempty string or list of names"
        raise ValueError(msg)
    source_root = _deptry_source_path(project, Path(module_root))
    packages: list[_DeptryPackage] = []
    for name in names:
        if not isinstance(name, str):
            msg = "uv_build module-name entries must be strings"
            raise TypeError(msg)
        first, *rest = name.split(".")
        import_root = first.removesuffix("-stubs")
        if not import_root.isidentifier() or not all(part.isidentifier() for part in rest):
            msg = "uv_build module-name must contain valid dotted module names"
            raise ValueError(msg)
        packages.append(_deptry_package(project, source_root.joinpath(first, *rest), import_root))
    return tuple(packages)


def _deptry_package(project: Path, relative: Path, import_root: str | None = None) -> _DeptryPackage:
    package = _deptry_source_path(project, relative)
    return _DeptryPackage(package, package.name if import_root is None else import_root)


def _deptry_source_path(project: Path, relative: Path) -> Path:
    package = (project / relative).resolve()
    if not package.is_relative_to(project):
        msg = "declared wheel package source must stay within its Python project"
        raise ValueError(msg)
    return package


def _deptry_first_party_modules(project: Path) -> tuple[str, ...]:
    roots = (project / "src", project)
    names = {
        package.import_root for package in _deptry_declared_packages(project) if package.import_root.isidentifier()
    }
    for source_root in roots:
        if not source_root.is_dir():
            continue
        for candidate in source_root.iterdir():
            if candidate.is_dir() and (candidate / "__init__.py").is_file() and candidate.name.isidentifier():
                names.add(candidate.name)
            elif candidate.is_file() and candidate.suffix == ".py" and candidate.stem.isidentifier():
                names.add(candidate.stem)
    return tuple(sorted(names))


def _loads(payload: str) -> JsonValue:
    if not payload.strip():
        msg = "analyzer returned empty structured output"
        raise ValueError(msg)
    return parse_json(payload)


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
    if not is_object_mapping(value):
        msg = f"{label} must be an object"
        raise TypeError(msg)
    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        table[key] = item
    return table


def _array(
    value: object, label: str
) -> list[  # sarj-noqa: SARJ528 -- Copy the list while preserving unchecked element values.
    object
]:
    if not is_object_list(value):
        msg = f"{label} must be an array"
        raise TypeError(msg)
    return list(value)


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


def redact_message(value: str, root: Path) -> str:
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


def _validate_mobsfscan_coverage(report: dict[str, object], root: Path, expected_paths: Sequence[str]) -> None:
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
