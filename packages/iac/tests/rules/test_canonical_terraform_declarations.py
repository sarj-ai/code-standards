from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze, main
from sarj_iac_lint.declaration_fixes import consolidate_declarations
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.canonical_terraform_declarations import CanonicalTerraformDeclarations


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    verify_native_rule(CanonicalTerraformDeclarations, analyze, fix=_project_fix)


def _project_fix(root: Path, path: Path, source: str) -> str:
    sources = {item: item.read_text() for item in root.glob("*.tf")}
    return consolidate_declarations(sources, selected=tuple(sources)).get(path, source)


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("service.tf", 'variable "region" { type = string }\n'),
        ("service.tf.json", '{"output":{"region":{"value":"${var.region}"}}}\n'),
    ],
)
def test_native_cli_blocks_misplaced_declarations_with_shrink_only_baseline(
    tmp_path: Path, filename: str, source: str
) -> None:
    path = tmp_path / filename
    path.write_text(source)
    arguments = ["check", "--rule", CanonicalTerraformDeclarations.id, str(path)]
    baseline = tmp_path / "baseline.json"

    findings = analyze([CanonicalTerraformDeclarations.id], [path])
    assert [finding.severity for finding in findings] == [DefaultLevel.ERROR]
    assert main(arguments) == 1
    assert main([*arguments, "--update-baseline", str(baseline)]) == 0
    assert main([*arguments, "--baseline", str(baseline)]) == 0
    extra = tmp_path / "extra.tf"
    extra.write_text('variable "project" { type = string }\n')
    assert main([*arguments, str(extra), "--baseline", str(baseline)]) == 1


def test_exact_reasoned_suppression_preserves_a_deliberate_interface_boundary(tmp_path: Path) -> None:
    path = tmp_path / "service.tf"
    path.write_text(
        'variable "region" { type = string } '
        "# sarj-noqa: SARJ224 -- Preserve the signed external module source layout.\n"
    )
    assert main(["check", "--rule", CanonicalTerraformDeclarations.id, str(path)]) == 0
