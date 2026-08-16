from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.adoption.manifest import load as load_manifest
from sarj_standards.libs.diagnostics import Completion, Diagnostic, Location, Severity, ToolReport, baseline
from sarj_standards.libs.linting.analysis import report_from_tools


if TYPE_CHECKING:
    from pathlib import Path


def _manifest(path: str | None = None) -> Manifest:
    return Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        diagnostic_baseline=path,
    )


def test_policy_analysis_hides_only_exact_baselined_diagnostics(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("import logging\n", encoding="utf-8")
    other = tmp_path / "other.py"
    other.write_text("import logging\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(baseline.render(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(selected), str(other)])
    raw_again = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert [item.location.path for item in policy.diagnostics if item.code == "SARJ052"] == ["other.py"]
    assert [item.code for item in raw_again.diagnostics] == ["SARJ052"]


def test_terraform_test_ban_cannot_be_diagnostic_baselined(tmp_path: Path) -> None:
    source = tmp_path / "routing.tftest.json"
    source.write_text("{}\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(baseline.render(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(source)])

    assert [item.code for item in policy.diagnostics] == ["SARJ206"]


def test_missing_diagnostic_baseline_is_an_execution_failure(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_text(_manifest("missing.json").render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze()

    assert report.exit_code == 2
    assert report.issues[0].kind == "baseline-failure"


def test_diagnostic_baseline_exposes_fingerprint_count_growth(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("import logging\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(baseline.render(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")
    source.write_text("import logging\nimport logging\n", encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(source)])

    assert [item.code for item in policy.diagnostics] == ["SARJ052"]


def test_manifest_round_trips_diagnostic_baseline(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_text(_manifest("quality/diagnostics.json").render(), encoding="utf-8")

    adopted = load_manifest(tmp_path)

    assert adopted is not None
    assert adopted.diagnostic_baseline == "quality/diagnostics.json"


@pytest.mark.parametrize("path", ["../outside.json", "baseline.toml"])
def test_manifest_rejects_unsafe_diagnostic_baseline_paths(tmp_path: Path, path: str) -> None:
    rendered = _manifest().render() + f"\n[baseline]\ndiagnostics = {json.dumps(path)}\n"
    (tmp_path / MANIFEST_NAME).write_text(rendered, encoding="utf-8")

    with pytest.raises(ValueError, match=r"repository-relative JSON path|escapes"):
        load_manifest(tmp_path)


def test_diagnostic_baseline_rejects_duplicate_fingerprints(tmp_path: Path) -> None:
    fingerprint = "a" * 64
    entry = {"fingerprint": fingerprint, "source": "ruff", "ruleId": "E501", "path": "app.py", "count": 1}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schemaVersion": 1, "diagnostics": [entry, entry]}), encoding="utf-8")

    with pytest.raises(ValueError, match="repeats fingerprint"):
        baseline.load(path)


def test_react_doctor_findings_are_never_recorded_in_a_baseline() -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )

    assert json.loads(baseline.render((finding,))) == {"schemaVersion": 1, "diagnostics": []}


def test_existing_baseline_fingerprint_never_hides_react_doctor(tmp_path: Path) -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )
    report = report_from_tools(tmp_path, (ToolReport("react-doctor", Completion.COMPLETE, (finding,)),))

    visible = api._without_baselined_diagnostics(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        report, {"a" * 64: 1}
    )

    assert visible.diagnostics == (finding,)


def test_baseline_init_records_todays_findings_for_every_engine(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("import logging\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )

    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0

    raw = api.Standards(tmp_path).analyze(external=True, mode=api.AnalysisMode.RAW)
    recorded = baseline.load(tmp_path / "diagnostic-baseline.json")

    # One command has to cover every engine, or a consumer needs one baseline per tool.
    assert {"SARJ052", "SARJ204"} <= {item.code for item in raw.diagnostics}
    assert sum(recorded.values()) == len(raw.diagnostics)


def test_baselined_findings_stop_failing_but_a_new_one_still_does(tmp_path: Path) -> None:
    source = tmp_path / "main.tf"
    source.write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )
    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0
    (tmp_path / MANIFEST_NAME).write_text(_manifest("diagnostic-baseline.json").render(), encoding="utf-8")

    settled = api.Standards(tmp_path).analyze()
    assert [item.code for item in settled.diagnostics] == []

    source.write_text(
        source.read_text(encoding="utf-8")
        + '\nresource "google_storage_bucket" "b" {\n  count = var.environment == "dev" ? 1 : 0\n}\n',
        encoding="utf-8",
    )

    grown = api.Standards(tmp_path).analyze()
    assert "SARJ204" in [item.code for item in grown.diagnostics]


def test_baseline_init_refuses_to_overwrite_and_update_replaces(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )
    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0

    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 2
    assert cli_main(["--root", str(tmp_path), "baseline", "update"]) == 0


def test_baseline_rejects_a_path_outside_the_repository(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")

    assert cli_main(["--root", str(tmp_path), "baseline", "init", "/etc/hosts"]) == 2
