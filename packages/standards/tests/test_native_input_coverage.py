from __future__ import annotations

from dataclasses import replace
import errno
from pathlib import Path

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    Completion,
    Conclusion,
    CoverageDisposition,
    CoverageNotice,
    ToolReport,
)
from sarj_standards.libs.linting import repo_standards, runner
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


_ENGINES = (
    ("document.sql", "sql:prefer-jsonb", "sarj-sql-lint"),
    ("main.tf", "iac:no-environment-conditional", "sarj-iac-lint"),
)


def test_covered_report_stays_incomplete_through_tool_and_severity_transforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coverage = (CoverageNotice("sql", "requested input unavailable", 1),)
    original = AnalysisReport.from_tools(tmp_path, (ToolReport("fixture", Completion.COMPLETE),), coverage=coverage)

    def repository_report(root: Path, *, staged: bool) -> ToolReport:
        assert root == tmp_path
        assert not staged
        return ToolReport("repo-standards", Completion.COMPLETE)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate the repository integration boundary so this regression exercises report composition without Git execution.
        repo_standards, "analyze", repository_report
    )
    shell = api._with_shell_format_severity(original, paths=None, staged=False, changed_scope=None)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise coverage preservation through the internal report transform.
    warning = api._with_warning_severity(shell, frozenset({RuleSelector(RuleEngine.PYTHON, RuleId("unrelated"))}))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the nonempty-selector transformation path.
    library = api._with_library_policy(tmp_path, warning, [], Policy.from_manifest(tmp_path, None))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise real library-tool composition with an empty private fixture.
    repository = api._with_repository_analysis(tmp_path, library, staged=False)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the successful repository-tool append path.

    for report in (shell, warning, library, repository):
        assert report.coverage == coverage
        assert report.completion is Completion.PARTIAL
        assert report.conclusion is Conclusion.INCONCLUSIVE
        assert report.exit_code == 2
        assert not report.diagnostics
    assert [tool.name for tool in repository.tools] == ["fixture", "repo-standards", "sarj-library-policy"]


def test_coverage_append_preserves_distinct_notices_and_exact_duplicate_order(tmp_path: Path) -> None:
    failed = CoverageNotice("sql", "input unavailable", 1)
    original = AnalysisReport.from_tools(tmp_path, (), coverage=(failed,))
    different_count = replace(failed, file_count=2)
    different_reason = replace(failed, reason="another unavailable input")
    nonblocking = replace(failed, disposition=CoverageDisposition.EXCLUDED)

    appended = api._with_coverage(original, (failed, different_count, different_reason, nonblocking, different_count))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise explicit append and complete-value deduplication semantics.
    repeated = api._with_coverage(appended, (failed, nonblocking))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- repeated notices must not change coverage contents or order.

    assert appended.coverage == (failed, different_count, different_reason, nonblocking)
    assert repeated.coverage == appended.coverage
    assert repeated.completion is Completion.PARTIAL
    assert repeated.conclusion is Conclusion.INCONCLUSIVE
    assert repeated.exit_code == 2
    assert api._with_coverage(appended, ()) is appended  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- an empty append preserves the original report identity.
    replacement = AnalysisReport.from_tools(tmp_path, original.tools, coverage=(nonblocking,))
    assert replacement.coverage == (nonblocking,)
    assert replacement.completion is Completion.COMPLETE
    assert replacement.exit_code == 0


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
@pytest.mark.parametrize("size", [500_001, 2 * 1024 * 1024], ids=("over-native-limit", "outer-runner-limit"))
@pytest.mark.parametrize("requested", ["file", "directory"])
def test_native_size_rejection_cannot_report_clean_analysis(
    tmp_path: Path, name: str, selector: str, engine: str, size: int, *, requested: str
) -> None:
    source = tmp_path / name
    source.write_bytes(b" " * size)

    report = api.Standards(tmp_path).analyze([name if requested == "file" else "."], rules=[selector])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert not report.diagnostics
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]
    assert "500,000-byte analysis limit" in report.issues[0].message
    assert name in report.issues[0].message
    assert [(tool.name, tool.completion) for tool in report.tools] == [(engine, Completion.FAILED)]


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_native_read_failure_cannot_report_clean_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, selector: str, engine: str
) -> None:
    source = tmp_path / name
    source.write_text("", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def unreadable_bytes(path: Path) -> bytes:
        if path == source:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read_bytes(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- fail the real native filesystem read while preserving Standards routing and normalization.
        Path, "read_bytes", unreadable_bytes
    )

    report = api.Standards(tmp_path).analyze([name], rules=[selector])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]
    assert "PermissionError" in report.issues[0].message
    assert name in report.issues[0].message


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_native_input_failure_preserves_another_engines_findings(
    tmp_path: Path, name: str, selector: str, engine: str
) -> None:
    (tmp_path / name).write_bytes(b" " * 500_001)
    (tmp_path / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze([name, "service.py"], rules=[selector, "python:no-secret-in-log"])

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.FINDINGS
    assert report.exit_code == 2
    assert [(finding.source, finding.code) for finding in report.diagnostics] == [("sarj-python-lint", "SARJ012")]
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]


@pytest.mark.parametrize("name", ["document.sql", "main.tf"])
def test_legacy_runner_propagates_native_input_rejection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    source = tmp_path / name
    source.write_bytes(b" " * 500_001)

    assert runner.run([str(source)]) == 2
    captured = capsys.readouterr()
    assert "500,000-byte analysis limit" in captured.err
    assert name in captured.err


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_intentionally_excluded_oversized_input_retains_nonblocking_coverage(
    tmp_path: Path, name: str, selector: str, engine: str
) -> None:
    source = tmp_path / "generated" / name
    source.parent.mkdir()
    source.write_bytes(b" " * 500_001)
    adopted = Manifest(
        version="1.2.3",
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_paths=("generated/**",),
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze([f"generated/{name}"], rules=[selector])

    assert report.completion is Completion.COMPLETE
    assert report.conclusion is Conclusion.PASSED
    assert report.exit_code == 0
    assert not report.issues
    assert not any(tool.name == engine for tool in report.tools)
    assert [(notice.file_count, notice.disposition) for notice in report.coverage] == [
        (1, CoverageDisposition.EXCLUDED)
    ]
