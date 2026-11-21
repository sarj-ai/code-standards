from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import ExclusionOverride, Manifest, load
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.rules import RuleSelection


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


@pytest.mark.parametrize("excepted", [False, True])
def test_comment_policy_exclusion_does_not_disable_the_narrower_control(tmp_path: Path, *, excepted: bool) -> None:
    (tmp_path / "main.tf").write_text('# ==== Resources ====\nresource "example_service" "app" {}\n')
    overrides = (
        (ExclusionOverride(paths=("main.tf",), rules=(_RULE,), reason="Required legal provenance."),)
        if excepted
        else ()
    )
    manifest = Manifest(api.__version__, (), ".", ".", exclusion_overrides=overrides)
    policy = Policy.from_manifest(tmp_path, manifest)

    report = analyze(
        ["main.tf"],
        root=tmp_path,
        policy=policy,
        use_guard_contracts=False,
        rule_selection=RuleSelection.from_values((_RULE, "iac:no-comment-cruft")),
    )

    assert report.completion is api.Completion.COMPLETE
    assert [item.code for item in report.diagnostics] == (["SARJ202"] if excepted else ["SARJ216"])
