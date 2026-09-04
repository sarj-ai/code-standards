from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.lifecycle import Command, EslintSelection
from sarj_standards.libs.adoption.manifest import ExclusionOverride, Manifest, as_table, list_field, table_field
from sarj_standards.libs.diagnostics import (
    ANALYSIS_SCHEMA,
    SCHEMA_URI,
    AnalysisReport,
    AnalyzerId,
    CacheStatus,
    Completion,
    Conclusion,
    CoverageDisposition,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Fix,
    FixSafety,
    InvocationId,
    Location,
    Position,
    Region,
    RelatedLocation,
    Severity,
    SourceDocument,
    TextEdit,
    ToolReport,
    TrustMode,
    to_github,
    to_json,
    to_sarif,
    to_text,
)
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.analysis import analyze as analyze_paths
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


def test_source_document_preserves_byte_offsets_and_utf16_columns(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "x = '😀'\nvalue = 1\n")

    after_emoji = document.point(line=1, column=7)

    assert after_emoji == Position(line=0, character=7, byte_offset=9)


def test_source_document_preserves_invalid_utf8_offsets_without_losing_the_report(tmp_path: Path) -> None:
    source = tmp_path / "legacy.py"
    raw = b"value = '\xff'\n"
    source.write_bytes(raw)

    document = SourceDocument.read(source)

    assert document.text.encode("utf-8", errors="surrogateescape") == raw
    point = document.point(line=1, column=12)
    assert point is not None
    assert point.byte_offset == len(raw.rstrip(b"\n"))
    assert document.byte_point(line=1, column=12) == point


def test_canonical_json_schema_is_bundled() -> None:
    raw: object = json.loads(ANALYSIS_SCHEMA.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    schema = as_table(raw)

    assert list(ANALYSIS_SCHEMA.parent.glob("*.schema.json")) == [ANALYSIS_SCHEMA]
    assert schema["$id"] == SCHEMA_URI
    assert table_field(schema, "properties")["schemaVersion"] == {"const": 1}
    assert "diagnostic" in table_field(schema, "$defs")
    assert "fix" in table_field(schema, "$defs")


@pytest.mark.parametrize(
    "build",
    [
        lambda: Diagnostic("", "message", Severity.ERROR, "fixture", Location("example.py")),
        lambda: Diagnostic("E001", "message", Severity.ERROR, "", Location("example.py")),
        lambda: Diagnostic("E001", "message", Severity.ERROR, "fixture", Location("example.py"), help_url="not a uri"),
        lambda: ExecutionIssue("", "failure", "message"),
        lambda: ToolReport("", Completion.COMPLETE),
    ],
)
def test_public_models_reject_values_that_violate_their_schema(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="must"):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Position(True, 0, 0),
        lambda: CoverageNotice("fixture", "reason", True),
        lambda: ExecutionIssue("fixture", "failure", "message", True),
    ],
)
def test_public_models_reject_boolean_in_integer_fields(build: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        build()


@pytest.mark.parametrize("path", ["/absolute.py", "../escape.py", "C:\\private\\file.py", "C:relative.py"])
def test_location_requires_portable_repository_relative_path(path: str) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        Location(path)


def _invalid_severity() -> Diagnostic:
    return Diagnostic(
        "E001",
        "message",
        "error",  # pyright: ignore[reportArgumentType] -- exercise runtime validation.
        "fixture",
        Location("example.py"),
    )


def _invalid_location() -> Diagnostic:
    return Diagnostic(
        "E001",
        "message",
        Severity.ERROR,
        "fixture",
        "example.py",  # pyright: ignore[reportArgumentType] -- exercise runtime validation.
    )


def _invalid_position() -> Location:
    return Location("example.py", position="bad")  # pyright: ignore[reportArgumentType] -- runtime boundary.


def _invalid_diagnostics() -> ToolReport:
    return ToolReport(
        "fixture",
        Completion.COMPLETE,
        diagnostics=("bad",),  # pyright: ignore[reportArgumentType] -- exercise runtime validation.
    )


@pytest.mark.parametrize("build", [_invalid_severity, _invalid_location, _invalid_position, _invalid_diagnostics])
def test_public_models_reject_invalid_nested_runtime_types(build: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="must be"):
        build()


@pytest.mark.parametrize(
    "case",
    [
        ("unicode.py", "😀\n", 1, 4, "splits a UTF-8 code point"),
        ("windows.py", "a\r\n", 2, 2, "splits a CRLF"),
    ],
    ids=("inside-utf8-codepoint", "inside-crlf"),
)
def test_source_document_rejects_invalid_byte_boundary(tmp_path: Path, case: tuple[str, str, int, int, str]) -> None:
    filename, text, start, end, message = case
    document = SourceDocument(tmp_path / filename, text)

    with pytest.raises(ValueError, match=message):
        document.region(start_byte=start, end_byte=end)


def test_source_document_rejects_utf16_position_inside_surrogate_pair(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "😀\n")

    assert document.utf16_point(line=0, character=1) is None
    assert document.utf16_point(line=0, character=2) == Position(0, 2, 4)


def test_source_document_only_treats_protocol_newlines_as_line_breaks(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "control.py", "x=1\f; import logging\n")

    assert document.point(line=1, column=7) == Position(0, 6, 6)
    assert document.utf16_point(line=1, character=0) == Position(1, 0, 21)


def test_region_rejects_backwards_editor_coordinates() -> None:
    with pytest.raises(ValueError, match="coordinates run backwards"):
        Region(Position(5, 9, 0), Position(0, 0, 1))


def test_source_document_converts_python_utf8_byte_columns(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "value = '😀'; import logging\n")

    assert document.byte_point(line=1, column=17) == Position(0, 14, 16)


def test_source_document_rejects_byte_column_inside_codepoint(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "😀 = 1\n")

    assert document.byte_point(line=1, column=2) is None


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
    assert payload["root"] == "."
    assert str(tmp_path) not in to_json(report)


def test_canonical_schema_preserves_rich_diagnostics(tmp_path: Path) -> None:
    start = Position(0, 0, 0)
    end = Position(0, 5, 5)
    edit = TextEdit(Location("example.py", region=Region(start, end)), "value")
    diagnostic = Diagnostic(
        "TEST007",
        "replace the legacy name",
        Severity.ERROR,
        "fixture",
        Location("example.py", region=Region(start, end)),
        rule_id="prefer-name",
        related=(RelatedLocation("declaration", Location("other.py", position=start)),),
        fixes=(Fix("Use value", FixSafety.SAFE, (edit,)),),
        tags=("maintainability",),
        fingerprint="stable-fingerprint",
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (
            ToolReport(
                "fixture",
                Completion.COMPLETE,
                diagnostics=(diagnostic,),
                analyzer_id=AnalyzerId("fixture/analyzer"),
                invocation_id=InvocationId("fixture/project"),
                version="1.2.3",
                duration_ms=7,
                file_count=2,
                cache_status=CacheStatus.MISS,
            ),
        ),
    )

    payload = as_table(json.loads(to_json(report)))  # pyright: ignore[reportAny]

    assert payload["schemaVersion"] == 1
    assert as_table(list_field(payload, "tools")[0])["invocationId"] == "fixture/project"
    assert "durationMs" not in as_table(list_field(payload, "tools")[0])
    assert report.tools[0].duration_ms == 7
    enriched = as_table(list_field(payload, "diagnostics")[0])
    assert enriched["ruleKey"] == "fixture:prefer-name"
    assert as_table(enriched["fingerprint"])["value"] == "stable-fingerprint"
    assert list_field(enriched, "fixes")
    sarif = as_table(json.loads(to_sarif(report)))  # pyright: ignore[reportAny]
    run = as_table(list_field(sarif, "runs")[0])
    result = as_table(list_field(run, "results")[0])
    assert as_table(result["partialFingerprints"])["sarj/v1"] == "stable-fingerprint"
    assert list_field(result, "fixes")
    assert list_field(result, "relatedLocations")


def test_expected_coverage_does_not_make_execution_incomplete(tmp_path: Path) -> None:
    coverage = CoverageNotice(
        "fixture",
        "excluded by repository policy",
        2,
        CoverageDisposition.EXCLUDED,
    )
    report = AnalysisReport(tmp_path, Completion.COMPLETE, Conclusion.PASSED, (), (coverage,))

    assert report.exit_code == 0
    payload = as_table(json.loads(to_json(report)))  # pyright: ignore[reportAny]
    assert as_table(list_field(payload, "coverage")[0])["disposition"] == "excluded"


def test_policy_is_default_all_with_path_rule_and_scoped_denylists(tmp_path: Path) -> None:
    policy = Policy.from_manifest(
        tmp_path,
        Manifest(
            version="1.2.3",
            configs=(),
            python_dest=".",
            typescript_dest=".",
            excluded_paths=("generated/**",),
            excluded_rules=("python:no-global-mutable",),
        ),
    )
    enabled = Diagnostic(
        "PY999",
        "enabled by default",
        Severity.ERROR,
        "sarj-python-lint",
        Location("src/app.py"),
        rule_id="future-rule",
    )
    disabled = Diagnostic(
        "PY100",
        "explicitly disabled",
        Severity.ERROR,
        "sarj-python-lint",
        Location("src/app.py"),
        rule_id="no-global-mutable",
    )
    generated = Diagnostic(
        "PY999",
        "generated code",
        Severity.ERROR,
        "sarj-python-lint",
        Location("generated/client.py"),
        rule_id="future-rule",
    )

    assert policy.filter_diagnostics((enabled, disabled, generated)) == (enabled,)
    assert policy.allows_path(".sarj-standards.toml")


def test_policy_scoped_rule_exclusion_does_not_leak_to_other_paths(tmp_path: Path) -> None:
    policy = Policy.from_manifest(
        tmp_path,
        Manifest(
            version="1.2.3",
            configs=(),
            python_dest=".",
            typescript_dest=".",
            exclusion_overrides=(ExclusionOverride(("tests/**",), ("ruff:S101",), "tests intentionally use assert"),),
        ),
    )
    test_finding = Diagnostic("S101", "assert", Severity.ERROR, "ruff", Location("tests/test_app.py"))
    source_finding = Diagnostic("S101", "assert", Severity.ERROR, "ruff", Location("src/app.py"))

    assert policy.filter_diagnostics((test_finding, source_finding)) == (source_finding,)


def test_explicitly_excluded_file_is_nonblocking_coverage(tmp_path: Path) -> None:
    source = tmp_path / "generated" / "client.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    adopted = Manifest(
        version="1.2.3",
        configs=("ruff", "pyright"),
        python_dest=".",
        typescript_dest=".",
        excluded_paths=("generated/**",),
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["generated/client.py"])

    assert report.exit_code == 0
    assert report.coverage[0].disposition is CoverageDisposition.EXCLUDED


def test_disabled_external_capabilities_are_not_executed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    adopted = Manifest(
        version="1.2.3",
        configs=("markdownlint",),
        python_dest=".",
        typescript_dest=".",
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
    called: list[str] = []

    def forbidden(_argv: Sequence[str], *, cwd: Path) -> external_module.ProcessOutput:
        _ = cwd
        called.append("external")
        return external_module.ProcessOutput(0, "[]", "")

    monkeypatch.setattr(external_module, "run_process", forbidden)
    report = api.Standards(tmp_path).analyze(["app.py"], external=True, trust=TrustMode.TRUSTED)

    assert report.exit_code == 0
    assert not called


def test_raw_scoped_eslint_analysis_does_not_run_unselected_external_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    captured: list[object] = []

    def analyze_external(*_args: object, **kwargs: object) -> tuple[ToolReport, ...]:
        captured.append(kwargs.get("capabilities"))
        return ()

    monkeypatch.setattr(api, "analyze_external", analyze_external)

    api.Standards(tmp_path).analyze(
        [str(source)],
        external=True,
        trust=TrustMode.TRUSTED,
        mode=api.AnalysisMode.RAW,
        rules=["eslint:prefer-ecmascript-private-members"],
    )

    assert captured == [frozenset({"eslint"})]


@pytest.mark.parametrize(("pass_on_unpruned", "expected"), [(False, False), (True, True)])
def test_standards_analysis_forwards_scoped_eslint_suppression_policy_to_the_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    pass_on_unpruned: bool,
    expected: bool,
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def select_commands(*_args: object, **_kwargs: object) -> EslintSelection:
        return EslintSelection((Command("eslint", ("npx", "eslint", "--", str(source)), tmp_path),), 0)

    def local_argv(argv: Sequence[str], *_args: object) -> tuple[str, ...]:
        return tuple(argv)

    def run_eslint(argv: Sequence[str], *, cwd: Path) -> external_module.ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return external_module.ProcessOutput(0, "[]", "")

    def installed_eslint(_project: Path, _root: Path) -> None:
        return None

    monkeypatch.setattr(external_module, "select_eslint_commands", select_commands)
    monkeypatch.setattr(external_module, "_local_eslint_argv", local_argv)
    monkeypatch.setattr(
        external_module,
        "_missing_eslint_issue",
        installed_eslint,
    )
    monkeypatch.setattr(external_module, "_run_eslint_process", run_eslint)

    report = api.Standards(tmp_path).analyze(
        [str(source)],
        external=True,
        trust=TrustMode.TRUSTED,
        mode=api.AnalysisMode.RAW,
        rules=["eslint:prefer-ecmascript-private-members"],
        pass_on_unpruned_eslint_suppressions=pass_on_unpruned,
    )

    assert report.issues == ()
    assert len(seen) == 1
    flag = "--pass-on-unpruned-suppressions"
    assert (flag in seen[0]) is expected
    if expected:
        assert seen[0].index(flag) < seen[0].index("--")


def test_fix_rejects_overlapping_edits() -> None:
    first = TextEdit(Location("example.py", region=Region(Position(0, 0, 0), Position(0, 3, 3))), "a")
    second = TextEdit(Location("example.py", region=Region(Position(0, 2, 2), Position(0, 4, 4))), "b")

    with pytest.raises(ValueError, match="must not overlap"):
        Fix("overlap", FixSafety.SAFE, (first, second))


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
        Conclusion.INCONCLUSIVE,
        (ToolReport("fixture", Completion.FAILED, issues=(issue,)),),
    )

    payload = report.as_dict()

    assert payload["diagnostics"] == []
    assert payload["issues"] == [issue.as_dict()]
    assert report.exit_code == 2


def test_report_rejects_completion_that_contradicts_execution_issues(tmp_path: Path) -> None:
    issue = ExecutionIssue("fixture", "crash", "boom")

    with pytest.raises(ValueError, match="completion must be failed"):
        AnalysisReport(
            tmp_path,
            Completion.COMPLETE,
            Conclusion.PASSED,
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
    assert run["columnKind"] == "utf16CodeUnits"
    assert str(tmp_path) not in to_sarif(report)


def test_sarif_qualifies_rule_identity_by_analyzer(tmp_path: Path) -> None:
    diagnostics = (
        Diagnostic("E001", "first", Severity.ERROR, "tool-a", Location("a.py"), help="First rule"),
        Diagnostic("E001", "second", Severity.WARNING, "tool-b", Location("b.py"), help="Second rule"),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=diagnostics),),
    )

    raw: object = json.loads(to_sarif(report))  # pyright: ignore[reportAny]
    run = as_table(list_field(as_table(raw), "runs")[0])
    driver = table_field(table_field(run, "tool"), "driver")

    assert [as_table(rule)["id"] for rule in list_field(driver, "rules")] == ["tool-a/E001", "tool-b/E001"]
    assert [as_table(result)["ruleId"] for result in list_field(run, "results")] == ["tool-a/E001", "tool-b/E001"]


def test_sarif_percent_encodes_artifact_uri(tmp_path: Path) -> None:
    diagnostic = Diagnostic("E001", "found", Severity.ERROR, "fixture", Location("dir/a b#c%.py"))
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    raw: object = json.loads(to_sarif(report))  # pyright: ignore[reportAny]
    run = as_table(list_field(as_table(raw), "runs")[0])
    result = as_table(list_field(run, "results")[0])
    location = as_table(list_field(result, "locations")[0])
    artifact = table_field(table_field(location, "physicalLocation"), "artifactLocation")

    assert artifact["uri"] == "dir/a%20b%23c%25.py"


def test_text_renderer_keeps_truthful_location_and_summary(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST005",
        "be concise",
        Severity.WARNING,
        "fixture",
        Location("README.md", position=Position(2, 4, 10)),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    assert to_text(report) == (
        "README.md:3:5: warning TEST005 be concise [fixture]\n"
        "code-standards: 0 error(s), 1 warning(s), 0 notice(s), 0 execution issue(s)\n"
    )


def test_github_renderer_escapes_commands_without_inventing_a_position(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST:006",
        "unsafe % value, first\r\nsecond",
        Severity.INFO,
        "fixture,source",
        Location("docs/a,b.md"),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    rendered = to_github(report)

    assert rendered.startswith(
        "::notice title=fixture%2Csource/TEST%3A006::docs/a,b.md: unsafe %25 value, first%0D%0Asecond\n"
    )
    assert "file=" not in rendered
    assert "line=" not in rendered
    assert rendered.endswith("1 notice(s), 0 execution issue(s)\n")


def test_github_renderer_uses_one_based_position_for_located_findings(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST007",
        "located",
        Severity.ERROR,
        "fixture",
        Location("src/example.py", position=Position(2, 4, 10)),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    assert to_github(report).startswith("::error file=src/example.py,line=3,col=5,title=fixture/TEST007::located\n")


def test_github_renderer_preserves_region_endpoint(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        "TEST008",
        "range",
        Severity.ERROR,
        "fixture",
        Location("src/example.py", region=Region(Position(2, 4, 10), Position(2, 8, 14))),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=(diagnostic,)),),
    )

    rendered = to_github(report)

    assert "line=3,col=5,endLine=3,endColumn=9" in rendered


def test_github_renderer_caps_annotations_and_prioritizes_errors(tmp_path: Path) -> None:
    diagnostics = (
        Diagnostic("W001", "warning", Severity.WARNING, "fixture", Location("a.py")),
        Diagnostic("W002", "another warning", Severity.WARNING, "fixture", Location("b.py")),
        Diagnostic("E001", "error", Severity.ERROR, "fixture", Location("z.py")),
    )
    report = AnalysisReport(
        tmp_path,
        Completion.COMPLETE,
        Conclusion.FINDINGS,
        (ToolReport("fixture", Completion.COMPLETE, diagnostics=diagnostics),),
    )

    rendered = to_github(report, max_annotations_per_level=1)

    assert "fixture/E001" in rendered
    assert "fixture/W001" in rendered
    assert "fixture/W002" not in rendered
    assert "1 annotation(s) omitted" in rendered


def test_standards_analyze_returns_native_python_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("logger.info('request', token=token)\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["service.py"])

    finding = next(item for item in report.diagnostics if item.code == "SARJ012")
    assert report.completion is Completion.COMPLETE
    assert report.conclusion is Conclusion.FINDINGS
    assert finding.rule_id == "no-secret-in-log"
    assert finding.source == "sarj-python-lint"
    assert finding.location.path == "service.py"
    assert finding.location.position == Position(0, 29, 29)


def test_standards_analyze_converts_python_ast_byte_columns_to_utf16(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("value = '😀'; logger.info('request', token=token)\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["service.py"])

    finding = next(item for item in report.diagnostics if item.code == "SARJ012")
    assert finding.location.position == Position(0, 43, 45)


def test_standards_analyze_converts_python_token_columns_to_utf16(tmp_path: Path) -> None:
    text = "𝕩 = 5 * 60  # 5 minutes\n"
    source = tmp_path / "service.py"
    source.write_text(text, encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["service.py"])

    finding = next(item for item in report.diagnostics if item.code == "SARJ051")
    hash_offset = text.index("#")
    assert finding.location.position == Position(0, hash_offset + 1, len(text[:hash_offset].encode()))


def test_standards_analyze_reports_invalid_input_as_execution_issue(tmp_path: Path) -> None:
    report = api.Standards(tmp_path).analyze(["missing.py"])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert not report.diagnostics
    assert report.issues[0].kind == "invalid-input"
    assert report.exit_code == 2


def test_standards_analyze_never_reports_selected_typescript_as_clean(tmp_path: Path) -> None:
    (tmp_path / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["app.ts"])

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert not report.issues
    assert report.coverage[0].source == "eslint"
    assert report.coverage[0].file_count == 1
    assert report.exit_code == 2


def test_standards_analyze_never_reports_unsupported_explicit_file_as_clean(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not covered\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["notes.txt"])

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.coverage[0].source == "sarj-standards"
    assert report.exit_code == 2


def test_external_analysis_never_reports_unsupported_explicit_file_as_clean(tmp_path: Path) -> None:
    (tmp_path / "notes.bin").write_bytes(b"not covered\n")

    report = api.Standards(tmp_path).analyze(["notes.bin"], external=True)

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.coverage[0].source == "sarj-standards"
    assert report.exit_code == 2


def test_external_analysis_reports_explicitly_disabled_eslint_coverage(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(api.__version__, (), ".", ".", hook_manager="none").render(),
        encoding="utf-8",
    )
    (tmp_path / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["app.ts"], external=True)

    assert report.completion is Completion.COMPLETE
    assert report.conclusion is Conclusion.PASSED
    assert report.coverage[0].source == "eslint"
    assert report.coverage[0].disposition is CoverageDisposition.NOT_REQUESTED
    assert report.coverage[0].file_count == 1


def test_public_native_analysis_rejects_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    report = analyze_paths([str(outside)], root=root)

    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "invalid-input"
    assert str(tmp_path) not in report.issues[0].message


def test_standards_analyze_preserves_native_findings_when_typescript_is_uncovered(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    (tmp_path / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze(["service.py", "app.ts"])

    assert report.completion is Completion.PARTIAL
    assert any(item.code == "SARJ012" for item in report.diagnostics)
    assert report.coverage[0].source == "eslint"
    assert report.exit_code == 2


def test_policy_analysis_applies_manifest_scope_and_baseline_while_raw_does_not(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    (tmp_path / "outside.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    baseline = tmp_path / ".sarj-python-baseline.json"
    baseline.write_text('{"selected/service.py":{"SARJ012":1}}\n', encoding="utf-8")
    (tmp_path / ".sarj-standards.toml").write_text(
        f'version = "{api.__version__}"\nprofile = "standard"\nconfigs = []\n'
        '[dest]\npython = "."\ntypescript = "."\n'
        '[hooks]\nmanager = "none"\n'
        '[verify]\npaths = ["selected"]\n'
        f'[gradual]\npython_baseline = "{baseline.name}"\n',
        encoding="utf-8",
    )

    policy = api.Standards(tmp_path).analyze()
    raw = api.Standards(tmp_path).analyze(mode=api.AnalysisMode.RAW)

    assert not [item for item in policy.diagnostics if item.code == "SARJ012"]
    assert {item.location.path for item in raw.diagnostics if item.code == "SARJ012"} == {
        "outside.py",
        "selected/service.py",
    }


def test_policy_analysis_includes_application_library_policy(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(
            api.__version__,
            (),
            ".",
            ".",
            profile="application",
            hook_manager="none",
        ).render(),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("requests==2\n", encoding="utf-8")

    policy = api.Standards(tmp_path).analyze()
    raw = api.Standards(tmp_path).analyze(mode=api.AnalysisMode.RAW)

    assert [item.code for item in policy.diagnostics if item.source == "sarj-library-policy"] == ["LIB004"]
    assert not [item for item in raw.diagnostics if item.source == "sarj-library-policy"]


def test_analysis_normalizes_public_string_enums_and_rejects_invalid_values(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    standards = api.Standards(tmp_path)

    enum_report = standards.analyze(["service.py"], mode=api.AnalysisMode.POLICY, trust=api.TrustMode.SAFE)
    string_report = standards.analyze(["service.py"], mode="policy", trust="safe")
    invalid = standards.analyze(["service.py"], mode="unknown")

    assert to_json(enum_report) == to_json(string_report)
    assert invalid.conclusion is Conclusion.INCONCLUSIVE
    assert invalid.issues[0].kind == "invalid-input"
    assert invalid.exit_code == 2


def test_analysis_renderers_are_independent_of_explicit_input_order(tmp_path: Path) -> None:
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("import logging\n", encoding="utf-8")

    first = api.Standards(tmp_path).analyze(["b.py", "a.py"])
    second = api.Standards(tmp_path).analyze(["a.py", "b.py"])

    assert to_json(first) == to_json(second)
    assert to_sarif(first) == to_sarif(second)
    assert to_text(first) == to_text(second)
    assert to_github(first) == to_github(second)


def test_partial_execution_retains_findings_as_an_independent_conclusion(tmp_path: Path) -> None:
    diagnostic = Diagnostic("TEST008", "found", Severity.ERROR, "complete", Location("example.py"))
    issue = ExecutionIssue("failed", "crash", "boom")

    report = report_from_tools(
        tmp_path,
        (
            ToolReport("complete", Completion.COMPLETE, diagnostics=(diagnostic,)),
            ToolReport("failed", Completion.FAILED, issues=(issue,)),
        ),
    )

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.FINDINGS
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].code == diagnostic.code
    assert report.diagnostics[0].fingerprint is not None
    assert report.exit_code == 2
