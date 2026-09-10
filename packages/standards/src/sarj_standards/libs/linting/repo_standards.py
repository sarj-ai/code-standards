from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

from repo_standards.core.models import (
    Diagnostic as RepositoryDiagnostic,
    SourceLocation as RepositoryLocation,
)
from repo_standards.repository import RepositoryAnalysisRequest, analyze_repository

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Region,
    RelatedLocation,
    Severity,
    ToolReport,
)


_MANIFEST = Path(".repo-standards/repository.toml")


def analyze(root: Path, *, staged: bool) -> ToolReport | None:
    manifest = root / _MANIFEST
    adopted = root / ".sarj-standards.toml"
    if not any(path.exists() or path.is_symlink() for path in (manifest, adopted)):
        return None
    report = analyze_repository(RepositoryAnalysisRequest(root=root, staged=staged))
    if (
        not (adopted.exists() or adopted.is_symlink())
        and len(report.execution_issues) == 1
        and report.execution_issues[0].code == "analysis.manifest-absent"
    ):
        return None
    issues = tuple(
        ExecutionIssue(
            "repo-standards",
            issue.code,
            f"{issue.phase}: {issue.message}",
            exit_code=2,
        )
        for issue in report.execution_issues
    )
    diagnostics = tuple(_diagnostic(item) for item in report.diagnostics)
    return ToolReport(
        "repo-standards",
        Completion.FAILED if issues else Completion.COMPLETE,
        diagnostics=diagnostics,
        issues=issues,
        version=version("repo-standards"),
    )


def _diagnostic(item: object) -> Diagnostic:
    if not isinstance(item, RepositoryDiagnostic):
        msg = "Repo Standards returned an invalid diagnostic type"
        raise TypeError(msg)
    severity = (
        Severity.INFO
        if item.disposition == "excepted"
        else Severity.ERROR
        if item.severity == "error"
        else Severity.WARNING
    )
    location = _location(item.location, fallback=item.path or _MANIFEST.as_posix())
    help_text = " ".join(
        (
            item.remediation.summary,
            *item.remediation.steps,
            *item.remediation.validation,
        )
    )
    notes = (
        f"rule version: {item.rule_version}",
        f"evidence: {item.evidence_level}",
        f"component: {item.component_id}",
        f"observed: {item.observed}",
        f"expected: {item.expected}",
        *(f"manifest pointer: {item.location.pointer}" for _ in (0,) if item.location and item.location.pointer),
    )
    return Diagnostic(
        str(item.rule_id),
        item.message,
        severity,
        "repo-standards",
        location,
        rule_id=str(item.rule_id),
        help=help_text,
        notes=notes,
        related=tuple(
            RelatedLocation(
                f"{related.relationship}: {related.message}",
                _location(related.location, fallback=location.path),
            )
            for related in item.related_locations
        ),
        fingerprint=item.fingerprint,
    )


def _location(item: RepositoryLocation | None, *, fallback: str) -> Location:
    if item is None:
        return Location(fallback)
    start = _position(item.line, item.column)
    end = _position(item.end_line, item.end_column)
    if start is not None and end is not None:
        return Location(item.path, region=Region(start, end))
    return Location(item.path, position=start)


def _position(line: int | None, column: int | None) -> Position | None:
    if line is None:
        return None
    return Position(line - 1, (column or 1) - 1, 0)
