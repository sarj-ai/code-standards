"""Standard machine formats for canonical Standards diagnostics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .models import AnalysisReport, Diagnostic, Severity


if TYPE_CHECKING:
    from pathlib import Path


def to_json(report: AnalysisReport, *, indent: int | None = 2) -> str:
    """Serialize the stable Standards schema deterministically."""
    return json.dumps(report.as_dict(), indent=indent, sort_keys=True) + "\n"


def to_sarif(report: AnalysisReport) -> str:
    """Serialize SARIF 2.1.0 for GitHub, editors, and analysis aggregators."""
    rules = _sarif_rules(report)
    payload: dict[str, object] = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "sarj-standards",
                        "informationUri": "https://github.com/sarj-ai/standards",
                        "rules": rules,
                    }
                },
                "results": [_sarif_result(report.root, item) for item in report.diagnostics],
                "invocations": [
                    {
                        "executionSuccessful": not report.issues,
                        "toolExecutionNotifications": [
                            {"descriptor": {"id": issue.kind}, "message": {"text": issue.message}, "level": "error"}
                            for issue in report.issues
                        ],
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sarif_rules(report: AnalysisReport) -> list[dict[str, object]]:
    by_code: dict[str, Diagnostic] = {}
    for diagnostic in report.diagnostics:
        by_code.setdefault(diagnostic.code, diagnostic)
    return [
        {
            "id": code,
            "name": item.rule_id or code,
            "shortDescription": {"text": item.message},
            **({"helpUri": item.help_url} if item.help_url is not None else {}),
        }
        for code, item in sorted(by_code.items())
    ]


def _sarif_result(root: Path, diagnostic: Diagnostic) -> dict[str, object]:
    location = diagnostic.location
    physical: dict[str, object] = {"artifactLocation": {"uri": location.path, "uriBaseId": "%SRCROOT%"}}
    if location.region is not None:
        physical["region"] = {
            "startLine": location.region.start.line + 1,
            "startColumn": location.region.start.character + 1,
            "endLine": location.region.end.line + 1,
            "endColumn": location.region.end.character + 1,
        }
    elif location.position is not None:
        physical["region"] = {
            "startLine": location.position.line + 1,
            "startColumn": location.position.character + 1,
        }
    return {
        "ruleId": diagnostic.code,
        "level": _sarif_level(diagnostic.severity),
        "message": {"text": diagnostic.message},
        "locations": [{"physicalLocation": physical}],
        "properties": {"source": diagnostic.source, "repositoryRoot": str(root)},
    }


def _sarif_level(severity: Severity) -> str:
    if severity is Severity.ERROR:
        return "error"
    if severity is Severity.WARNING:
        return "warning"
    return "note"
