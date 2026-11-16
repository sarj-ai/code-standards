from __future__ import annotations

from dataclasses import replace
import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.__main__ import main
from sarj_standards.libs.adoption.manifest import (
    Manifest,
    TerraformOutputContract,
    adopted_version,
    load,
    terraform_output_contracts,
)
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.rules import RuleSelection


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.diagnostics import AnalysisReport

_RULE = "iac:no-unused-module-outputs"


def _git(root: Path, *arguments: str) -> None:
    executable = shutil.which("git")
    assert executable is not None
    subprocess.run([executable, "-C", str(root), *arguments], check=True, capture_output=True, timeout=10)


def _manifest() -> Manifest:
    return Manifest(version=adopted_version(), configs=(), python_dest=".", typescript_dest=".")


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    (root / "infra/child").mkdir(parents=True)
    (root / ".sarj-standards.toml").write_text(_manifest().render())
    (root / "infra/main.tf").write_text(
        'module "child" { source = "./child" }\noutput "public" { value = module.child.used }\n'
    )
    (root / "infra/child/outputs.tf").write_text(
        'output "used" { value = "used" }\noutput "external" { value = "external" }\n'
    )
    _git(root, "init", "--quiet", "--template=")
    _git(root, "add", ".")
    return root


def _report(root: Path, *, staged: bool = True, files: tuple[str, ...] = ()) -> AnalysisReport:
    return analyze(
        files, root=root, staged=staged, use_guard_contracts=False, rule_selection=RuleSelection.from_values((_RULE,))
    )


def test_staged_check_finds_unused_export_even_without_changed_iac_files(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    report = _report(root)
    assert not report.issues
    assert report.completion is Completion.COMPLETE
    assert len(report.diagnostics) == 1
    finding = report.diagnostics[0]
    assert finding.code == "SARJ223"
    assert finding.rule_id == "no-unused-module-outputs"
    assert finding.location.path == "infra/child/outputs.tf"
    assert finding.location.position is not None
    assert finding.location.position.line == 1
    assert finding.severity.value == "error"
    assert {"non-baselineable", "required-source-policy"}.issubset(finding.tags)


def test_required_project_rule_ignores_broad_rule_and_path_exclusions(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    policy = Policy.from_manifest(root, replace(_manifest(), excluded_paths=("infra/**",), excluded_rules=(_RULE,)))
    report = analyze([], root=root, staged=True, use_guard_contracts=False, policy=policy)
    assert any(item.code == "SARJ223" for item in report.diagnostics)


def test_head_and_staged_index_keep_their_unchanged_consumers_separate(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(
        root,
        "-c",
        "user.name=Lint Fixture",
        "-c",
        "user.email=lint@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    (root / "other-root").mkdir()
    (root / "other-root/main.tf").write_text(
        'module "shared" { source = "../infra/child" }\noutput "public" { value = module.shared.external }\n'
    )
    _git(root, "add", ".")
    assert not _report(root, files=("other-root/main.tf",)).diagnostics
    assert len(_report(root, staged=False).diagnostics) == 1
    (root / "other-root/main.tf").write_text("terraform {}\n")
    assert not _report(root).diagnostics
    _git(root, "add", ".")
    assert len(_report(root, files=("other-root/main.tf",)).diagnostics) == 1


def test_diagnostic_location_uses_selected_index_source(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "infra/child/outputs.tf").write_text("\n" * 20 + 'output "external" { value = false }\n')
    report = _report(root)
    assert not report.issues
    finding = report.diagnostics[0]
    assert finding.location.position is not None
    assert finding.location.position.line == 1


@pytest.mark.parametrize("indexed", [False, True], ids=["unicode", "quoted-instance"])
def test_json_unicode_and_for_each_consumer_semantics(tmp_path: Path, *, indexed: bool) -> None:
    root = _repository(tmp_path)
    (root / "infra/main.tf").unlink()
    (root / "infra/child/outputs.tf").write_text(
        'output "café" { value = true }\noutput "external" { value = false }\n'
    )
    call: dict[str, str | dict[str, bool]] = {"source": "./child"}
    if indexed:
        call["for_each"] = {"slot": True}
    value = '${module.child["slot"].café}' if indexed else "${module.child.café}"
    (root / "infra/main.tf.json").write_text(
        json.dumps({"module": {"child": call}, "output": {"public": {"value": value}}})
    )
    _git(root, "add", ".")
    report = _report(root)
    assert not report.issues
    assert len(report.diagnostics) == 1
    assert "'external'" in report.diagnostics[0].message


def test_output_safety_precondition_and_its_input_are_real_consumers(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "infra/child/outputs.tf").write_text(
        'variable "accepted" { type = bool }\noutput "used" { value = true }\noutput "external" {\n  value = false\n  precondition {\n    condition = var.accepted\n    error_message = "Approval is required."\n  }\n}\n'
    )
    (root / "infra/main.tf").write_text(
        'module "child" {\n source = "./child"\n accepted = true\n}\noutput "public" { value = module.child.used }\n'
    )
    _git(root, "add", ".")
    report = _report(root)
    assert not report.issues
    assert not report.diagnostics


@pytest.mark.parametrize(
    ("output", "evidence", "complete"),
    [("external", "contract.md", True), ("missing", "contract.md", False), ("external", "missing.md", False)],
)
def test_exact_external_contracts_require_real_output_and_tracked_evidence(
    tmp_path: Path, output: str, evidence: str, *, complete: bool
) -> None:
    root = _repository(tmp_path)
    (root / "contract.md").write_text("The existing external metadata reader contract remains uncertain.\n")
    contract = TerraformOutputContract(
        module="infra/child",
        output=output,
        reason="Preserve the uncertain external metadata interface",
        evidence=evidence,
    )
    manifest = replace(_manifest(), terraform_output_contracts=(contract,))
    (root / ".sarj-standards.toml").write_text(manifest.render())
    _git(root, "add", ".")
    report = _report(root)
    if complete:
        assert not report.issues
        assert not report.diagnostics
        adopted = load(root)
        assert adopted is not None
        assert adopted.terraform_output_contracts == (contract,)
    else:
        assert report.completion is Completion.FAILED
        assert report.issues


def test_dynamic_output_selection_preserves_uncertain_consumers(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "infra/main.tf").write_text(
        'variable "selected" {}\nmodule "child" { source = "./child" }\noutput "public" { value = module.child[var.selected] }\n'
    )
    _git(root, "add", ".")
    report = _report(root)
    assert not report.issues
    assert not report.diagnostics


def test_more_than_one_hundred_sources_are_not_truncated(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for index in range(120):
        (root / f"infra/child/export-{index}.tf").write_text(f'output "unused_{index}" {{ value = true }}\n')
    _git(root, "add", ".")
    report = _report(root)
    assert not report.issues
    assert len(report.diagnostics) == 121
    assert any(item.location.path == "infra/child/export-119.tf" for item in report.diagnostics)


@pytest.mark.parametrize("source", ['output "broken" { value = [', '{"output":'])
def test_malformed_source_fails_analysis(tmp_path: Path, source: str) -> None:
    root = _repository(tmp_path)
    name = "broken.tf.json" if source.startswith("{") else "broken.tf"
    (root / "infra/child" / name).write_text(source)
    _git(root, "add", ".")
    report = _report(root)
    assert report.completion is Completion.FAILED
    assert report.issues


@pytest.mark.parametrize(
    "record",
    [
        {"module": "infra/*", "output": "external", "reason": "reader", "evidence": "contract.md"},
        {"module": "../child", "output": "external", "reason": "reader", "evidence": "contract.md"},
        {"module": "infra/child", "output": "external", "reason": "", "evidence": "contract.md"},
        {"module": "infra/child", "output": "external", "reason": "reader"},
    ],
    ids=["wildcard-module", "parent-escape", "empty-reason", "missing-evidence"],
)
def test_broad_or_incomplete_external_contracts_are_rejected(record: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="external"):
        terraform_output_contracts({"iac": {"no-unused-module-outputs": {"external_outputs": [record]}}})


def test_unrelated_package_metadata_does_not_make_terraform_sources_incomplete(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "package.json").write_text("{invalid unrelated metadata")
    _git(root, "add", ".")
    report = _report(root)
    assert not report.issues
    assert len(report.diagnostics) == 1


def test_explicit_rule_selection_requires_an_actual_git_snapshot(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report.completion is Completion.FAILED
    assert any("complete Git" in issue.message for issue in report.issues)


def test_unborn_head_keeps_default_scope_empty_and_checks_initial_staged_exports(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    report = analyze([], root=root, use_guard_contracts=False)
    assert report.completion is Completion.COMPLETE
    assert not report.issues
    assert not report.diagnostics
    assert _report(root, staged=False).completion is Completion.FAILED
    assert any(item.code == "SARJ223" for item in _report(root).diagnostics)


def test_broken_existing_head_cannot_skip_required_source_analysis(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "symbolic-ref", "HEAD", "refs/heads/broken-fixture")
    (root / ".git/refs/heads/broken-fixture").write_text("f" * 40 + "\n")
    report = analyze([], root=root, use_guard_contracts=False)
    assert report.completion is Completion.FAILED
    assert any(issue.source == "sarj-iac-lint/module-outputs" for issue in report.issues)


def test_unreadable_git_metadata_cannot_skip_required_source_analysis(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: missing\n")
    report = analyze([], root=tmp_path, use_guard_contracts=False)
    assert report.completion is Completion.FAILED
    assert any(issue.source == "sarj-iac-lint/module-outputs" for issue in report.issues)


def test_detached_head_still_checks_complete_committed_sources(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "-c", "user.name=Lint Fixture", "-c", "user.email=lint@example.invalid", "commit", "-qm", "fixture")
    _git(root, "checkout", "--quiet", "--detach")
    report = _report(root, staged=False)
    assert not report.issues
    assert len(report.diagnostics) == 1


def test_active_git_index_is_used_and_an_unowned_index_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    candidate = root / ".git/candidate-index"
    shutil.copyfile(root / ".git/index", candidate)
    (root / "infra/child/outputs.tf").write_text('output "used" { value = "used" }\n')
    _git(root, "add", ".")
    assert not _report(root).diagnostics
    monkeypatch.setenv("GIT_INDEX_FILE", str(candidate))
    report = _report(root)
    assert not report.issues
    assert len(report.diagnostics) == 1
    foreign = tmp_path / "foreign-index"
    shutil.copyfile(candidate, foreign)
    monkeypatch.setenv("GIT_INDEX_FILE", str(foreign))
    assert _report(root).completion is Completion.FAILED


@pytest.mark.parametrize("annotated", [False, True], ids=["plain", "reasoned-noqa"])
def test_native_cli_selected_rule_blocks_the_exact_staged_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, annotated: bool
) -> None:
    root = _repository(tmp_path)
    if annotated:
        source = root / "infra/child/outputs.tf"
        source.write_text("# sarj-noqa: SARJ223 — migration\n" + source.read_text())
        _git(root, "add", ".")
    assert main(["--root", str(root), "check", "--staged", "--rule", _RULE, "infra/child/outputs.tf"]) == 1
    captured = capsys.readouterr()
    assert "SARJ223" in captured.out
    assert "external" in captured.out


def test_a_deletion_only_commit_still_checks_unchanged_outputs(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "other-root").mkdir()
    consumer = root / "other-root/main.tf"
    consumer.write_text(
        'module "shared" { source = "../infra/child" }\noutput "public" { value = module.shared.external }\n'
    )
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Lint Fixture",
        "-c",
        "user.email=lint@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    assert not _report(root).diagnostics
    consumer.unlink()
    _git(root, "add", "--update")
    assert len(_report(root).diagnostics) == 1


@pytest.mark.parametrize("iac", [None, False, []], ids=["null", "boolean", "array"])
def test_malformed_iac_configuration_cannot_hide_external_contracts(iac: bool | list[str] | None) -> None:
    with pytest.raises(ValueError, match="valid dictionary"):
        terraform_output_contracts({"iac": iac})


def test_diagnostic_path_cannot_follow_an_unstaged_symlink(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    source = root / "infra/child/outputs.tf"
    source.unlink()
    source.symlink_to(root / "infra/main.tf")
    report = _report(root)
    assert not report.issues
    finding = report.diagnostics[0]
    assert finding.location.path == "infra/child/outputs.tf"
    assert finding.location.position is not None
    assert finding.location.position.line == 1
