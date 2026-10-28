from __future__ import annotations

from heapq import nsmallest
import json
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import quote

from .models import AnalysisReport, Diagnostic, Fix, FixSafety, Location, Severity, TextEdit


if TYPE_CHECKING:
    from pydantic import JsonValue


class _DiagnosticPriority(NamedTuple):
    severity: int
    path: str
    line: int
    character: int
    source: str
    code: str
    message: str


_GITHUB_ANNOTATION_LIMIT = 10


def to_json(report: AnalysisReport, *, indent: int | None = 2, include_fix_source_hashes: bool = False) -> str:
    return (
        json.dumps(report.as_dict(include_fix_source_hashes=include_fix_source_hashes), indent=indent, sort_keys=True)
        + "\n"
    )


def to_sarif(report: AnalysisReport) -> str:
    notifications: list[JsonValue] = [
        {"descriptor": {"id": issue.kind}, "message": {"text": issue.message}, "level": "error"}
        for issue in report.issues
    ]
    notifications.extend(
        {
            "descriptor": {"id": "coverage-notice"},
            "message": {"text": _coverage_line(item.source, item.reason, item.file_count)},
            "level": "error" if item.blocking else "note",
            "properties": {"disposition": item.disposition.value},
        }
        for item in report.coverage
    )
    notifications.extend(
        {"descriptor": {"id": "baseline-notice"}, "message": {"text": line}, "level": "note"}
        for line in _baseline_lines(report)
    )
    run: dict[str, JsonValue] = {
        "tool": {
            "driver": {
                "name": "code-standards",
                "informationUri": "https://github.com/sarj-ai/code-standards",
                "rules": _sarif_rules(report),
            }
        },
        "results": [_sarif_result(item) for item in report.diagnostics],
        "columnKind": "utf16CodeUnits",
        "invocations": [
            {
                "executionSuccessful": report.completion.value == "complete",
                "toolExecutionNotifications": notifications,
            }
        ],
    }
    if any(tool.policy_failed for tool in report.tools):
        run["properties"] = {
            "policyFailedTools": [tool.name for tool in report.tools if tool.policy_failed],
            "exitCode": report.exit_code,
        }
    payload: dict[str, JsonValue] = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [run],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def to_text(report: AnalysisReport, *, max_diagnostics: int | None = None) -> str:
    diagnostics = report.diagnostics
    omitted = 0
    if max_diagnostics is not None:
        if max_diagnostics < 0:
            msg = "max_diagnostics must be non-negative"
            raise ValueError(msg)
        omitted = max(0, len(diagnostics) - max_diagnostics)
        if omitted:
            diagnostics = tuple(nsmallest(max_diagnostics, diagnostics, key=_diagnostic_priority))
    lines = [_text_diagnostic(item) for item in diagnostics]
    if omitted:
        lines.append(
            f"code-standards: {omitted} diagnostic(s) omitted; use --format json or sarif for the complete report"
        )
    lines.extend(f"{issue.source}: {issue.kind}: {issue.message}" for issue in report.issues)
    lines.extend(_coverage_line(item.source, item.reason, item.file_count) for item in report.coverage)
    lines.extend(_baseline_lines(report))
    lines.extend(_policy_failure_lines(report))
    lines.append(_summary(report))
    return "\n".join(lines) + "\n"


def to_github(report: AnalysisReport, *, max_annotations_per_level: int = _GITHUB_ANNOTATION_LIMIT) -> str:
    if not 0 <= max_annotations_per_level <= _GITHUB_ANNOTATION_LIMIT:
        msg = "max_annotations_per_level must be between 0 and 10"
        raise ValueError(msg)
    issues = [
        f"::error title={_github_property(f'{issue.source}/{issue.kind}')}::{_github_message(issue.message)}"
        for issue in report.issues[:max_annotations_per_level]
    ]
    counts = dict.fromkeys(Severity, 0)
    for tool in report.tools:
        for diagnostic in tool.diagnostics:
            counts[diagnostic.severity] += 1
    error_budget = max_annotations_per_level - len(issues)
    selected = _github_selection(report, error_budget, max_annotations_per_level)
    lines = [
        *issues,
        *(_github_diagnostic(item) for item in selected[Severity.ERROR]),
        *(_github_diagnostic(item) for item in selected[Severity.WARNING]),
        *(_github_diagnostic(item) for item in selected[Severity.INFO]),
    ]
    omitted = (
        max(0, len(report.issues) + counts[Severity.ERROR] - max_annotations_per_level)
        + max(0, counts[Severity.WARNING] - max_annotations_per_level)
        + max(0, counts[Severity.INFO] - max_annotations_per_level)
    )
    if omitted:
        lines.append(
            f"code-standards: {omitted} annotation(s) omitted by GitHub's per-level limits; "
            "use JSON or SARIF for the complete report"
        )
    lines.extend(_coverage_line(item.source, item.reason, item.file_count) for item in report.coverage)
    lines.extend(_baseline_lines(report))
    lines.extend(_policy_failure_lines(report))
    lines.append(_summary(report))
    return "\n".join(lines) + "\n"


def _github_selection(
    report: AnalysisReport, error_budget: int, max_annotations_per_level: int
) -> dict[Severity, list[Diagnostic]]:
    return {
        severity: nsmallest(
            error_budget if severity is Severity.ERROR else max_annotations_per_level,
            (diagnostic for tool in report.tools for diagnostic in tool.diagnostics if diagnostic.severity is severity),
            key=_diagnostic_priority,
        )
        for severity in Severity
    }


def _diagnostic_priority(diagnostic: Diagnostic) -> _DiagnosticPriority:
    severity = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[diagnostic.severity]
    location = diagnostic.location
    position = location.region.start if location.region is not None else location.position
    return _DiagnosticPriority(
        severity,
        location.path,
        -1 if position is None else position.line,
        -1 if position is None else position.character,
        diagnostic.source,
        diagnostic.code,
        diagnostic.message,
    )


def _text_diagnostic(diagnostic: Diagnostic) -> str:
    position = (
        diagnostic.location.region.start if diagnostic.location.region is not None else diagnostic.location.position
    )
    suffix = "" if position is None else f":{position.line + 1}:{position.character + 1}"
    return (
        f"{diagnostic.location.path}{suffix}: {diagnostic.severity.value} "
        f"{diagnostic.code} {diagnostic.message} [{diagnostic.source}]"
    )


def _github_diagnostic(diagnostic: Diagnostic) -> str:
    level = "notice" if diagnostic.severity is Severity.INFO else diagnostic.severity.value
    properties: list[str] = []
    position = (
        diagnostic.location.region.start if diagnostic.location.region is not None else diagnostic.location.position
    )
    if position is not None:
        properties.extend((f"file={_github_property(diagnostic.location.path)}", f"line={position.line + 1}"))
        region = diagnostic.location.region
        if region is None:
            properties.append(f"col={position.character + 1}")
        elif region.end.line == region.start.line:
            properties.extend(
                (
                    f"col={position.character + 1}",
                    f"endLine={region.end.line + 1}",
                    f"endColumn={region.end.character + 1}",
                )
            )
        else:
            properties.append(f"endLine={region.end.line + 1}")
    properties.append(f"title={_github_property(f'{diagnostic.source}/{diagnostic.code}')}")
    message = diagnostic.message if position is not None else f"{diagnostic.location.path}: {diagnostic.message}"
    return f"::{level} {','.join(properties)}::{_github_message(message)}"


def _github_message(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _github_property(value: str) -> str:
    return _github_message(value).replace(":", "%3A").replace(",", "%2C")


def _summary(report: AnalysisReport) -> str:
    counts = dict.fromkeys(Severity, 0)
    for tool in report.tools:
        for diagnostic in tool.diagnostics:
            counts[diagnostic.severity] += 1
    return (
        f"code-standards: {counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s), "
        f"{counts[Severity.INFO]} notice(s), {len(report.issues)} execution issue(s)"
    )


def _baseline_lines(report: AnalysisReport) -> list[str]:
    return [
        f"code-standards baseline: {tool.name}: {tool.baselined_count} existing finding(s) accepted by central diagnostic baseline"
        for tool in report.tools
        if tool.baselined_count
    ]


def _coverage_line(source: str, reason: str, file_count: int) -> str:
    return f"code-standards coverage: {source} did not analyze {file_count} selected file(s): {reason}"


def _sarif_rules(report: AnalysisReport) -> list[JsonValue]:
    by_code: dict[tuple[str, str], Diagnostic] = {}
    for diagnostic in report.diagnostics:
        by_code.setdefault((diagnostic.source, diagnostic.code), diagnostic)
    return [
        {
            "id": _sarif_rule_id(item),
            "name": item.rule_id or code,
            "shortDescription": {"text": item.help or item.rule_id or code},
            **({"helpUri": item.help_url} if item.help_url is not None else {}),
        }
        for (_source, code), item in sorted(by_code.items())
    ]


def _sarif_result(diagnostic: Diagnostic) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {
        "ruleId": _sarif_rule_id(diagnostic),
        "level": _sarif_level(diagnostic.severity),
        "message": {"text": diagnostic.message},
        "locations": [{"physicalLocation": _sarif_physical(diagnostic.location)}],
        "properties": {
            "source": diagnostic.source,
            "code": diagnostic.code,
            "repositoryRoot": ".",
            **({"tags": list(diagnostic.tags)} if diagnostic.tags else {}),
            **({"notes": list(diagnostic.notes)} if diagnostic.notes else {}),
        },
    }
    if diagnostic.fingerprint is not None:
        result["partialFingerprints"] = {"sarj/v1": diagnostic.fingerprint}
    safe_fixes = tuple(fix for fix in diagnostic.fixes if fix.safety is FixSafety.SAFE)
    if safe_fixes:
        result["fixes"] = [_sarif_fix(fix) for fix in safe_fixes]
    if diagnostic.related:
        result["relatedLocations"] = [
            {"message": {"text": item.label}, "physicalLocation": _sarif_physical(item.location)}
            for item in diagnostic.related
        ]
    return result


def _sarif_fix(fix: Fix) -> dict[str, JsonValue]:
    grouped: dict[str, list[TextEdit]] = {}
    for edit in fix.edits:
        grouped.setdefault(edit.location.path, []).append(edit)
    return {
        "description": {"text": fix.title},
        "artifactChanges": [
            {
                "artifactLocation": {"uri": quote(path, safe="/")},
                "replacements": [
                    {
                        "deletedRegion": _sarif_region(edit.location),
                        "insertedContent": {"text": edit.replacement},
                    }
                    for edit in edits
                ],
            }
            for path, edits in sorted(grouped.items())
        ],
    }


def _sarif_physical(location: Location) -> dict[str, JsonValue]:
    physical: dict[str, JsonValue] = {"artifactLocation": {"uri": quote(location.path, safe="/")}}
    region = _sarif_region(location)
    if region:
        physical["region"] = region
    return physical


def _sarif_region(location: Location) -> dict[str, JsonValue]:
    if location.region is not None:
        return {
            "startLine": location.region.start.line + 1,
            "startColumn": location.region.start.character + 1,
            "endLine": location.region.end.line + 1,
            "endColumn": location.region.end.character + 1,
        }
    if location.position is not None:
        return {"startLine": location.position.line + 1, "startColumn": location.position.character + 1}
    return {}


def _sarif_rule_id(diagnostic: Diagnostic) -> str:
    return f"{diagnostic.source}/{diagnostic.code}"


def _sarif_level(severity: Severity) -> str:
    if severity is Severity.ERROR:
        return "error"
    if severity is Severity.WARNING:
        return "warning"
    return "note"


def _policy_failure_lines(report: AnalysisReport) -> list[str]:
    return [
        f"code-standards policy: {tool.name} rejected findings under its configured gate"
        for tool in report.tools
        if tool.policy_failed
    ]
