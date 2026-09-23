from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest, as_table, load as load_manifest
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
from sarj_standards.libs.diagnostics.serialize import to_github, to_sarif, to_text
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from pathlib import Path


def _manifest(
    path: str | None = None,
    *,
    verify_paths: tuple[str, ...] = (".",),
) -> Manifest:
    return Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        verify_paths=verify_paths,
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
    selected.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    other = tmp_path / "other.py"
    other.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    policy = api.Standards(tmp_path).analyze([str(selected), str(other)])
    raw_again = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert [item.location.path for item in policy.diagnostics if item.code == "SARJ012"] == ["other.py"]
    assert [item.code for item in raw_again.diagnostics] == ["SARJ012"]
    assert sum(tool.baselined_count for tool in policy.tools) == 1
    assert sum(tool.baselined_count for tool in raw_again.tools) == 0
    assert any(tool.get("baselinedDiagnosticCount") == 1 for tool in policy.as_dict()["tools"])
    assert "1 existing finding(s) accepted by central diagnostic baseline" in to_text(policy)
    assert "1 existing finding(s) accepted by central diagnostic baseline" in to_github(policy)
    assert "baseline-notice" in to_sarif(policy)


def test_mocked_terraform_test_can_be_ratcheted_without_hiding_new_files(tmp_path: Path) -> None:
    test_source = """override_resource {
  target = aws_s3_bucket.main
  values = { arn = "fixture-arn" }
}
run "routing" {
  assert {
    condition = aws_s3_bucket.main.arn == "fixture-arn"
    error_message = "ARN mismatch"
  }
}
"""
    source = tmp_path / "routing.tftest.hcl"
    source.write_text(test_source, encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    new_source = tmp_path / "new-routing.tftest.hcl"
    new_source.write_text(test_source, encoding="utf-8")
    policy = api.Standards(tmp_path).analyze([str(source), str(new_source)])

    assert [item.location.path for item in policy.diagnostics] == ["new-routing.tftest.hcl"]


def test_missing_diagnostic_baseline_is_an_execution_failure(tmp_path: Path) -> None:
    (tmp_path / MANIFEST_NAME).write_text(_manifest("missing.json").render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze()

    assert report.exit_code == 2
    assert report.issues[0].kind == "baseline-failure"


def test_diagnostic_baseline_exposes_fingerprint_count_growth(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    raw = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(_policy_baseline(raw.diagnostics), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")
    source.write_text(
        "logger.info('request', token=token)\nlogger.info('request', password=password)\n",
        encoding="utf-8",
    )

    policy = api.Standards(tmp_path).analyze([str(source)])

    assert [item.code for item in policy.diagnostics] == ["SARJ012"]


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


def test_scoped_merge_preserves_existing_tab_indentation(tmp_path: Path) -> None:
    old = Diagnostic("OLD", "old", Severity.ERROR, "ruff", Location("old.py"), rule_id="OLD", fingerprint="a" * 64)
    replacement = Diagnostic(
        "OLD", "replacement", Severity.ERROR, "ruff", Location("next.py"), rule_id="OLD", fingerprint="b" * 64
    )
    path = tmp_path / "baseline.json"
    path.write_text(baseline.render((old,)).replace("  ", "\t"), encoding="utf-8")

    merged = baseline.merge_scoped(
        path,
        (replacement,),
        selectors=("ruff:OLD",),
        bundle_version="9.0.0",
        consumer_base_sha="d" * 40,
        catalog_digest="e" * 64,
    )

    assert '\n\t"schemaVersion"' in merged
    assert '\n  "schemaVersion"' not in merged
    assert json.loads(merged)["diagnostics"][0]["fingerprint"] == "b" * 64


def test_scoped_merge_with_paths_preserves_same_rule_outside_selected_file(tmp_path: Path) -> None:
    old_selected = Diagnostic(
        "S607", "old", Severity.ERROR, "ruff", Location("audio.py"), rule_id="S607", fingerprint="a" * 64
    )
    old_other = replace(old_selected, location=Location("other.py"), fingerprint="b" * 64)
    replacement = replace(old_selected, message="new", fingerprint="c" * 64)
    path = tmp_path / "baseline.json"
    path.write_text(baseline.render((old_selected, old_other)), encoding="utf-8")

    merged = baseline.merge_scoped(
        path,
        (replacement, old_other),
        selectors=("ruff:S607",),
        paths=frozenset({"audio.py"}),
        bundle_version="9.0.0",
        consumer_base_sha="d" * 40,
        catalog_digest="e" * 64,
    )

    assert merged.count('"fingerprint":') == 2
    assert f'"fingerprint": "{"a" * 64}"' not in merged
    assert f'"fingerprint": "{"b" * 64}"' in merged
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


def test_react_doctor_findings_are_baselineable_by_fingerprint() -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )

    rendered: dict[str, object] = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
        baseline.render((finding,))
    )
    assert rendered["diagnostics"] == [
        {
            "count": 1,
            "fingerprint": "a" * 64,
            "path": "app.tsx",
            "ruleId": "react-doctor/no-array-index-as-key",
            "source": "react-doctor",
        }
    ]


def test_existing_baseline_fingerprint_hides_only_matching_react_doctor_debt(tmp_path: Path) -> None:
    finding = Diagnostic(
        "react-doctor/no-array-index-as-key",
        "Do not use an array index as a key.",
        Severity.WARNING,
        "react-doctor",
        Location("app.tsx"),
        rule_id="react-doctor/no-array-index-as-key",
        fingerprint="a" * 64,
    )
    new_finding = replace(finding, fingerprint="b" * 64)
    report = report_from_tools(
        tmp_path,
        (ToolReport("react-doctor", Completion.COMPLETE, (finding, new_finding)),),
    )

    visible = api._without_baselined_diagnostics(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        report, {"a" * 64: 1}
    )

    assert visible.diagnostics == (new_finding,)
    assert visible.tools[0].baselined_count == 1


def test_baseline_init_records_todays_findings_for_every_engine(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text(
        'resource "google_storage_bucket" "a" {\n  count = var.environment == "prod" ? 1 : 0\n}\n',
        encoding="utf-8",
    )

    assert cli_main(["--root", str(tmp_path), "baseline", "init"]) == 0

    raw = api.Standards(tmp_path).analyze(external=True, mode=api.AnalysisMode.RAW)
    recorded = baseline.load(tmp_path / "diagnostic-baseline.json")

    # One command has to cover every engine, or a consumer needs one baseline per tool.
    assert {"SARJ012", "SARJ204"} <= {item.code for item in raw.diagnostics}
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


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("eslint:@sarj/prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("eslint:prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("sarj-iac-lint:no-restated-comment", "iac:no-restated-comment"),
        ("iac:no-restated-comment", "iac:no-restated-comment"),
        ("sarj-python-lint:no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("python:no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("sarj-sql-lint:no-create-trigger", "sql:no-create-trigger"),
        ("sql:no-create-trigger", "sql:no-create-trigger"),
        ("sarj-text-lint:hidden-markdown-heading", "text:hidden-markdown-heading"),
        ("text:hidden-markdown-heading", "text:hidden-markdown-heading"),
    ],
)
def test_scoped_baseline_update_normalizes_native_sarj_rule_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
    expected: str,
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
    captured: list[tuple[object, object, object]] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths
        captured.append(
            (
                kwargs.get("rules"),
                kwargs.get("include_react_doctor"),
                kwargs.get("pass_on_unpruned_eslint_suppressions"),
            )
        )
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

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
                selector,
            ]
        )
        == 0
    )
    assert captured == [([expected], False, True)]


def test_scoped_baseline_update_runs_only_shellcheck_for_native_selector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    source = tmp_path / "release.sh"
    source.write_text("echo $name\n", encoding="utf-8")
    finding = Diagnostic(
        "SC2086",
        "quote expansion",
        Severity.WARNING,
        "shellcheck",
        Location("release.sh"),
        rule_id="SC2086",
        fingerprint="e" * 64,
    )
    calls: list[object] = []

    def analyze_shellcheck(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        calls.append((files, kwargs.get("capabilities"), kwargs.get("include_react_doctor")))
        return (ToolReport("shellcheck", Completion.COMPLETE, (finding,)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_shellcheck
    )

    status = cli_main(
        [
            "--root",
            str(tmp_path),
            "baseline",
            "update",
            "--output",
            str(baseline_path),
            "--rule",
            "shellcheck:SC2086",
            str(source),
        ]
    )

    assert status == 0
    assert calls == [([str(source)], frozenset({"shellcheck"}), False)]
    rendered: object = json.loads(baseline_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    diagnostics = as_table(rendered).get("diagnostics")
    assert isinstance(diagnostics, list)
    assert diagnostics == [
        {
            "fingerprint": "e" * 64,
            "source": "shellcheck",
            "ruleId": "SC2086",
            "path": "release.sh",
            "count": 1,
        }
    ]


def test_scoped_baseline_update_keeps_retired_iac_alias_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    (tmp_path / "main.tf").write_text("terraform {}\n", encoding="utf-8")

    status = cli_main(
        [
            "--root",
            str(tmp_path),
            "baseline",
            "update",
            "--output",
            str(baseline_path),
            "--rule",
            "iac:no-terraform-test-file",
        ]
    )

    assert status == 2
    assert "unknown or invalid rule selector: iac:no-terraform-test-file" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("source", "rule_id", "selector"),
    [
        ("eslint", "@sarj/prefer-ecmascript-private-members", "eslint:prefer-ecmascript-private-members"),
        ("sarj-iac-lint", "no-restated-comment", "iac:no-restated-comment"),
        ("sarj-python-lint", "no-unnecessary-docstring", "python:no-unnecessary-docstring"),
        ("sarj-sql-lint", "no-create-trigger", "sql:no-create-trigger"),
        ("sarj-text-lint", "hidden-markdown-heading", "text:hidden-markdown-heading"),
    ],
)
def test_scoped_baseline_update_replaces_native_debt_for_canonical_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    rule_id: str,
    selector: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        source,
        Location("old.txt"),
        rule_id=rule_id,
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        source,
        Location("new.txt"),
        rule_id=rule_id,
        fingerprint="b" * 64,
    )

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths, kwargs
        return report_from_tools(tmp_path, (ToolReport(source, Completion.COMPLETE, (replacement,)),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

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
                selector,
            ]
        )
        == 0
    )
    updated = baseline.load(baseline_path)
    assert "a" * 64 not in updated
    assert updated == {"b" * 64: 1}


def test_scoped_baseline_update_replaces_debt_recorded_under_a_catalogued_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        "sarj-iac-lint",
        Location("old.tf"),
        rule_id="no-terraform-test-file",
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        "sarj-iac-lint",
        Location("new.tf"),
        rule_id="no-mocked-terraform-test-oracle",
        fingerprint="b" * 64,
    )

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths, kwargs
        return report_from_tools(tmp_path, (ToolReport("sarj-iac-lint", Completion.COMPLETE, (replacement,)),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

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
                "iac:no-mocked-terraform-test-oracle",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1}


def test_scoped_baseline_update_replaces_plugin_qualified_eslint_alias_debt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        "OLD",
        "old",
        Severity.ERROR,
        "eslint",
        Location("old.ts"),
        rule_id="@sarj/zod-naming-convention",
        fingerprint="a" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old,),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = Diagnostic(
        "NEW",
        "replacement",
        Severity.ERROR,
        "eslint",
        Location("new.ts"),
        rule_id="@sarj/require-pascal-case-zod-schema-name",
        fingerprint="b" * 64,
    )

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths, kwargs
        return report_from_tools(
            tmp_path,
            (ToolReport("eslint", Completion.COMPLETE, (replacement,)),),
        )

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

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
                "eslint:require-pascal-case-zod-schema-name",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1}


@pytest.mark.parametrize(
    ("selector", "source", "rule_id"),
    [
        ("react-doctor:react-doctor/no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("react-doctor:no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("eslint:react-doctor/no-array-index-as-key", "react-doctor", "react-doctor/no-array-index-as-key"),
        ("eslint:react-doctor/no-array-index-as-key", "react-doctor", "no-array-index-as-key"),
        (
            "react-doctor:react-hooks-js/no-useless-custom-hooks",
            "react-doctor",
            "react-hooks-js/no-useless-custom-hooks",
        ),
        ("eslint:react-hooks-js/no-useless-custom-hooks", "react-doctor", "react-hooks-js/no-useless-custom-hooks"),
        ("eslint:react-hooks-js/no-useless-custom-hooks", "react-hooks-js", "no-useless-custom-hooks"),
        ("react-hooks-js:no-useless-custom-hooks", "react-doctor", "react-hooks-js/no-useless-custom-hooks"),
        ("react-hooks-js:no-useless-custom-hooks", "react-hooks-js", "no-useless-custom-hooks"),
    ],
)
def test_scoped_baseline_update_captures_react_doctor_and_preserves_unrelated_debt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
    source: str,
    rule_id: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old = Diagnostic(
        rule_id,
        "old selected debt",
        Severity.ERROR,
        source,
        Location("old.tsx"),
        rule_id=rule_id,
        fingerprint="a" * 64,
    )
    unrelated = Diagnostic(
        "react-doctor/button-has-type",
        "unrelated debt",
        Severity.ERROR,
        source,
        Location("button.tsx"),
        rule_id="react-doctor/button-has-type",
        fingerprint="c" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old, unrelated),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = replace(old, message="replacement debt", location=Location("new.tsx"), fingerprint="b" * 64)
    calls: list[tuple[object, object, object, object]] = []

    def analyze_react_doctor(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        calls.append(
            (
                files,
                kwargs.get("capabilities"),
                (kwargs.get("include_react_doctor"), kwargs.get("force_react_doctor")),
                kwargs.get("react_doctor_full_scan"),
            )
        )
        return (ToolReport("react-doctor", Completion.COMPLETE, (replacement, unrelated)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_react_doctor
    )

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
                selector,
            ]
        )
        == 0
    )
    assert calls == [
        ([str(tmp_path)], frozenset({"react-doctor"}), (True, True), True),
    ]
    assert baseline.load(baseline_path) == {"b" * 64: 1, "c" * 64: 1}


def test_scoped_react_doctor_wildcard_replaces_every_react_doctor_rule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old_react = Diagnostic(
        "react-doctor/old",
        "old React debt",
        Severity.ERROR,
        "react-doctor",
        Location("old.tsx"),
        rule_id="react-doctor/old",
        fingerprint="a" * 64,
    )
    unrelated = Diagnostic(
        "F401",
        "unrelated Python debt",
        Severity.ERROR,
        "ruff",
        Location("old.py"),
        rule_id="F401",
        fingerprint="c" * 64,
    )
    baseline_path.write_text(
        baseline.render(
            (old_react, unrelated),
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        ),
        encoding="utf-8",
    )
    replacement = replace(
        old_react,
        code="react-doctor/new",
        rule_id="react-doctor/new",
        message="current React debt",
        fingerprint="b" * 64,
    )

    def analyze_react_doctor(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        assert files == [str(tmp_path)]
        assert kwargs.get("react_doctor_full_scan") is True
        return (ToolReport("react-doctor", Completion.COMPLETE, (replacement,)),)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_react_doctor
    )

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
                "react-doctor:*",
            ]
        )
        == 0
    )
    assert baseline.load(baseline_path) == {"b" * 64: 1, "c" * 64: 1}


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
    adopted = _manifest(baseline_path.name, verify_paths=("src", "test"))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    captured: list[object] = []

    def analyze_eslint(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        _ = kwargs
        captured.append(files)
        return ()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_eslint
    )

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


def test_scoped_baseline_update_includes_tracked_terraform_tests_outside_verification_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "iac" / "bootstrap.tftest.hcl"
    source.parent.mkdir()
    source.write_text('mock_provider "aws" {}\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "iac/bootstrap.tftest.hcl"), cwd=tmp_path, check=True)
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
    adopted = _manifest(baseline_path.name, verify_paths=("src",))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    finding = Diagnostic(
        "SARJ206",
        "Terraform mock provider oracle",
        Severity.WARNING,
        "sarj-iac-lint",
        Location("iac/bootstrap.tftest.hcl"),
        rule_id="no-mocked-terraform-test-oracle",
        fingerprint="d" * 64,
    )
    captured: list[object] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, kwargs
        captured.append(paths)
        diagnostics = (finding,) if isinstance(paths, list) and str(source) in paths else ()
        return report_from_tools(tmp_path, (ToolReport("sarj-iac-lint", Completion.COMPLETE, diagnostics),))

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

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
                "sarj-iac-lint:no-mocked-terraform-test-oracle",
            ]
        )
        == 0
    )
    assert captured == [[str(tmp_path / "src"), str(source)]]
    assert baseline.load(baseline_path) == {"d" * 64: 1}


@pytest.mark.parametrize(
    "selector",
    ["eslint:@typescript-eslint/naming-convention", "eslint:unicorn/prefer-iterator-helpers"],
)
def test_scoped_baseline_update_runs_only_eslint_for_upstream_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
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
    adopted = replace(_manifest(baseline_path.name), excluded_paths=("generated/**",))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    captured: list[tuple[object, object]] = []

    def analyze(self: api.Standards, paths: object = None, **kwargs: object) -> AnalysisReport:
        _ = self, paths
        captured.append((paths, kwargs.get("rules")))
        return report_from_tools(tmp_path, ())

    monkeypatch.setattr(api.Standards, "analyze", analyze)  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing

    external_calls: list[object] = []

    def analyze_eslint(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        policy = kwargs.get("policy")
        assert isinstance(policy, Policy)
        external_calls.append(
            (
                files,
                kwargs.get("capabilities"),
                kwargs.get("include_react_doctor"),
                kwargs.get("pass_on_unpruned_eslint_suppressions"),
                policy.allows_path(tmp_path / "generated" / "client.ts"),
            )
        )
        return ()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts baseline analyzer routing
        external, "analyze_external", analyze_eslint
    )

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
                selector,
            ]
        )
        == 0
    )
    assert captured == []
    assert external_calls == [([str(tmp_path)], frozenset({"eslint"}), False, True, False)]


@pytest.mark.parametrize("selector", ["ruff:S404", "ruff:S603", "ruff:S607"])
def test_scoped_baseline_update_runs_only_ruff_and_preserves_other_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
) -> None:
    rule_id = selector.partition(":")[2]
    selected = tmp_path / "audio.py"
    selected.write_text("print('test')\n", encoding="utf-8")
    baseline_path = tmp_path / "diagnostic-baseline.json"
    old_selected = Diagnostic(
        rule_id, "old", Severity.ERROR, "ruff", Location("audio.py"), rule_id=rule_id, fingerprint="a" * 64
    )
    old_other = replace(old_selected, location=Location("other.py"), fingerprint="b" * 64)
    unrelated = replace(old_selected, code="F401", rule_id="F401", fingerprint="d" * 64)
    baseline_path.write_text(_policy_baseline((old_selected, old_other, unrelated)), encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")
    replacement = replace(old_selected, message="current", fingerprint="c" * 64)

    def unexpected_native(_self: api.Standards, _paths: object = None, **_kwargs: object) -> AnalysisReport:
        pytest.fail("upstream Ruff selector must not run all analyzers")

    monkeypatch.setattr(api.Standards, "analyze", unexpected_native)  # sarj-noqa: SARJ445 -- verifies upstream routing
    captured: list[object] = []

    def analyze_ruff(files: object, **kwargs: object) -> tuple[ToolReport, ...]:
        captured.append((files, kwargs.get("capabilities"), kwargs.get("force_explicit_ruff_files")))
        return (ToolReport("ruff", Completion.COMPLETE, (replacement,), file_count=1),)

    monkeypatch.setattr(external, "analyze_external", analyze_ruff)  # sarj-noqa: SARJ445 -- intercepts analyzer routing

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
                selector,
                "audio.py",
            ]
        )
        == 0
    )
    assert captured == [([str(selected)], frozenset({"ruff"}), True)]
    assert baseline.load(baseline_path) == {"b" * 64: 1, "c" * 64: 1, "d" * 64: 1}


def test_upstream_ruff_baseline_update_requires_explicit_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    original = _policy_baseline(())
    baseline_path.write_text(original, encoding="utf-8")

    def unexpected_external(_files: object, **_kwargs: object) -> tuple[ToolReport, ...]:
        pytest.fail("upstream Ruff must not run before scope validation")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- validates fail-closed scope
        external, "analyze_external", unexpected_external
    )
    assert (
        cli_main(["--root", str(tmp_path), "baseline", "update", "--output", str(baseline_path), "--rule", "ruff:S607"])
        == 2
    )
    assert "require explicit Python files" in capsys.readouterr().err
    assert baseline_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("selected_path", ["excluded.py", "unrouted.txt", "."])
def test_upstream_ruff_baseline_rejects_excluded_or_unroutable_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selected_path: str,
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    original = _policy_baseline(
        (
            Diagnostic(
                "S607", "old", Severity.ERROR, "ruff", Location("excluded.py"), rule_id="S607", fingerprint="a" * 64
            ),
        )
    )
    baseline_path.write_text(original, encoding="utf-8")
    (tmp_path / "excluded.py").write_text("print('excluded')\n", encoding="utf-8")
    (tmp_path / "unrouted.txt").write_text("not Python\n", encoding="utf-8")
    adopted = replace(_manifest(baseline_path.name), excluded_paths=("excluded.py",))
    (tmp_path / MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    def unexpected_external(_files: object, **_kwargs: object) -> tuple[ToolReport, ...]:
        pytest.fail("invalid Ruff path must be rejected before analysis")

    monkeypatch.setattr(external, "analyze_external", unexpected_external)  # sarj-noqa: SARJ445 -- validates scope
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
                "ruff:S607",
                selected_path,
            ]
        )
        == 2
    )
    assert baseline_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "tools",
    [
        pytest.param((), id="no-report"),
        pytest.param((ToolReport("ruff", Completion.COMPLETE, file_count=0),), id="zero-files"),
    ],
)
def test_upstream_ruff_baseline_rejects_incomplete_tool_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tools: tuple[ToolReport, ...],
) -> None:
    baseline_path = tmp_path / "diagnostic-baseline.json"
    original = _policy_baseline(
        (Diagnostic("S607", "old", Severity.ERROR, "ruff", Location("audio.py"), rule_id="S607", fingerprint="a" * 64),)
    )
    baseline_path.write_text(original, encoding="utf-8")
    (tmp_path / "audio.py").write_text("print('audio')\n", encoding="utf-8")

    def analyze_incompletely(_files: object, **_kwargs: object) -> tuple[ToolReport, ...]:
        return tools

    monkeypatch.setattr(external, "analyze_external", analyze_incompletely)  # sarj-noqa: SARJ445 -- tests coverage
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
                "ruff:S607",
                "audio.py",
            ]
        )
        == 2
    )
    assert "coverage-missing" in capsys.readouterr().err
    assert baseline_path.read_text(encoding="utf-8") == original


def test_upstream_ruff_baseline_checks_explicit_file_even_with_force_exclude(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nforce-exclude = true\nextend-exclude = ["audio.py"]\n[tool.ruff.lint]\npreview = true\nselect = ["S"]\n',
        encoding="utf-8",
    )
    (tmp_path / "audio.py").write_text("import subprocess\n", encoding="utf-8")
    baseline_path = tmp_path / "diagnostic-baseline.json"
    baseline_path.write_text(
        _policy_baseline(
            (
                Diagnostic(
                    "S404", "old", Severity.ERROR, "ruff", Location("audio.py"), rule_id="S404", fingerprint="a" * 64
                ),
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline_path.name).render(), encoding="utf-8")

    excluded = subprocess.run(
        ("ruff", "check", "--output-format", "json", "--config", str(tmp_path / "pyproject.toml"), "--", "audio.py"),
        cwd=tmp_path,
        check=False,
        text=True,
        capture_output=True,
    )
    assert excluded.returncode == 0
    assert json.loads(excluded.stdout) == []

    assert cli_main(["--root", str(tmp_path), "baseline", "update", "--rule", "ruff:S404", "audio.py"]) == 0
    recorded = baseline.load(baseline_path)
    assert len(recorded) == 1
    assert "a" * 64 not in recorded
    rendered = baseline_path.read_text(encoding="utf-8")
    assert '"source": "ruff"' in rendered
    assert '"ruleId": "S404"' in rendered
    assert '"path": "audio.py"' in rendered


def test_baseline_rejects_a_path_outside_the_repository(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")

    assert cli_main(["--root", str(tmp_path), "baseline", "init", "/etc/hosts"]) == 2
