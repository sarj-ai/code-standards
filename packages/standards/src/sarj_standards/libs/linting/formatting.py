from __future__ import annotations

from functools import partial
import json
import os
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.adoption import manifest, packagemanager
from sarj_standards.libs.adoption.formatting import (
    SUPPORTED_SUFFIXES as SUPPORTED_SUFFIXES,
    selected_formatter_projects,
)
from sarj_standards.libs.diagnostics import (
    AnalyzerId,
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Severity,
    ToolReport,
    TrustMode,
)
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list

from . import external
from .runner import maintained_files


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_standards.libs.linting.external import ProcessRunner

    from .policy import Policy

_BATCH_SIZE: Final = 250
_MAX_PROJECTS: Final = 32
_DEADLINE_SECONDS: Final = 300


def maintained_formatting_paths(files: Sequence[str], *, root: Path, policy: Policy | None = None) -> tuple[str, ...]:
    repository = root.resolve()
    supplied = tuple(
        str(Path(os.path.abspath(repository / path)))  # ruff: ignore[os-path-abspath] -- preserve lexical symlink components for validation.
        for path in files
    )
    for path in supplied:
        relative = Path(path).relative_to(repository)
        cursor = repository
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                msg = f"refusing symlink formatter input: {path}"
                raise ValueError(msg)
    return maintained_files(supplied, suffixes=SUPPORTED_SUFFIXES, policy=policy)


def analyze_formatting(
    files: Sequence[str],
    *,
    root: Path,
    trust: TrustMode | str,
    runner: ProcessRunner | None = None,
    policy: Policy | None = None,
) -> ToolReport:
    root = root.resolve()
    started = time.monotonic()
    try:
        grouped = selected_formatter_projects(maintained_formatting_paths(files, root=root, policy=policy), root)
        trust = TrustMode(trust)
    except (OSError, TypeError, ValueError) as exc:
        return _failure("configuration-failure", str(exc))
    if trust is TrustMode.SAFE and grouped:
        return _failure("trust-required", "Oxfmt may load executable repository policy; use trusted mode")
    if len(grouped) > _MAX_PROJECTS:
        return _failure("project-limit", "Oxfmt selected more than 32 formatter projects")
    reports: list[ToolReport] = []
    version = manifest.oxlint_peers()["oxfmt"]
    for config, selected in sorted(grouped.items()):
        reports.extend(
            _analyze_formatter_project(config, selected, root=root, runner=runner, version=version, started=started)
        )
    issues = tuple(issue for report in reports for issue in report.issues)
    return ToolReport(
        "oxfmt",
        Completion.FAILED if issues else Completion.COMPLETE,
        diagnostics=tuple(item for report in reports for item in report.diagnostics),
        issues=issues,
        analyzer_id=AnalyzerId("oxfmt"),
        invocation_id=InvocationId("oxfmt"),
        version=version if not issues else None,
        duration_ms=round((time.monotonic() - started) * 1000),
        file_count=sum(len(paths) for paths in grouped.values()),
    )


def _analyze_formatter_project(
    config: Path,
    selected: set[Path],
    *,
    root: Path,
    runner: ProcessRunner | None,
    version: str,
    started: float,
) -> list[ToolReport]:
    project = config.parent
    if runner is None and (issue := external.missing_local_binary_issue("oxfmt", project, root)) is not None:
        return [ToolReport("oxfmt", Completion.FAILED, issues=(issue,))]
    reports: list[ToolReport] = []
    paths = sorted(selected)
    for offset in range(0, len(paths), _BATCH_SIZE):
        remaining = _DEADLINE_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            reports.append(_failure("aggregate-timeout", "Oxfmt aggregate analysis exceeded 300 seconds"))
            break
        chunk = paths[offset : offset + _BATCH_SIZE]
        # --list-different is read-only and omits check banners/statistics.
        client = packagemanager.detect(packagemanager.workspace_root(project, root))
        argv = packagemanager.exec_argv(
            client,
            "oxfmt",
            "--config",
            config.name,
            "--list-different",
            "--no-error-on-unmatched-pattern",
            "--",
            *(path.as_posix() for path in chunk),
        )
        try:
            local = external.local_node_binary_argv("oxfmt", argv, project, root) if runner is None else argv
            execute = runner or partial(external.run_node_process, timeout_seconds=remaining)
            reports.append(
                external.invoke_tool(
                    "oxfmt",
                    local,
                    cwd=project,
                    root=root,
                    runner=partial(_structured_output, execute),
                    parser=partial(_parse_paths, cwd=project, selected=frozenset(chunk)),
                    file_count=len(chunk),
                    version=version,
                    invocation_id=f"{project.relative_to(root).as_posix()}:{offset // _BATCH_SIZE + 1}",
                )
            )
        except (OSError, TypeError, ValueError) as exc:
            reports.append(_failure("tool-failure", str(exc)))
    return reports


def _structured_output(runner: ProcessRunner, argv: Sequence[str], *, cwd: Path) -> external.ProcessOutput:
    output = runner(argv, cwd=cwd)
    if (
        output.returncode == 0
        and re.fullmatch(r"Finished in \d+ms on 0 files using \d+ threads\.\n?", output.stdout)
        and output.stderr.strip() == "No files found matching the given patterns."
    ):
        return external.ProcessOutput(0, "[]", "")
    if output.returncode not in {0, 1} or output.stderr.strip():
        return external.ProcessOutput(2, output.stdout, output.stderr or "Oxfmt execution failed")
    return external.ProcessOutput(output.returncode, json.dumps(output.stdout.splitlines()), "")


def _parse_paths(payload: str, *, root: Path, cwd: Path, selected: frozenset[Path]) -> tuple[Diagnostic, ...]:
    values = parse_json(payload)
    if not is_object_list(values) or any(not isinstance(value, str) for value in values):
        msg = "Oxfmt must return a list of filenames"
        raise ValueError(msg)
    paths: set[Path] = set()
    for name in values:
        if not isinstance(name, str):
            msg = "Oxfmt must return string filenames"
            raise TypeError(msg)
        path = (cwd / name).resolve()
        if path not in selected or path in paths:
            msg = "Oxfmt returned an unexpected or duplicate selected filename"
            raise ValueError(msg)
        paths.add(path)
    return tuple(
        Diagnostic(
            "OXFMT001",
            "File does not match the repository formatter policy.",
            Severity.ERROR,
            "oxfmt",
            Location(path.relative_to(root).as_posix()),
            rule_id="OXFMT001",
            help="Run code-standards fix for this file.",
        )
        for path in sorted(paths)
    )


def _failure(kind: str, message: str) -> ToolReport:
    return ToolReport(
        "oxfmt",
        Completion.FAILED,
        issues=(ExecutionIssue("oxfmt", kind, message),),
        analyzer_id=AnalyzerId("oxfmt"),
        invocation_id=InvocationId("oxfmt"),
    )
