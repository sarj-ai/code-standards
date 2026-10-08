from __future__ import annotations

from threading import Barrier
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    ToolReport,
    baseline,
)
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.analysis import report_from_tools


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.diagnostics import AnalysisReport


@pytest.mark.parametrize("failed", [False, True], ids=("complete", "analyzer-failure"))
def test_mixed_baseline_scans_overlap_once_and_preserve_selected_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    path = tmp_path / "diagnostic-baseline.json"
    prior = baseline.render(
        (), bundle_version=api.__version__, consumer_base_sha="0" * 40, catalog_digest=baseline.bundled_catalog_digest()
    )
    path.write_text(prior)
    ready = Barrier(2, timeout=10)
    calls: list[str] = []

    def analyze(_self: api.Standards, _paths: object = None, **kwargs: object) -> AnalysisReport:
        assert kwargs["rules"] == ["python:no-dunder-all"]
        assert kwargs["jobs"] == 1
        calls.append("native")
        ready.wait()
        return report_from_tools(tmp_path, ())

    def eslint(_files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        assert kwargs["capabilities"] == frozenset({"eslint"})
        calls.append("eslint")
        ready.wait()
        issues = (ExecutionIssue("eslint", "execution-failure", "unavailable"),) if failed else ()
        findings = tuple(
            Diagnostic(
                "RULE", rule, Severity.ERROR, "eslint", Location("source.ts"), rule_id=rule, fingerprint=letter * 64
            )
            for rule, letter in [
                ("@sarj/require-pascal-case-zod-schema-name", "a"),
                ("unicorn/prefer-iterator-helpers", "b"),
                ("unselected", "c"),
            ]
        )
        return (ToolReport("eslint", Completion.FAILED if failed else Completion.COMPLETE, findings, issues),)

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- observes scoped analyzer routing
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- synchronizes external scan boundary
        external, "analyze_external", eslint
    )
    result = cli_main(
        [
            "--root",
            str(tmp_path),
            "baseline",
            "update",
            "--output",
            str(path),
            "--jobs",
            "2",
            "--rule",
            "python:no-dunder-all",
            "--rule",
            "eslint:@sarj/require-pascal-case-zod-schema-name",
            "--rule",
            "eslint:unicorn/prefer-iterator-helpers",
        ]
    )
    assert sorted(calls) == ["eslint", "native"]
    assert result == (2 if failed else 0)
    if failed:
        assert path.read_text() == prior
    else:
        assert baseline.load(path) == {"a" * 64: 1, "b" * 64: 1}


def test_combining_eslint_scans_still_rejects_unknown_custom_selectors(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("unchanged")
    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(path),
                "--rule",
                "eslint:@sarj/not-a-rule",
                "--rule",
                "eslint:unicorn/prefer-iterator-helpers",
            ]
        )
        == 2
    )
    assert path.read_text() == "unchanged"


@pytest.mark.parametrize("jobs", [1, 2])
def test_single_baseline_operation_uses_requested_analysis_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jobs: int
) -> None:
    seen: list[int] = []

    def analyze(_self: api.Standards, _paths: object = None, **kwargs: object) -> AnalysisReport:
        assert kwargs["jobs"] == jobs
        seen.append(jobs)
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- observes the analyzer worker budget
    assert cli_main(["--root", str(tmp_path), "baseline", "init", "--jobs", str(jobs)]) == 0
    assert seen == [jobs]
