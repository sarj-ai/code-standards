from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- only catch bounded runner timeout failures.
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    SourceDocument,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool, invoke
from sarj_standards.libs.linting.external import ProcessOutput, ProcessRunner, run_process
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Callable

SUPPORTED: Final = frozenset({"actionlint", "hadolint", "terraform", "tflint", "compose"})
_ACTION_FORMAT: Final = "{{json .}}"
_CONFIGS: Final = Path(__file__).resolve().parents[2] / "configs"
_GOOGLE_PLUGIN: Final = re.compile(r"ruleset.google \(0\.39\.0\)")
_MISSING_TERRAFORM_INPUTS: Final = frozenset(
    {"Missing required provider", "Module not installed", "Required plugins are not installed"}
)


@dataclass(frozen=True, slots=True)
class SourcePaths:
    workflows: tuple[Path, ...]
    dockerfiles: tuple[Path, ...]
    terraform: tuple[Path, ...]
    compose: tuple[Path, ...]


def analyze_sources(
    *,
    root: Path,
    paths: tuple[str, ...],
    selected: frozenset[str] = SUPPORTED,
    trust_repository_code: bool = False,
    runner: ProcessRunner = run_process,
    compose_version: str | None = None,
) -> tuple[ToolReport, ...]:
    root = root.resolve()
    sources = _select_sources(root, paths)
    reports: list[ToolReport] = []
    if "actionlint" in selected and sources.workflows:
        reports.append(_actionlint_report(root, sources.workflows, runner))
    if "hadolint" in selected and sources.dockerfiles:
        reports.append(
            _json_tool(
                "hadolint",
                (
                    "--format",
                    "json",
                    "--config",
                    str(_CONFIGS / "hadolint.strict.yaml"),
                    "--no-color",
                    "--disable-ignore-pragma",
                    *map(str, sources.dockerfiles),
                ),
                root,
                sources.dockerfiles,
                parse_hadolint,
                runner=runner,
            )
        )
    if "terraform" in selected and sources.terraform:
        reports.extend(_terraform_reports(root, sources.terraform, runner, trust_repository_code=trust_repository_code))
    if "tflint" in selected and sources.terraform:
        reports.extend(_tflint_reports(root, sources.terraform, runner, trust_repository_code=trust_repository_code))
    if "compose" in selected:
        reports.extend(_compose_reports(root, sources.compose, runner, version=compose_version))
    return tuple(reports)


def _select_sources(root: Path, paths: tuple[str, ...]) -> SourcePaths:
    inputs = tuple(_contained(root, path) for path in paths)
    return SourcePaths(
        workflows=tuple(
            path
            for path in inputs
            if path.suffix in {".yml", ".yaml"} and ".github/workflows/" in path.relative_to(root).as_posix()
        ),
        dockerfiles=tuple(
            path
            for path in inputs
            if not path.name.lower().endswith(".dockerignore")
            and (
                path.name.lower() == "dockerfile"
                or path.name.lower().startswith("dockerfile.")
                or path.name.lower().endswith(".dockerfile")
            )
        ),
        terraform=tuple(path for path in inputs if path.suffix == ".tf" or path.name.endswith(".tf.json")),
        compose=tuple(
            path
            for path in inputs
            if path.name in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
        ),
    )


def _compose_reports(
    root: Path, paths: tuple[Path, ...], runner: ProcessRunner, *, version: str | None
) -> tuple[ToolReport, ...]:
    if not paths:
        return ()
    if version is None:
        from sarj_standards.libs.adoption import manifest  # ruff: ignore[import-outside-top-level] -- resolve the consumer contract after adoption initialization.

        adopted = manifest.load(root)
        version = None if adopted is None else adopted.compose_version
    return tuple(_compose_report(root, path, runner, version=version) for path in paths)


def _actionlint_report(root: Path, paths: tuple[Path, ...], runner: ProcessRunner) -> ToolReport:
    try:
        shellcheck = checked_tool("shellcheck", root=root, runner=runner)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return _failed("actionlint", error, len(paths))
    shellcheck_path = (
        str(shellcheck.executable)
        if shellcheck.executable is not None
        else shutil.which(shellcheck.name) or shellcheck.name
    )
    return _json_tool(
        "actionlint",
        (
            "-format",
            _ACTION_FORMAT,
            "-config-file",
            str(_CONFIGS / "actionlint.strict.yaml"),
            f"-shellcheck={shellcheck_path}",
            "-pyflakes=",
            *map(str, paths),
        ),
        root,
        paths,
        parse_actionlint,
        runner=runner,
    )


def _json_tool(
    name: str,
    args: tuple[str, ...],
    root: Path,
    paths: tuple[Path, ...],
    parser: Callable[[str, Path], tuple[Diagnostic, ...]],
    *,
    runner: ProcessRunner,
) -> ToolReport:
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary normalizes native execution and structured protocol failures.
        tool = checked_tool(name, root=root, runner=runner)
        output = invoke(tool, args, root=root, runner=runner)
        payload = output.stdout
        # actionlint does not render its error template on a clean invocation.
        if not payload.strip() and name == "actionlint" and output.returncode == 0:
            payload = "[]"
        findings = parser(payload, root)
        if output.returncode and not findings:
            message = f"{name} reported findings without structured diagnostics"
            raise NativeToolError(message)
        return ToolReport(name, Completion.COMPLETE, diagnostics=findings, version=tool.version, file_count=len(paths))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return _failed(name, error, len(paths))


def parse_actionlint(payload: str, root: Path) -> tuple[Diagnostic, ...]:
    return tuple(
        _diagnostic(
            "actionlint",
            _text(item, "kind"),
            _text(item, "message"),
            _text(item, "filepath"),
            root,
            line=_integer(item, "line"),
            column=_integer(item, "column"),
            byte_column=True,
        )
        for item in _records(parse_json(payload))
    )


def parse_hadolint(payload: str, root: Path) -> tuple[Diagnostic, ...]:
    records = _records(parse_json(payload))
    for item in records:
        if item.get("level") not in {"error", "warning", "info", "style", "ignore"}:
            message = "Hadolint reported an unknown severity"
            raise ValueError(message)
    return tuple(
        _diagnostic(
            "hadolint",
            _text(item, "code"),
            _text(item, "message"),
            _text(item, "file"),
            root,
            line=_integer(item, "line"),
            column=_integer(item, "column"),
        )
        for item in records
    )


def parse_tflint(payload: str, root: Path, *, cwd: Path | None = None) -> tuple[Diagnostic, ...]:
    report = _table(parse_json(payload))
    errors = _records(report.get("errors"))
    if errors:
        message = "TFLint reported configuration or execution errors"
        raise NativeToolError(message)
    diagnostics: list[Diagnostic] = []
    for item in _records(report.get("issues")):
        rule, region = _table(item.get("rule")), _table(item.get("range"))
        point = _table(region.get("start"))
        if rule.get("severity") not in {"error", "warning", "notice"}:
            message = "TFLint reported an unknown severity"
            raise ValueError(message)
        diagnostics.append(
            _diagnostic(
                "tflint",
                _text(rule, "name"),
                _text(item, "message"),
                str((cwd or root) / _text(region, "filename")),
                root,
                line=_integer(point, "line"),
                column=_integer(point, "column"),
                byte_column=True,
            )
        )
    return tuple(diagnostics)


def parse_terraform(payload: str, root: Path, *, cwd: Path | None = None) -> tuple[Diagnostic, ...]:
    report = _table(parse_json(payload))
    if not isinstance(report.get("valid"), bool) or report.get("format_version") != "1.0":
        message = "Terraform validation report must declare validity and a supported format"
        raise ValueError(message)
    diagnostics: list[Diagnostic] = []
    for item in _records(report.get("diagnostics")):
        summary = _text(item, "summary")
        if summary in _MISSING_TERRAFORM_INPUTS:
            raise NativeToolError(summary)
        if item.get("severity") not in {"error", "warning"}:
            message = "Terraform reported an unknown severity"
            raise ValueError(message)
        region = item.get("range")
        if region is None:
            diagnostics.append(
                Diagnostic(
                    "validate",
                    summary,
                    Severity.ERROR,
                    "terraform",
                    Location((cwd or root).relative_to(root).as_posix()),
                    rule_id="validate",
                )
            )
        else:
            location = _table(region)
            start = _table(location.get("start"))
            diagnostics.append(
                _diagnostic(
                    "terraform",
                    "validate",
                    summary,
                    str((cwd or root) / _text(location, "filename")),
                    root,
                    line=_integer(start, "line"),
                    column=_integer(start, "column"),
                    byte_column=True,
                )
            )
    error_count = _integer(report, "error_count", minimum=0)
    if (
        error_count != sum(item.get("severity") == "error" for item in _records(report.get("diagnostics")))
        or bool(error_count) == report["valid"]
    ):
        message = "Terraform validity and error count disagree"
        raise ValueError(message)
    return tuple(diagnostics)


def _terraform_reports(
    root: Path, paths: tuple[Path, ...], runner: ProcessRunner, *, trust_repository_code: bool
) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    formatting_paths = tuple(path for path in paths if path.suffix == ".tf")
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary owns read-only formatting protocol.
        tool = checked_tool("terraform", root=root, runner=runner)
        output = (
            invoke(
                replace(tool, finding_exits=frozenset({3})),
                ("fmt", "-check", "-list=true", *map(str, formatting_paths)),
                root=root,
                runner=runner,
            )
            if formatting_paths
            else ProcessOutput(0, "", "")
        )
        changed = tuple(_contained(root, path) for path in output.stdout.splitlines() if path.strip())
        if bool(changed) != (output.returncode != 0) or any(path not in formatting_paths for path in changed):
            message = "Terraform fmt exit and selected path list disagree"
            raise NativeToolError(message)
        findings = tuple(
            Diagnostic(
                "fmt",
                "Run terraform fmt on this file",
                Severity.ERROR,
                "terraform",
                Location(path.relative_to(root).as_posix()),
                rule_id="fmt",
            )
            for path in changed
        )
        reports.append(
            ToolReport(
                "terraform-fmt",
                Completion.COMPLETE,
                diagnostics=findings,
                version=tool.version,
                file_count=len(formatting_paths),
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        reports.append(_failed("terraform-fmt", error, len(paths)))
    for project in sorted({path.parent for path in paths}):
        if not trust_repository_code:
            reports.append(
                _failed(
                    "terraform-validate",
                    "Terraform provider validation requires trusted repository code and preinitialized local providers",
                    len(paths),
                )
            )
            continue
        reports.append(
            _json_tool(
                "terraform",
                ("validate", "-json", "-no-color"),
                project,
                paths,
                lambda payload, project_root: parse_terraform(payload, root, cwd=project_root),
                runner=runner,
            )
        )
    return tuple(reports)


def _tflint_reports(
    root: Path, paths: tuple[Path, ...], runner: ProcessRunner, *, trust_repository_code: bool
) -> tuple[ToolReport, ...]:
    if not trust_repository_code:
        return (
            _failed(
                "tflint", "TFLint requires trusted repository configuration and installed pinned plugins", len(paths)
            ),
        )
    return tuple(_tflint_report(root, project, paths, runner) for project in sorted({path.parent for path in paths}))


def _tflint_report(root: Path, project: Path, paths: tuple[Path, ...], runner: ProcessRunner) -> ToolReport:
    config = str(_CONFIGS / "tflint.strict.hcl")
    try:
        tool = checked_tool("tflint", root=project, runner=runner)
        version = invoke(tool, ("--config", config, "--version"), root=project, runner=runner)
        if version.returncode or _GOOGLE_PLUGIN.search(version.stdout) is None:
            message = "TFLint requires the locally installed Google ruleset at exact version 0.39.0"
            raise NativeToolError(message)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return _failed("tflint", error, len(paths))
    return _json_tool(
        "tflint",
        ("--config", config, "--format=json", "--call-module-type=local"),
        project,
        paths,
        lambda payload, project_root: parse_tflint(payload, root, cwd=project_root),
        runner=runner,
    )


def _compose_report(root: Path, path: Path, runner: ProcessRunner, *, version: str | None) -> ToolReport:
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary owns static Compose output coverage.
        if version is None:
            message = "Compose static validation requires an explicit manifest [devops].compose_version consumer pin"
            raise NativeToolError(message)
        tool = checked_tool("docker", root=root, runner=runner, expected_version=version)
        output = invoke(
            replace(tool, finding_exits=frozenset()),
            ("compose", "-f", str(path), "config", "--no-interpolate", "--no-env-resolution", "--format", "json"),
            root=root,
            runner=runner,
        )
        report = _table(parse_json(output.stdout))
        if not is_object_mapping(report.get("services")):
            message = "Compose static output must contain a services mapping"
            raise NativeToolError(message)
        return ToolReport("compose-static", Completion.COMPLETE, version=tool.version, file_count=1)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return _failed("compose-static", error, 1)


def _diagnostic(
    source: str,
    rule: str,
    message: str,
    filename: str,
    root: Path,
    *,
    line: int,
    column: int,
    byte_column: bool = False,
) -> Diagnostic:
    path = _contained(root, filename)
    document = SourceDocument.read(path)
    point = document.byte_point(line=line, column=column) if byte_column else document.point(line=line, column=column)
    if point is None:
        message = "Tool reported a position outside its source document"
        raise ValueError(message)
    return Diagnostic(
        rule, message, Severity.ERROR, source, Location(path.relative_to(root).as_posix(), position=point), rule_id=rule
    )


def _contained(root: Path, filename: str) -> Path:
    path = (root / filename).resolve()
    path.relative_to(root)
    if not path.is_file():
        message = "Selected or reported DevOps input is not a local file"
        raise ValueError(message)
    return path


def _table(value: object) -> dict[object, object]:
    if not is_object_mapping(value):
        message = "Expected a JSON object in native tool output"
        raise ValueError(message)
    return value


def _records(value: object) -> list[dict[object, object]]:
    if not is_object_list(value):
        message = "Expected a JSON array in native tool output"
        raise ValueError(message)
    return [_table(item) for item in value]


def _text(value: dict[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        message = f"Native tool output requires nonempty string {key}"
        raise ValueError(message)
    return item


def _integer(value: dict[object, object], key: str, *, minimum: int = 1) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
        message = f"Native tool output requires integer {key} >= {minimum}"
        raise ValueError(message)
    return item


def _failed(name: str, error: Exception | str, count: int) -> ToolReport:
    return ToolReport(
        name, Completion.FAILED, issues=(ExecutionIssue(name, "coverage-failure", str(error)),), file_count=count
    )
