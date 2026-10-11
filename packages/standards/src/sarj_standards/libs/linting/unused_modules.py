from __future__ import annotations

from dataclasses import replace
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- only catch bounded native runner failures.
from typing import TYPE_CHECKING, ClassVar, Final

from pathspec import PathSpec
from pydantic import BaseModel, ConfigDict, Field

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    ToolReport,
    TrustMode,
)
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting.devops_tools import checked_tool, invoke
from sarj_standards.libs.linting.duplicate_code import TEST_GLOBS
from sarj_standards.libs.linting.external import ProcessRunner, redact_message, run_process
from sarj_standards.libs.linting.runner import accepts_hook_path
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sarj_standards.libs.linting.devops_tools import NativeTool


_TEST_PATHS: Final = PathSpec.from_lines("gitignore", TEST_GLOBS)
_CONFIG_NAMES: Final = (
    "knip.json",
    ".knip.json",
    "knip.jsonc",
    ".knip.jsonc",
    "knip.ts",
    "knip.js",
    "knip.config.ts",
    "knip.config.js",
)
_HELP: Final = (
    "Check runtime, framework, generated, dynamic, and public entry points before deleting this module. "
    "Move test-only support into the test tree when it has no application owner. "
    "This is evidence from configured production roots, not an automatic deletion decision."
)


class _KnipSymbol(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    name: str


class _KnipIssue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    file: str = Field(min_length=1)
    files: tuple[_KnipSymbol, ...] = ()
    unresolved: tuple[_KnipSymbol, ...] = ()


class _KnipReport(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    issues: tuple[_KnipIssue, ...]


def analyze_application_modules(
    *,
    root: Path,
    trust: TrustMode,
    allows_path: Callable[[str], bool],
    runner: ProcessRunner = run_process,
) -> ToolReport:
    root = root.resolve()
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- one boundary contains native configuration, attestation, and protocol failures.
        adopted = manifest.load(root)
        if adopted is None or not adopted.knip_application:
            return _inconclusive("Declare [knip].application = true before enabling Knip module ownership evidence.")
        project = (root / adopted.typescript_dest).resolve()
        project.relative_to(root)
        config = _production_config(project)
        if config is None:
            return _inconclusive(
                "Knip requires a single application with explicit production entry/project patterns in knip.json; "
                "library, workspace, dynamic, and unknown configuration topology needs a separate audited owner."
            )
        if trust is not TrustMode.TRUSTED:
            return _inconclusive("Knip loads executable framework configuration; trusted repository code is required.")
        tool = checked_tool("knip", root=project, runner=runner)
        if not _configuration_is_complete(tool, config=config, root=project, runner=runner):
            return _inconclusive("Knip reported configuration hints or unresolved imports; graph ownership is unknown.")
        output = invoke(
            tool,
            (
                "--config",
                str(config),
                "--production",
                "--include",
                "files,unresolved",
                "--reporter",
                "json",
                "--no-progress",
                "--no-exit-code",
            ),
            root=project,
            runner=runner,
        )
        report = _KnipReport.model_validate_json(output.stdout)
        if output.stderr.strip() or any(issue.unresolved for issue in report.issues):
            return _inconclusive(
                "Knip reported unresolved imports or configuration diagnostics; graph ownership is unknown."
            )
        diagnostics = tuple(
            diagnostic
            for issue in report.issues
            if issue.files
            and (diagnostic := _diagnostic(issue.file, project=project, root=root, allows_path=allows_path)) is not None
        )
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        issue = ExecutionIssue("knip", "tool-failure", redact_message(str(error), root))
        return ToolReport("knip", Completion.FAILED, issues=(issue,))
    return ToolReport("knip", Completion.COMPLETE, diagnostics=diagnostics, version=tool.version)


def _configuration_is_complete(tool: NativeTool, *, config: Path, root: Path, runner: ProcessRunner) -> bool:
    # Production mode suppresses native configuration hints. Validate them in
    # the same native tool before relying on its production graph.
    output = invoke(
        replace(tool, finding_exits=frozenset({1})),
        (
            "--config",
            str(config),
            "--include",
            "unresolved",
            "--reporter",
            "json",
            "--no-progress",
            "--treat-config-hints-as-errors",
        ),
        root=root,
        runner=runner,
    )
    report = _KnipReport.model_validate_json(output.stdout)
    return output.returncode == 0 and not output.stderr.strip() and not any(issue.unresolved for issue in report.issues)


def _production_config(project: Path) -> Path | None:
    package = parse_unique_json((project / "package.json").read_text(encoding="utf-8"))
    if (
        not is_object_mapping(package)
        or package.get("private") is not True
        or package.get("workspaces")
        or "knip" in package
        or (project / "pnpm-workspace.yaml").is_file()
    ):
        return None
    configs = tuple(project / name for name in _CONFIG_NAMES if (project / name).is_file())
    if len(configs) != 1 or configs[0].suffix != ".json":
        return None
    config = parse_unique_json(configs[0].read_text(encoding="utf-8"))
    if not is_object_mapping(config) or any(
        config.get(key) for key in ("workspaces", "ignore", "ignoreUnresolved", "ignoreIssues", "preprocessor")
    ):
        return None
    rules = config.get("rules")
    if is_object_mapping(rules) and rules.get("unresolved") == "off":
        return None
    if not all(_production_patterns(config.get(key)) for key in ("entry", "project")):
        return None
    return configs[0]


def _production_patterns(value: object) -> bool:
    if not is_object_list(value):
        return False
    patterns = tuple(item for item in value if isinstance(item, str))
    return len(patterns) == len(value) and any(item.endswith("!") and not item.startswith("!") for item in patterns)


def _diagnostic(file: str, *, project: Path, root: Path, allows_path: Callable[[str], bool]) -> Diagnostic | None:
    path = (project / file).resolve()
    relative = path.relative_to(root).as_posix()
    if not path.is_file() or not path.is_relative_to(project):
        message = "Knip reported a module outside the application's existing files"
        raise ValueError(message)
    if (
        not accepts_hook_path(path, root=root)
        or path.name.endswith((".d.ts", ".d.mts", ".d.cts"))
        or _TEST_PATHS.match_file(relative)
        or not allows_path(relative)
    ):
        return None
    return Diagnostic(
        "files",
        "This application module is not reached by Knip's configured production entry points.",
        Severity.WARNING,
        "knip",
        Location(relative),
        rule_id="files",
        help=_HELP,
    )


def _inconclusive(message: str) -> ToolReport:
    return ToolReport("knip", Completion.PARTIAL, issues=(ExecutionIssue("knip", "graph-inconclusive", message),))
