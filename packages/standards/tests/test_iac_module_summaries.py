from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest, load


if TYPE_CHECKING:
    from pathlib import Path


_RULE = "iac:no-terraform-comments"
_SOURCE = '# Voice runtime\n\nresource "example_service" "voice" {}\n'


@pytest.mark.parametrize("enabled", [False, True])
def test_module_summary_option_round_trips(tmp_path: Path, enabled: bool) -> None:
    adopted = Manifest(api.__version__, (), ".", ".", terraform_module_summaries=enabled)
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render())

    assert load(tmp_path) == adopted


@pytest.mark.parametrize("option", ['module_summaries = "true"', "module_summaries = 1", "unknown = true"])
def test_module_summary_option_rejects_malformed_configuration(tmp_path: Path, option: str) -> None:
    adopted = Manifest(api.__version__, (), ".", ".")
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render() + f"\n[iac.no-terraform-comments]\n{option}\n")

    with pytest.raises(ValueError, match="supports only boolean module_summaries"):
        load(tmp_path)


@pytest.mark.parametrize("mode", list(api.AnalysisMode))
@pytest.mark.parametrize("enabled", [False, True])
def test_analysis_uses_the_explicit_summary_policy(tmp_path: Path, mode: api.AnalysisMode, enabled: bool) -> None:
    adopted = Manifest(api.__version__, (), ".", ".", terraform_module_summaries=enabled)
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render())
    (tmp_path / "main.tf").write_text(_SOURCE)

    report = api.Standards(tmp_path).analyze(["main.tf"], mode=mode, rules=[_RULE])

    assert report.completion is api.Completion.COMPLETE
    assert [item.code for item in report.diagnostics] == (
        [] if enabled and mode is not api.AnalysisMode.RAW else ["SARJ216"]
    )
