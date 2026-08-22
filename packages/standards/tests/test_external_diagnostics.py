from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError
import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import (
    ProcessOutput,
    analyze_external,
    parse_basedpyright,
    parse_eslint,
    parse_react_doctor,
    parse_ruff,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def test_ruff_json_becomes_an_exact_canonical_region(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("import os\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filename": str(source),
                "location": {"row": 1, "column": 1},
                "end_location": {"row": 1, "column": 7},
                "code": "F401",
                "message": "unused import",
                "url": "https://docs.astral.sh/ruff/rules/unused-import/",
            }
        ]
    )

    finding = parse_ruff(payload, root=tmp_path)[0]

    assert finding.code == "F401"
    assert finding.location.path == "example.py"
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == 0
    assert finding.location.region.end.byte_offset == 6


def test_react_doctor_v3_json_becomes_a_blocking_canonical_region(tmp_path: Path) -> None:
    source = tmp_path / "src" / "button.tsx"
    source.parent.mkdir()
    source.write_text("export const Button = () => <button />;\n", encoding="utf-8")
    diagnostic: dict[str, object] = {
        "filePath": "src/button.tsx",
        "plugin": "react-doctor",
        "rule": "button-has-type",
        "severity": "error",
        "message": "Button needs an explicit type.",
        "help": "Add type=button.",
        "line": 1,
        "column": 28,
        "endLine": 1,
        "endColumn": 36,
        "category": "Bugs",
        "id": "stable-id",
        "normalizedFilePath": "src/button.tsx",
        "tags": [],
    }
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "mode": "full",
            "reactDetected": True,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "directory": str(tmp_path),
            "diff": None,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "packageRoot": str(tmp_path),
                    "framework": "react",
                    "project": {},
                    "diagnostics": [diagnostic],
                    "score": None,
                    "skippedChecks": [],
                    "analyzedFiles": ["src/button.tsx"],
                    "analyzedFileCount": 1,
                    "complete": True,
                    "scannedFileCount": 1,
                    "elapsedMilliseconds": 1,
                }
            ],
            "skippedProjects": [],
            "diagnostics": [diagnostic],
            "summary": {
                "errorCount": 1,
                "warningCount": 0,
                "affectedFileCount": 1,
                "totalDiagnosticCount": 1,
                "score": None,
                "scoreLabel": None,
            },
            "elapsedMilliseconds": 1,
            "error": None,
        }
    )

    finding = parse_react_doctor(payload, root=tmp_path)[0]

    assert finding.code == "react-doctor/button-has-type"
    assert finding.rule_id == "react-doctor/button-has-type"
    assert finding.severity is Severity.ERROR
    assert finding.location.path == "src/button.tsx"
    assert finding.location.region is not None


def test_react_doctor_rejects_empty_project_coverage(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="no analyzed projects"):
        parse_react_doctor(payload, root=tmp_path)


def test_react_doctor_accepts_empty_staged_report_without_analyzable_sources(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "diagnostics": [],
            "error": None,
        }
    )

    assert (
        parse_react_doctor(
            payload,
            root=tmp_path,
            expected_projects=frozenset({tmp_path.resolve()}),
            allow_empty_projects=True,
        )
        == ()
    )


def test_react_doctor_rejects_empty_report_with_top_level_diagnostics(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "diagnostics": [
                {
                    "filePath": "component.tsx",
                    "plugin": "react-doctor",
                    "rule": "example",
                    "severity": "warning",
                    "message": "example",
                    "line": 1,
                    "column": 1,
                }
            ],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="diagnostics without an analyzed project"):
        parse_react_doctor(payload, root=tmp_path, allow_empty_projects=True)


def test_react_doctor_zero_coordinates_become_a_path_only_location(tmp_path: Path) -> None:
    source = tmp_path / "package.json"
    source.write_text('{"private": true}\n', encoding="utf-8")
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "reactDetected": True,
            "baselineDegraded": False,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "skippedChecks": [],
                    "analyzedFileCount": 2,
                    "scannedFileCount": 2,
                    "diagnostics": [
                        {
                            "filePath": "package.json",
                            "plugin": "react-doctor",
                            "rule": "project-configuration",
                            "severity": "warning",
                            "message": "Project configuration needs attention.",
                            "line": 0,
                            "column": 0,
                            "endLine": 0,
                            "endColumn": 0,
                        }
                    ],
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    finding = parse_react_doctor(payload, root=tmp_path, include_warnings=True)[0]

    assert finding.location.path == "package.json"
    assert finding.location.position is None
    assert finding.location.region is None


def test_react_doctor_accepts_omitted_false_baseline_degraded_metadata(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "reactDetected": True,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "skippedChecks": [],
                    "analyzedFileCount": 1,
                    "scannedFileCount": 1,
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    assert parse_react_doctor(payload, root=tmp_path, expected_projects=frozenset({tmp_path.resolve()})) == ()


def test_react_doctor_rejects_incomplete_projects(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [{"directory": str(tmp_path), "complete": False}],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="did not complete"):
        parse_react_doctor(payload, root=tmp_path)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"reactDetected": False}, "did not detect React"),
        ({"baselineDegraded": True}, "baseline degraded"),
    ],
)
def test_react_doctor_fails_closed_on_degraded_coverage(tmp_path: Path, extra: dict[str, object], message: str) -> None:
    payload = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "projects": [{"directory": str(tmp_path), "complete": True}],
        "skippedProjects": [],
        "error": None,
        **extra,
    }

    with pytest.raises(ValueError, match=message):
        parse_react_doctor(json.dumps(payload), root=tmp_path)


def test_react_doctor_protocol_rejects_coerced_schema_types(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": "3",
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValidationError, match="schemaVersion"):
        parse_react_doctor(payload, root=tmp_path)


def test_react_doctor_protocol_rejects_boolean_coordinates(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "diagnostics": [
                        {
                            "filePath": "app.tsx",
                            "plugin": "react-doctor",
                            "rule": "example",
                            "severity": "error",
                            "message": "example",
                            "line": True,
                            "column": 1,
                        }
                    ],
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValidationError, match="line"):
        parse_react_doctor(payload, root=tmp_path)


def test_react_doctor_discovers_independent_react_projects(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    react_project = tmp_path / "apps" / "react-app"
    next_project = tmp_path / "demos" / "next-app"
    ignored_project = tmp_path / "node_modules" / "third-party"
    for project, package in (
        (react_project, "react"),
        (next_project, "next"),
        (ignored_project, "react"),
    ):
        project.mkdir(parents=True)
        (project / "package.json").write_text(
            json.dumps({"dependencies": {package: "1.0.0"}}),
            encoding="utf-8",
        )

    assert external_module._react_project_roots(tmp_path) == (  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        react_project.resolve(),
        next_project.resolve(),
    )


def test_react_doctor_honors_manifest_doctor_project_exclusions(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    included = tmp_path / "apps" / "web"
    excluded = tmp_path / "demos" / "historical"
    for project in (included, excluded):
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    adopted = manifest.Manifest(
        "5.13.5",
        ("eslint",),
        ".",
        ".",
        doctor_excluded_paths=("demos/**",),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    selection = external_module._selected_react_doctor_projects(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        enabled=True,
        has_typescript=True,
        capabilities=frozenset({"eslint"}),
    )

    assert selection == (tmp_path, (included.resolve(),))


def test_react_metadata_only_scope_still_runs_doctor(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": True,
                    "baselineDegraded": False,
                    "projects": [
                        {
                            "directory": str(cwd),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 1,
                            "scannedFileCount": 1,
                        }
                    ],
                    "skippedProjects": [],
                    "error": None,
                }
            ),
            "",
        )

    reports = analyze_external(
        (str(package),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
        include_react_doctor=True,
    )

    assert [item.name for item in reports] == ["react-doctor"]
    assert any("react-doctor" in item for command in seen for item in command)


@pytest.mark.parametrize(
    ("changed", "expected_completion"),
    [
        ("doctor.config.json\0package.json\0diagnostic-baseline.json\0", Completion.COMPLETE),
        ("apps/web/src/component.tsx\0", Completion.FAILED),
    ],
)
def test_react_doctor_only_accepts_empty_degraded_changed_scope_without_project_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed: str,
    expected_completion: Completion,
) -> None:
    base = "a" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        if argv[0] == "git":
            return ProcessOutput(0, changed, "")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "diff",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is expected_completion
    assert seen[0] == (
        "git",
        "diff",
        f"{base}...HEAD",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        "--",
    )
    if expected_completion is Completion.FAILED:
        assert "baseline degraded" in report.issues[0].message


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            ("a" * 40, ".sarj-standards.toml\0diagnostic-baseline.json\0", 2, 0, 0, Completion.COMPLETE),
            id="exact-automations-config-only-scope",
        ),
        pytest.param(
            ("a" * 40, "apps/landing-page/src/page.tsx\0", 1, 0, 0, Completion.FAILED),
            id="react-source-remains-blocking",
        ),
        pytest.param(
            ("a" * 40, ".sarj-standards.toml\0diagnostic-baseline.json\0", 3, 0, 0, Completion.FAILED),
            id="changed-file-count-mismatch",
        ),
        pytest.param(
            ("../unsafe", ".sarj-standards.toml\0", 1, 0, 0, Completion.FAILED),
            id="unsafe-reported-base",
        ),
        pytest.param(
            ("main", ".sarj-standards.toml\0", 1, 128, 0, Completion.FAILED),
            id="unresolved-reported-base",
        ),
        pytest.param(
            ("main", ".sarj-standards.toml\0", 1, 0, 1, Completion.FAILED),
            id="non-ancestor-reported-base",
        ),
    ],
)
def test_react_doctor_validates_reported_degraded_changed_scope_before_allowing_empty_projects(
    tmp_path: Path,
    case: tuple[str, str, int, int, int, Completion],
) -> None:
    reported_base, changed, reported_count, resolve_status, ancestor_status, expected_completion = case
    resolved_base = "b" * 40
    project = tmp_path / "apps" / "landing-page"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        if argv[:2] == ("git", "rev-parse"):
            assert cwd == tmp_path
            return ProcessOutput(resolve_status, f"{resolved_base}\n" if resolve_status == 0 else "", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            assert cwd == tmp_path
            return ProcessOutput(ancestor_status, "", "")
        if argv[:2] == ("git", "diff"):
            assert cwd == tmp_path
            return ProcessOutput(0, changed, "")
        assert cwd == tmp_path
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "diff",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "diff": {"baseBranch": reported_base, "changedFileCount": reported_count},
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=2,
        staged=False,
    )

    assert report.completion is expected_completion
    if expected_completion is Completion.COMPLETE:
        assert report.diagnostics == ()
        assert report.issues == ()
        assert ("git", "diff", f"{resolved_base}...HEAD", "--name-only", "--diff-filter=ACMR", "-z", "--") in seen
    else:
        assert "baseline degraded" in report.issues[0].message


def test_react_doctor_accepts_empty_staged_scope_without_selected_project_source(tmp_path: Path) -> None:
    project = tmp_path / "typescript" / "packages" / "app"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        if argv[0] == "git":
            return ProcessOutput(
                0,
                "typescript/eslint.strict.mjs\0typescript/packages/app/package.json\0diagnostic-baseline.json\0",
                "",
            )
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=3,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert report.diagnostics == ()
    assert report.issues == ()
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
    assert "--staged" in seen[1]
    assert len(seen) == 2


@pytest.mark.parametrize(
    "staged_path",
    [
        "apps/web/src/component.tsx",
        "apps/web/src/page.astro",
        "apps/web/public/fragment.html",
        "../apps/web/src/unsafe.tsx",
    ],
)
def test_react_doctor_rejects_empty_staged_scope_with_candidate_or_unsafe_path(
    tmp_path: Path,
    staged_path: str,
) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(0, f"{staged_path}\0", "")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message


def test_react_doctor_empty_staged_scope_fails_closed_when_git_diff_fails(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(128, "", "index unavailable")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message


def test_react_doctor_empty_degraded_scope_fails_closed_when_git_diff_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_BASE", "b" * 40)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(128, "", "invalid base")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "baseline degraded" in report.issues[0].message


def test_react_doctor_staged_non_detection_falls_back_to_full_and_filters_exact_paths(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    staged_source = project / "staged.tsx"
    staged_source.write_text('export const Image = () => <img src="avatar.png" />;\n', encoding="utf-8")
    unrelated_source = project / "unrelated.tsx"
    unrelated_source.write_text('export const Other = () => <img src="other.png" />;\n', encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def diagnostic(path: Path) -> dict[str, object]:
        return {
            "filePath": str(path),
            "plugin": "react-doctor",
            "rule": "alt-text",
            "severity": "error",
            "message": "Image elements must have alternative text.",
            "line": 1,
            "column": 28,
        }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        if argv[0] == "git":
            return ProcessOutput(0, "apps/web/staged.tsx\0", "")
        is_full = "--scope" in argv and argv[argv.index("--scope") + 1] == "full"
        diagnostics = [diagnostic(staged_source), diagnostic(unrelated_source)] if is_full else []
        return ProcessOutput(
            1 if diagnostics else 0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": is_full,
                    "projects": [
                        {
                            "directory": str(project),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 2 if is_full else 1,
                            "scannedFileCount": 2 if is_full else 1,
                            "diagnostics": diagnostics,
                        }
                    ],
                    "diagnostics": diagnostics,
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("apps/web/staged.tsx",)
    assert report.diagnostics[0].code == "react-doctor/alt-text"
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
    assert "--staged" in seen[1]
    assert seen[2] == seen[0]
    scope_index = seen[3].index("--scope")
    assert seen[3][scope_index + 1] == "full"
    duration_index = seen[3].index("--max-duration")
    assert int(seen[3][duration_index + 1]) >= 60


def test_react_doctor_full_scan_still_rejects_non_detection(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv
        assert cwd == tmp_path
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [{"directory": str(project), "complete": True}],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
        full_scan=True,
    )

    assert report.completion is Completion.FAILED
    assert "did not detect React" in report.issues[0].message


def test_react_doctor_staged_fallback_rejects_malformed_scoped_coverage(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [{"directory": str(project), "complete": False}],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "did not complete" in report.issues[0].message
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("git", "index unavailable"),
        ("full-exit", "full scan crashed"),
        ("full-empty", "empty structured output"),
    ],
)
def test_react_doctor_staged_fallback_failures_remain_blocking(
    tmp_path: Path,
    failure: str,
    expected_message: str,
) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            if failure == "git":
                return ProcessOutput(128, "", "index unavailable")
            return ProcessOutput(0, "apps/web/staged.tsx\0", "")
        if "--scope" in argv:
            if failure == "full-exit":
                return ProcessOutput(2, "", "full scan crashed")
            return ProcessOutput(0, "", "")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [
                        {
                            "directory": str(project),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 1,
                            "scannedFileCount": 1,
                            "diagnostics": [],
                        }
                    ],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert expected_message in report.issues[0].message


def test_react_doctor_uses_native_staged_scope_for_precommit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    (tmp_path / "package.json").write_text(
        '{"packageManager":"npm@11.5.2","dependencies":{"react":"19.0.0"}}\n',
        encoding="utf-8",
    )
    source = tmp_path / "component.tsx"
    source.write_text("export const Component = () => <button />;\n", encoding="utf-8")
    untouched = tmp_path / "untouched.tsx"
    untouched.write_text("export const Untouched = () => <button />;\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    git_seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            git_seen.append(tuple(argv))
            return ProcessOutput(0, "component.tsx\0", "")
        seen.append(tuple(argv))
        return ProcessOutput(
            1,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": True,
                    "baselineDegraded": False,
                    "projects": [
                        {
                            "directory": str(tmp_path),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 2,
                            "scannedFileCount": 2,
                            "diagnostics": [
                                {
                                    "filePath": str(source),
                                    "plugin": "react-doctor",
                                    "rule": "button-has-type",
                                    "severity": "error",
                                    "message": "Button needs an explicit type.",
                                    "line": 1,
                                    "column": 32,
                                },
                                {
                                    "filePath": str(untouched),
                                    "plugin": "react-doctor",
                                    "rule": "button-has-type",
                                    "severity": "warning",
                                    "message": "Button needs an explicit type.",
                                    "line": 1,
                                    "column": 32,
                                },
                            ],
                        }
                    ],
                    "skippedProjects": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("component.tsx",)
    assert report.diagnostics[0].severity is Severity.ERROR
    assert report_from_tools(tmp_path, (report,)).exit_code == 1
    assert "--staged" in seen[0]
    assert "--scope" not in seen[0]
    blocking_index = seen[0].index("--blocking")
    assert seen[0][blocking_index + 1] == "error"
    assert "--no-warnings" in seen[0]

    changed_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert changed_report.completion is Completion.COMPLETE
    scope_index = seen[1].index("--scope")
    assert seen[1][scope_index + 1] == "changed"
    assert "--base" not in seen[1]

    event_base = "f" * 40
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"base": {"sha": event_base}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    github_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert tuple(item.location.path for item in github_report.diagnostics) == ("component.tsx",)
    github_base_index = seen[2].index("--base")
    assert seen[2][github_base_index + 1] == event_base

    monkeypatch.setenv("SARJ_REACT_DOCTOR_BASE", "0123456789abcdef")
    ci_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert ci_report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in ci_report.diagnostics) == ("component.tsx",)

    base_index = seen[3].index("--base")
    assert seen[3][base_index + 1] == "0123456789abcdef"
    assert git_seen == [
        ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--"),
        ("git", "diff", f"{event_base}...HEAD", "--name-only", "--diff-filter=ACMR", "-z", "--"),
        ("git", "diff", "0123456789abcdef...HEAD", "--name-only", "--diff-filter=ACMR", "-z", "--"),
    ]
    assert "--no-cache" in seen[0]
    duration_index = seen[0].index("--max-duration")
    assert seen[0][duration_index + 1] == "12"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ref": "refs/heads/feature", "repository": {"default_branch": "main"}}, True),
        ({"ref": "refs/heads/main", "repository": {"default_branch": "main"}}, False),
        (
            {
                "ref": "refs/heads/feature",
                "repository": {"default_branch": "main"},
                "pull_request": {"base": {"sha": "f" * 40}},
            },
            False,
        ),
        ({"ref": "refs/tags/v1.0.0", "repository": {"default_branch": "main"}}, False),
    ],
)
def test_non_default_github_push_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected: bool,
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert external_module.is_non_default_github_push() is expected


def test_non_default_branch_is_not_treated_as_a_push_for_other_github_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"ref": "refs/heads/feature", "repository": {"default_branch": "main"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert not external_module.is_non_default_github_push()


def test_external_analyzers_do_not_inherit_caller_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SARJ_AUDIT_SECRET", "must-not-leak")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted-preload.cjs")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LC_ALL", "C")

    environment = external_module._analysis_environment()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

    assert "SARJ_AUDIT_SECRET" not in environment
    assert "NODE_OPTIONS" not in environment
    assert environment["PATH"] == "/usr/bin"
    assert environment["LC_ALL"] == "C"


def test_only_eslint_receives_the_fixed_node_heap_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted-preload.cjs")
    command = (
        sys.executable,
        "-c",
        "import os; print(os.environ.get('NODE_OPTIONS', 'missing'))",
    )

    generic = external_module.run_process(command, cwd=tmp_path)
    eslint = external_module._run_eslint_process(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        command,
        cwd=tmp_path,
    )

    assert generic.stdout.strip() == "missing"
    assert eslint.stdout.strip() == "--max-old-space-size=4096"


def test_external_analyzers_prefer_the_isolated_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / "bin" / "python"
    calls: list[tuple[str, str | None]] = []

    def which(name: str, path: str | None = None) -> str | None:
        calls.append((name, path))
        return str(tmp_path / "bin" / name) if path is not None else f"/system/{name}"

    monkeypatch.setattr(external_module.sys, "executable", str(interpreter))  # pyright: ignore[reportPrivateLocalImportUsage]
    monkeypatch.setattr(external_module.shutil, "which", which)  # pyright: ignore[reportPrivateLocalImportUsage]

    assert external_module._analyzer_executable("basedpyright") == str(tmp_path / "bin" / "basedpyright")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert calls == [("basedpyright", str(tmp_path / "bin"))]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(
            ("npm", "exec", "--offline", "--", "eslint", "--", "app.ts"),
            (
                "npm",
                "exec",
                "--offline",
                "--",
                "eslint",
                "--format",
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
                "--no-warn-ignored",
                "--no-cache",
                "--",
                "app.ts",
            ),
            id="npm-package-manager-delimiter",
        ),
        pytest.param(
            ("pnpm", "exec", "eslint", "--", "app.ts"),
            (
                "pnpm",
                "exec",
                "eslint",
                "--format",
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
                "--no-warn-ignored",
                "--no-cache",
                "--",
                "app.ts",
            ),
            id="pnpm-local-exec",
        ),
    ],
)
def test_eslint_json_flags_follow_the_executable_not_the_package_manager_delimiter(
    argv: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert external_module._eslint_json_argv(argv) == expected  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert external_module._argv_file_count(argv) == 1  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]


def test_eslint_fatal_message_is_an_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "fatal": True,
                        "severity": 2,
                        "message": "parser could not load",
                        "line": 1,
                        "column": 1,
                    }
                ],
            }
        ]
    )

    def fatal(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=fatal)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues
    assert not reports[0].diagnostics


def test_missing_local_eslint_fails_before_package_manager_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("the package manager ran without a local ESLint installation")

    monkeypatch.setattr(external_module, "run_process", forbidden)

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "missing-dependency"
    assert "node_modules/.bin/eslint is missing" in reports[0].issues[0].message
    assert "code-standards setup" in reports[0].issues[0].message


def test_hoisted_eslint_above_analysis_root_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "app"
    root.mkdir(parents=True)
    source = root / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (root / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    binary = tmp_path / "node_modules" / ".bin" / "eslint"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    called: list[tuple[str, ...]] = []

    def successful(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        called.append(tuple(argv))
        return ProcessOutput(0, "[]", "")

    monkeypatch.setattr(external_module, "_run_eslint_process", successful)

    reports = analyze_external([str(source)], root=root, trust=TrustMode.TRUSTED)

    assert called
    assert called[0][0] == str(binary)
    assert called[0][1:5] == (
        "--format",
        str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        "--no-warn-ignored",
        "--no-cache",
    )
    assert reports[0].completion is Completion.COMPLETE


def test_eslint_empty_output_preserves_package_manager_stderr(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def missing(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, "", "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command 'eslint' not found")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=missing)

    assert len(reports) == 1
    issue = reports[0].issues[0]
    assert issue.kind == "tool-failure"
    assert issue.exit_code == 1
    assert issue.message == "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command 'eslint' not found"
    assert "JSONDecodeError" not in issue.message


def test_eslint_malformed_output_preserves_stderr_without_json_exception_name(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def broken(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, "not-json", "eslint could not load its local configuration")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=broken)

    issue = reports[0].issues[0]
    assert issue.kind == "protocol-mismatch"
    assert issue.message == "eslint could not load its local configuration"
    assert "JSONDecodeError" not in issue.message


def test_basedpyright_utf16_range_preserves_astral_character(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = '😀'\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "warning",
                    "message": "example",
                    "rule": "reportExample",
                    "range": {
                        "start": {"line": 0, "character": 9},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.severity is Severity.WARNING
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == 9
    assert finding.location.region.end.byte_offset == 13


def test_basedpyright_preserves_project_diagnostic_without_range(tmp_path: Path) -> None:
    source = tmp_path / "theme.py"
    source.write_text("from . import ui\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "error",
                    "message": "Cycle detected in import chain",
                    "rule": "reportImportCycles",
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.code == "reportImportCycles"
    assert finding.location.path == "theme.py"
    assert finding.location.position is None
    assert finding.location.region is None


def test_basedpyright_accepts_range_ending_at_trailing_newline_eof(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "error",
                    "message": "example",
                    "rule": "reportExample",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 1, "character": 0},
                    },
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.location.region is not None
    assert finding.location.region.end.byte_offset == len("value = 1\n")


def test_eslint_without_end_location_keeps_a_truthful_point(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": "prefer-const",
                        "severity": 2,
                        "message": "use const",
                        "line": 1,
                        "column": 1,
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.location.position is not None
    assert finding.location.region is None
    assert finding.severity is Severity.ERROR


def test_eslint_line_zero_keeps_a_truthful_path_level_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": "configuration-rule",
                        "severity": 2,
                        "message": "project-level diagnostic",
                        "line": 0,
                        "column": 1,
                        "endLine": 0,
                        "endColumn": 1,
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.location.path == "example.ts"
    assert finding.location.position is None
    assert finding.location.region is None


def test_eslint_ignored_file_warning_without_position_is_path_level(tmp_path: Path) -> None:
    source = tmp_path / "next-env.d.ts"
    source.write_text("// generated\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": None,
                        "fatal": False,
                        "severity": 1,
                        "message": "File ignored because of a matching ignore pattern.",
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.code == "eslint/file"
    assert finding.location.path == "next-env.d.ts"
    assert finding.location.position is None


def test_safe_mode_never_executes_repository_eslint_config(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("throw new Error('must not execute');\n", encoding="utf-8")
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("safe mode executed repository code")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=forbidden)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "trust-required"


def test_string_safe_mode_never_executes_repository_eslint_config(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("throw new Error('must not execute');\n", encoding="utf-8")
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("string safe mode executed repository code")

    reports = analyze_external([str(source)], root=tmp_path, trust="safe", runner=forbidden)

    assert reports[0].issues[0].kind == "trust-required"


def test_signal_terminated_tool_is_an_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def terminated(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(-9, "[]", "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=terminated)

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(report.issues[0].exit_code == -9 for report in reports)


def test_finding_exit_without_diagnostics_fails_the_external_protocol(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def empty_finding_exit(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        payload = '{"generalDiagnostics":[]}' if argv[0] == "basedpyright" else "[]"
        return ProcessOutput(1, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=empty_finding_exit)

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(report.issues[0].kind == "protocol-mismatch" for report in reports)


def test_basedpyright_parser_rejects_unknown_severity(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "fatal",
                    "message": "bad severity",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="severity"):
        parse_basedpyright(payload, root=tmp_path)


@pytest.mark.parametrize(("severity", "message"), [(99, "bad severity"), (True, "bad")], ids=("unknown", "boolean"))
def test_eslint_parser_rejects_invalid_severity(tmp_path: Path, severity: int | bool, message: str) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [{"severity": severity, "message": message, "line": 1, "column": 1}],
            }
        ]
    )

    with pytest.raises(ValueError, match="severity"):
        parse_eslint(payload, root=tmp_path)


def test_external_process_output_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(external_module, "_MAX_STDOUT_BYTES", 128)
    monkeypatch.setattr(external_module, "_MAX_STDERR_BYTES", 64)

    with pytest.raises(external_module.OutputLimitError, match="output exceeded"):
        external_module.run_process(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 10000)"),
            cwd=tmp_path,
        )


def test_malformed_nested_json_becomes_a_bounded_tool_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def nested(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(0, "[" * 100_000, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=nested)

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(len(report.issues[0].message) <= 1024 for report in reports)


def test_external_failure_redacts_secrets_and_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def failed(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(
            2,
            "",
            f"token=SUPERSECRET {cwd}/src/config /Users/alice/private/config https://docs.example.com/remediation",
        )

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=failed)
    messages = "\n".join(issue.message for report in reports for issue in report.issues)

    assert "SUPERSECRET" not in messages
    assert "/Users/alice" not in messages
    assert "<redacted>" in messages
    assert "./src/config" in messages
    assert "https://docs.example.com/remediation" in messages


def test_eslint_rejects_boolean_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [{"severity": 2, "message": "bad", "line": True, "column": True}],
            }
        ]
    )

    with pytest.raises(TypeError, match="invalid boolean coordinates"):
        parse_eslint(payload, root=tmp_path)


def test_python_external_tools_use_structured_output_without_uv(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        seen.append(tuple(argv))
        if argv[0] == "ruff":
            return ProcessOutput(0, "[]", "")
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert [report.name for report in reports] == ["ruff", "basedpyright"]
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert all(argv[0] != "uv" for argv in seen)


def test_python_external_tools_run_once_per_nearest_project(tmp_path: Path) -> None:
    first = tmp_path / "services" / "first"
    second = tmp_path / "services" / "second"
    for project in (first, second):
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0'\n", encoding="utf-8")
        (project / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    sources = (first / "app.py", second / "app.py")
    for source in sources:
        source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, Path, tuple[str, ...]]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((argv[0], cwd, tuple(argv)))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external(
        [str(source) for source in sources],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
    )

    assert [(name, cwd) for name, cwd, _argv in seen] == [
        ("ruff", tmp_path),
        ("basedpyright", first),
        ("basedpyright", second),
    ]
    assert [report.file_count for report in reports] == [2, 1, 1]
    assert [report.invocation_id for report in reports] == [
        "ruff",
        "basedpyright:services/first",
        "basedpyright:services/second",
    ]


def test_basedpyright_uses_the_project_environment_for_import_resolution(tmp_path: Path) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    source = project / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        seen.append(tuple(argv))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1][0] == str(analyzer)


def test_basedpyright_prefers_a_parent_environment_over_a_nested_package_manifest(tmp_path: Path) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\n", encoding="utf-8")
    package = project / "service"
    package.mkdir()
    (package / "pyproject.toml").write_text("[project]\nname='service'\nversion='0'\n", encoding="utf-8")
    source = package / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((tuple(argv), cwd))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1] == ((str(analyzer), "--outputjson"), project)


def test_basedpyright_runs_in_project_mode_and_filters_unselected_diagnostics(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyrightconfig.json").write_text('{"include":["."]}\n', encoding="utf-8")
    selected = project / "selected.py"
    unselected = project / "unselected.py"
    selected.write_text("value = 1\n", encoding="utf-8")
    unselected.write_text("value = 2\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        seen.append(tuple(argv))
        if argv[0] == "ruff":
            return ProcessOutput(0, "[]", "")
        diagnostics = [
            {
                "file": str(path),
                "severity": "error",
                "message": "fixture error",
                "rule": "reportGeneralTypeIssues",
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
            }
            for path in (selected, unselected)
        ]
        return ProcessOutput(1, json.dumps({"generalDiagnostics": diagnostics}), "")

    reports = analyze_external([str(selected)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    basedpyright = next(report for report in reports if report.name == "basedpyright")
    assert seen[1] == ("basedpyright", "--outputjson")
    assert basedpyright.completion is Completion.COMPLETE
    assert [diagnostic.location.path for diagnostic in basedpyright.diagnostics] == ["python/selected.py"]


def test_python_tools_use_the_adopted_config_for_files_outside_its_directory(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\n[tool.ruff]\nextend='.ruff-strict.toml'\n"
        "[tool.pyright]\nextends='.pyright-strict.json'\n",
        encoding="utf-8",
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = scripts / "release.py"
    source.write_text("value = 1\n", encoding="utf-8")
    adopted = manifest.Manifest(
        "5.6.8",
        ("ruff", "pyright", "markdownlint", "taplo", "yamllint"),
        "python",
        ".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    seen: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((tuple(argv), cwd))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen == [
        (
            (
                "ruff",
                "check",
                "--output-format",
                "json",
                "--config",
                str(project / "pyproject.toml"),
                "--",
                str(source),
            ),
            project,
        ),
        (("basedpyright", "--outputjson"), project),
    ]


def test_external_analyzer_cannot_leak_a_path_outside_repository(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    outside = tmp_path.parent / "private.py"

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        if argv[0] == "ruff":
            return ProcessOutput(
                1,
                json.dumps(
                    [
                        {
                            "filename": str(outside),
                            "location": {"row": 1, "column": 1},
                            "end_location": {"row": 1, "column": 2},
                            "code": "E001",
                            "message": "outside",
                        }
                    ]
                ),
                "",
            )
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)
    ruff = next(report for report in reports if report.name == "ruff")

    assert ruff.completion is Completion.FAILED
    assert ruff.issues[0].message == "ValueError: analyzer reported a path outside the repository root"
    assert str(tmp_path.parent) not in ruff.issues[0].message
