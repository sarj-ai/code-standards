from __future__ import annotations

from dataclasses import replace
import json
from threading import Event
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.diagnostics import (
    AnalyzerId,
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Position,
    Region,
    Severity,
    ToolReport,
    TrustMode,
)
from sarj_standards.libs.linting import external, shell_format
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessOutput
from sarj_standards.libs.linting.runner import GroupedPaths
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_standards.libs.adoption.manifest import Manifest
    from sarj_standards.libs.linting.execution_plan import RuffProjectPlan, ShellCheckFamilyPlan


@pytest.mark.parametrize(
    "jobs",
    [0, 3, True, False, 1.0, 2.0, "1", None, pytest.param([1], id="mutable-list")],
)
@pytest.mark.parametrize("include_external", [False, True])
def test_api_rejects_invalid_jobs_before_reading_analysis_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, jobs: int, *, include_external: bool
) -> None:
    def unexpected_manifest(_root: Path, _mode: api.AnalysisMode) -> Manifest | None:
        pytest.fail("invalid jobs must be rejected before reading the adoption manifest")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the first input read after real validation.
        api, "_analysis_manifest", unexpected_manifest
    )

    report = api.Standards(tmp_path).analyze(["missing.py"], external=include_external, jobs=jobs)

    assert report.completion is Completion.FAILED
    assert report.conclusion is api.Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert report.issues == (ExecutionIssue("sarj-standards", "invalid-input", "analysis jobs must be 1 or 2"),)


def test_ruff_plan_keeps_post_primary_selection_required_proof_and_complete_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_project, second_project = tmp_path / "a", tmp_path / "b"
    first_project.mkdir()
    second_project.mkdir()
    for project in (first_project, second_project):
        (project / "ruff.toml").write_text("[lint]\nselect = ['F401']\n", encoding="utf-8")
    first, second = first_project / "app.py", second_project / "app.py"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("#\nimport os\n", encoding="utf-8")
    calls: list[tuple[str, bool]] = []
    plans: list[RuffProjectPlan] = []
    execute_project = external._execute_ruff_project  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- forward the real cohort.

    def observe_plan(plan: RuffProjectPlan) -> ToolReport:
        plans.append(plan)
        return execute_project(plan)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe cohorts; retain their real passes and proof.
        external, "_execute_ruff_project", observe_plan
    )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv[0] == "ruff"
        required = "--ignore-noqa" in argv
        calls.append((cwd.name, required))
        if cwd == first_project:
            if not required:
                # The required-file decision must happen after this pass, even when it fails.
                first.write_text('import typing\nvalue = getattr(typing, "cast")\n', encoding="utf-8")
                return ProcessOutput(2, "", "primary unavailable")
            assert calls == [("a", False), ("a", True)]
            return ProcessOutput(0, "[]", "")
        assert calls[:2] == [("a", False), ("a", True)]
        if required:
            return ProcessOutput(2, "", "required unavailable")
        return ProcessOutput(
            1,
            json.dumps(
                [
                    {
                        "filename": str(second),
                        "location": {"row": 2, "column": 1},
                        "end_location": {"row": 2, "column": 7},
                        "code": "F401",
                        "message": "unused import",
                    }
                ]
            ),
            "",
        )

    reports = external.analyze_external(
        [str(second), str(first)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"ruff"}),
        runner=FakeProcessExecutor(runner),
    )

    assert calls == [("a", False), ("a", True), ("b", False), ("b", True)]
    assert [(plan.project, plan.config, plan.files) for plan in plans] == [
        (first_project, first_project / "ruff.toml", (str(first),)),
        (second_project, second_project / "ruff.toml", (str(second),)),
    ]
    assert tuple(replace(report, duration_ms=0) for report in reports) == (
        ToolReport(
            "ruff",
            Completion.FAILED,
            diagnostics=(
                Diagnostic(
                    "banned-api",
                    "`typing.cast` is banned even through a literal getattr lookup; "
                    "use explicit narrowing or a typed contract.",
                    Severity.ERROR,
                    "ruff",
                    Location("a/app.py", region=Region(Position(1, 8, 22), Position(1, 31, 45))),
                    rule_id="banned-api",
                    notes=("Standards source proof supplements native Ruff resolution for this indirect access.",),
                    tags=("non-baselineable", "required-source-policy", "required-cast-policy"),
                ),
            ),
            issues=(ExecutionIssue("ruff", "tool-failure", "primary unavailable", 2),),
            analyzer_id=AnalyzerId("ruff"),
            invocation_id=InvocationId("ruff:a"),
            duration_ms=0,
            file_count=1,
        ),
        ToolReport(
            "ruff",
            Completion.FAILED,
            diagnostics=(
                Diagnostic(
                    "F401",
                    "unused import",
                    Severity.ERROR,
                    "ruff",
                    Location("b/app.py", region=Region(Position(1, 0, 2), Position(1, 6, 8))),
                    rule_id="F401",
                ),
            ),
            issues=(ExecutionIssue("ruff", "tool-failure", "required unavailable", 2),),
            analyzer_id=AnalyzerId("ruff"),
            invocation_id=InvocationId("ruff:b"),
            duration_ms=0,
            file_count=1,
        ),
    )


@pytest.mark.parametrize("matching_version", [False, True])
def test_shellcheck_plan_attests_before_batches_and_preserves_partial_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, matching_version: bool
) -> None:
    # Reverse order distinguishes slice-then-sort from sorting the whole selection first.
    files = tuple(str(tmp_path / f"{number:03d}.sh") for number in range(251, 0, -1))
    for number in range(1, 252):
        (tmp_path / f"{number:03d}.sh").write_text('echo "$value"\n', encoding="utf-8")
    unsupported = tmp_path / "fixture.zsh"
    unsupported.write_text("#!/bin/zsh\nprintf fixture\n", encoding="utf-8")
    attested = Event()
    batches: list[tuple[str, ...]] = []
    plans: list[ShellCheckFamilyPlan] = []
    execute_family = external._execute_shellcheck_family  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- forward the real family.

    def observe_plan(plan: ShellCheckFamilyPlan) -> tuple[ToolReport, ...]:
        plans.append(plan)
        return execute_family(plan)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- forward real attestation and batches while observing their plan.
        external, "_execute_shellcheck_family", observe_plan
    )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if tuple(argv) == ("shellcheck", "--version"):
            assert not batches
            attested.set()
            version = "0.11.0" if matching_version else "0.10.0"
            return ProcessOutput(0, f"ShellCheck\nversion: {version}\n", "")
        assert attested.is_set()
        batch = tuple(argv[argv.index("--") + 1 :])
        batches.append(batch)
        if len(batches) == 1:
            return ProcessOutput(2, "", "first batch unavailable")
        return ProcessOutput(
            1,
            json.dumps(
                {
                    "comments": [
                        {
                            "file": batch[0],
                            "line": 1,
                            "column": 1,
                            "endLine": 1,
                            "endColumn": 5,
                            "level": "warning",
                            "code": 2086,
                            "message": "fixture shell diagnostic",
                        }
                    ]
                }
            ),
            "",
        )

    execute = FakeProcessExecutor(runner, capabilities=ProcessCapabilities())
    reports = external.analyze_external(
        [*files, str(unsupported)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"shellcheck"}),
        grouped=GroupedPaths(shellcheck=list(files), unsupported_shell=[str(unsupported)]),
        runner=execute,
    )

    assert len(plans) == 1
    assert plans[0].files == files
    assert plans[0].unsupported_files == (str(unsupported),)
    assert attested.is_set()
    assert execute.requests[0].timeout_seconds == 5
    unsupported_report = ToolReport(
        "shellcheck",
        Completion.FAILED,
        issues=(
            ExecutionIssue(
                "shellcheck",
                "coverage-missing",
                "ShellCheck does not support zsh; 1 selected zsh path(s) were not analyzed",
            ),
        ),
        analyzer_id=AnalyzerId("shellcheck"),
        invocation_id=InvocationId("shellcheck:zsh"),
        file_count=1,
    )
    if not matching_version:
        assert batches == []
        assert len(execute.requests) == 1
        assert reports == (
            unsupported_report,
            ToolReport(
                "shellcheck",
                Completion.FAILED,
                issues=(
                    ExecutionIssue(
                        "shellcheck",
                        "version-mismatch",
                        "ShellCheck 0.10.0 is installed; exact version 0.11.0 is required",
                        0,
                    ),
                ),
                analyzer_id=AnalyzerId("shellcheck"),
                invocation_id=InvocationId("shellcheck:version"),
                file_count=251,
            ),
        )
        return
    assert batches == [tuple(sorted(files[:250])), files[250:]]
    assert all(request.timeout_seconds == 900 for request in execute.requests[1:])
    assert reports[0] == unsupported_report
    assert tuple(replace(report, duration_ms=0) for report in reports[1:]) == (
        ToolReport(
            "shellcheck",
            Completion.FAILED,
            issues=(ExecutionIssue("shellcheck", "tool-failure", "first batch unavailable", 2),),
            analyzer_id=AnalyzerId("shellcheck"),
            invocation_id=InvocationId("shellcheck:1"),
            version="0.11.0",
            duration_ms=0,
            file_count=250,
        ),
        ToolReport(
            "shellcheck",
            Completion.COMPLETE,
            diagnostics=(
                Diagnostic(
                    "SC2086",
                    "fixture shell diagnostic",
                    Severity.WARNING,
                    "shellcheck",
                    Location("001.sh", region=Region(Position(0, 0, 0), Position(0, 4, 4))),
                    rule_id="SC2086",
                ),
            ),
            analyzer_id=AnalyzerId("shellcheck"),
            invocation_id=InvocationId("shellcheck:2"),
            version="0.11.0",
            duration_ms=0,
            file_count=1,
        ),
    )


def test_shellcheck_family_finishes_before_separate_format_and_embedded_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "fixture.sh"
    source.write_text("#!/bin/sh\nprintf fixture\n", encoding="utf-8")
    calls: list[str] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if tuple(argv) == ("shellcheck", "--version"):
            calls.append("attest")
            return ProcessOutput(0, "ShellCheck\nversion: 0.11.0\n", "")
        assert calls == ["attest"]
        calls.append("batch")
        return ProcessOutput(0, '{"comments":[]}', "")

    def format_sources(*, root: Path, paths: Sequence[str]) -> tuple[ToolReport, ...]:
        assert root == tmp_path
        assert tuple(paths) == (str(source),)
        assert calls == ["attest", "batch"]
        calls.append("shfmt")
        return (ToolReport("shfmt", Completion.COMPLETE),)

    def embedded_sources(
        _grouped: GroupedPaths, *, root: Path, capabilities: frozenset[str] | None
    ) -> tuple[ToolReport, ...]:
        assert root == tmp_path
        assert capabilities == frozenset({"shellcheck", "shfmt"})
        assert calls == ["attest", "batch", "shfmt"]
        calls.append("embedded")
        return (ToolReport("embedded", Completion.COMPLETE),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the opaque formatter stage without starting its worker pool.
        shell_format, "analyze_sources", format_sources
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the separate stage after real ShellCheck dispatch.
        external, "_embedded_shell_reports", embedded_sources
    )

    reports = external.analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"shellcheck", "shfmt"}),
        grouped=GroupedPaths(shellcheck=[str(source)]),
        runner=FakeProcessExecutor(runner, capabilities=ProcessCapabilities()),
    )

    assert calls == ["attest", "batch", "shfmt", "embedded"]
    assert [report.name for report in reports] == ["shellcheck", "shfmt", "embedded"]
