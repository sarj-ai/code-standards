from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.adoption.manifest import load as load_manifest
from sarj_standards.libs.diagnostics import (
    AnalysisReport,
    Completion,
    Diagnostic,
    Location,
    Position,
    Severity,
    ToolReport,
    baseline,
)
from sarj_standards.libs.linting import external
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


def _policy_baseline(diagnostics: tuple[Diagnostic, ...]) -> str:
    return baseline.render(
        diagnostics,
        bundle_version=api.__version__,
        consumer_base_sha="0" * 40,
        catalog_digest=baseline.bundled_catalog_digest(),
    )


def test_policy_analysis_hides_only_exact_baselined_diagnostics(tmp_path: Path) -> None:
    selected = tmp_path / "selected.py"
    selected.write_text("import logging\n", encoding="utf-8")
    other = tmp_path / "other.py"
    other.write_text("import logging\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(selected), str(other)])
    raw_again = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert [item.location.path for item in policy.diagnostics if item.code == "SARJ052"] == ["other.py"]
    assert [item.code for item in raw_again.diagnostics] == ["SARJ052"]


def test_terraform_test_ban_can_be_ratcheted_without_hiding_new_files(tmp_path: Path) -> None:
    source = tmp_path / "routing.tftest.json"
    source.write_text("{}\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    new_source = tmp_path / "new-routing.tftest.json"
    new_source.write_text("{}\n", encoding="utf-8")
    policy = api.Standards(tmp_path).analyze([str(source), str(new_source)])

    assert [item.location.path for item in policy.diagnostics] == ["new-routing.tftest.json"]


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
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
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


def test_v2_baseline_records_and_validates_provenance(tmp_path: Path) -> None:
    rendered = baseline.render(
        (),
        bundle_version="9.0.0",
        consumer_base_sha="a" * 40,
        catalog_digest="b" * 64,
    )
    path = tmp_path / "baseline.json"
    path.write_text(rendered, encoding="utf-8")

    assert baseline.load(path) == {}
    assert json.loads(rendered)["provenance"] == {
        "bundleVersion": "9.0.0",
        "consumerBaseSha": "a" * 40,
        "catalogDigest": "b" * 64,
    }


def test_policy_mode_rejects_legacy_or_stale_baseline_provenance(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(baseline.render(()), encoding="utf-8")
    with pytest.raises(ValueError, match="schemaVersion 2"):
        baseline.load(legacy, require_v2=True)

    stale = tmp_path / "stale.json"
    stale.write_text(
        baseline.render((), bundle_version="0.0.0", consumer_base_sha="0" * 40, catalog_digest="f" * 64),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bundle version"):
        baseline.load(stale, require_v2=True, expected_bundle_version=api.__version__)


def test_scoped_merge_preserves_unrelated_debt(tmp_path: Path) -> None:
    old = Diagnostic("OLD", "old", Severity.ERROR, "ruff", Location("old.py"), rule_id="OLD", fingerprint="a" * 64)
    promoted = Diagnostic("NEW", "new", Severity.ERROR, "ruff", Location("new.py"), rule_id="NEW", fingerprint="b" * 64)
    path = tmp_path / "baseline.json"
    path.write_text(baseline.render((old, promoted)), encoding="utf-8")
    replacement = Diagnostic(
        "NEW", "replacement", Severity.ERROR, "ruff", Location("next.py"), rule_id="NEW", fingerprint="c" * 64
    )

    merged = baseline.merge_scoped(
        path,
        (replacement,),
        selectors=("ruff:NEW",),
        bundle_version="9.0.0",
        consumer_base_sha="d" * 40,
        catalog_digest="e" * 64,
    )

    assert merged.count('"fingerprint":') == 2
    assert f'"fingerprint": "{"a" * 64}"' in merged
    assert f'"fingerprint": "{"c" * 64}"' in merged


def test_staged_changed_lines_cannot_consume_baseline_allowance(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Standards Test"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.email", "standards@example.com"), cwd=tmp_path, check=True)
    source = tmp_path / "app.py"
    source.write_text("old\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=tmp_path, check=True)
    source.write_text("old\nnew\n", encoding="utf-8")
    subprocess.run(("git", "add", "app.py"), cwd=tmp_path, check=True)

    scope = baseline.changed_line_scope(tmp_path, staged=True)
    old = Diagnostic("X", "old", Severity.ERROR, "ruff", Location("app.py", position=Position(0, 0, 0)))
    new = Diagnostic("X", "new", Severity.ERROR, "ruff", Location("app.py", position=Position(1, 0, 4)))

    assert not baseline.touches_changed_lines(old, scope)
    assert baseline.touches_changed_lines(new, scope)


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


def test_scoped_baseline_update_normalizes_native_sarj_eslint_rule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    captured: list[tuple[object, object]] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths
        captured.append((kwargs.get("rules"), kwargs.get("include_react_doctor")))
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "eslint:@sarj/prefer-ecmascript-private-members",
            ]
        )
        == 0
    )
    assert captured == [(["eslint:prefer-ecmascript-private-members"], False)]


def test_scoped_baseline_update_uses_manifest_verification_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    adopted = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        verify_paths=("src", "test"),
        diagnostic_baseline=baseline_path.name,
    )
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    captured: list[object] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, kwargs
        captured.append(paths)
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "eslint:unicorn/prefer-iterator-helpers",
            ]
        )
        == 0
    )
    assert captured == [[str(tmp_path / "src"), str(tmp_path / "test")]]


def test_scoped_baseline_update_runs_only_eslint_for_upstream_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        baseline.render(
            (),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    captured: list[tuple[object, object]] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths
        captured.append((paths, kwargs.get("rules")))
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)

    external_calls: list[object] = []

    def analyze_eslint(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        external_calls.append((files, kwargs.get("capabilities"), kwargs.get("include_react_doctor")))
        return ()

    monkeypatch.setattr(external, "analyze_external", analyze_eslint)

    assert (
        cli_main(
            [
                "--root",
                str(tmp_path),
                "baseline",
                "update",
                "--output",
                str(baseline_path),
                "--rule",
                "eslint:@typescript-eslint/naming-convention",
            ]
        )
        == 0
    )
    assert captured == []
    assert external_calls == [([str(tmp_path)], frozenset({"eslint"}), False)]


def test_baseline_rejects_a_path_outside_the_repository(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")

    assert cli_main(["--root", str(tmp_path), "baseline", "init", "/etc/hosts"]) == 2
