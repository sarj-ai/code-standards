"""Canonical diagnostics preserve facts across JSON, SARIF, and native tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import api
from sarj_lint_configs.libs.adoption.manifest import as_table, list_field, table_field
from sarj_lint_configs.libs.diagnostics import (
    ANALYSIS_SCHEMA,
    AnalysisReport,
    Completion,
    Conclusion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Severity,
    SourceDocument,
    ToolReport,
    to_json,
    to_sarif,
)


if TYPE_CHECKING:
    from pathlib import Path


def test_source_document_preserves_byte_offsets_and_utf16_columns(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "x = '😀'\nvalue = 1\n")

    after_emoji = document.point(line=1, column=7)

    assert after_emoji == Position(line=0, character=7, byte_offset=9)


def test_versioned_json_schema_is_bundled() -> None:
    raw: object = json.loads(ANALYSIS_SCHEMA.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    schema = as_table(raw)

    assert schema["$id"] == "https://standards.sarj.ai/schemas/analysis/v1"
    assert "diagnostic" in table_field(schema, "$defs")


def test_source_document_rejects_byte_span_inside_utf8_codepoint(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "😀\n")

    with pytest.raises(ValueError, match="splits a UTF-8 code point"):
        document.region(start_byte=1, end_byte=4)


def test_source_document_rejects_utf16_position_inside_surrogate_pair(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "😀\n")

    assert document.utf16_point(line=0, character=1) is None
    assert document.utf16_point(line=0, character=2) == Position(0, 2, 4)


def test_json_uses_utf16_positions_without_leaking_internal_byte_offsets(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST001",
        "example",
        Severity.ERROR,
        "fixture",
        Location("example.py", position=Position(2, 3, 17)),
        rule_id="example-rule",
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    raw: object = json.loads(to_json(report))  # pyright: ignore[reportAny] -- json is an untyped boundary
    payload = as_table(raw)
    first = as_table(list_field(payload, "diagnostics")[0])
    position = table_field(table_field(first, "location"), "position")

    assert payload["schemaVersion"] == 1
    assert position == {"line": 2, "character": 3}
    assert "byte" not in json.dumps(payload)
    assert payload["exitCode"] == 1


def test_warning_only_report_is_successful_but_retains_findings(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST002",
        "gradual rollout",
        Severity.WARNING,
        "fixture",
        Location("example.py"),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    assert report.ok
    assert report.exit_code == 0
    assert report.conclusion is Conclusion.FINDINGS


def test_execution_issue_is_not_fabricated_as_a_diagnostic(tmp_path: Path) -> None:
    issue = ExecutionIssue("fixture", "tool-missing", "executable not found", 127)
    report = AnalysisReport(
        tmp_path,
        Completion.FAILED,
        Conclusion.FAILED,
        (ToolReport("fixture", Completion.FAILED, issues=(issue,)),),
    )

    payload = report.as_dict()

    assert payload["diagnostics"] == []
    assert payload["issues"] == [issue.as_dict()]
    assert report.exit_code == 2


def test_report_rejects_completion_that_contradicts_execution_issues(tmp_path: Path) -> None:
    issue = ExecutionIssue("fixture", "crash", "boom")

    with pytest.raises(ValueError, match="completion contradicts"):
        AnalysisReport(
            tmp_path,
            Completion.COMPLETE,
            Conclusion.FAILED,
            (ToolReport("fixture", Completion.FAILED, issues=(issue,)),),
        )


def test_report_rejects_conclusion_that_hides_findings(tmp_path: Path) -> None:
    diagnostic = Diagnostic("TEST004", "found", Severity.WARNING, "fixture", Location("example.py"))

    with pytest.raises(ValueError, match="conclusion must be findings"):
        AnalysisReport(
            tmp_path,
            Completion.COMPLETE,
            Conclusion.PASSED,
            (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
        )


def test_sarif_omits_region_when_analyzer_only_knows_a_path(tmp_path: Path) -> None:
    diagnostic = Diagnostic("TEST003", "path only", Severity.INFO, "fixture", Location("README.md"))
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    raw: object = json.loads(to_sarif(report))  # pyright: ignore[reportAny] -- json is an untyped boundary
    payload = as_table(raw)
    run = as_table(list_field(payload, "runs")[0])
    result = as_table(list_field(run, "results")[0])
    location = as_table(list_field(result, "locations")[0])
    physical = table_field(location, "physicalLocation")

    assert "region" not in physical


def test_standards_analyze_returns_native_python_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("import logging\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["service.py"])

    finding = next(item for item in report.diagnostics if item.code == "SARJ052")
    assert report.completion is Completion.COMPLETE
    assert report.conclusion is Conclusion.FINDINGS
    assert finding.rule_id == "no-stdlib-logging"
    assert finding.source == "sarj-python-lint"
    assert finding.location.path == "service.py"
    assert finding.location.position == Position(0, 0, 0)


def test_standards_analyze_reports_invalid_input_as_execution_issue(tmp_path: Path) -> None:
    report = api.Standards(tmp_path).analyze(["missing.py"])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.FAILED
    assert not report.diagnostics
    assert report.issues[0].kind == "invalid-input"
    assert report.exit_code == 2
