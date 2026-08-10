from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.adoption.manifest import load as load_manifest
from sarj_standards.libs.diagnostics import baseline


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
