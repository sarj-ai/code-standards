from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.declaration_fixes import consolidate_declarations
from sarj_iac_lint.rules.canonical_terraform_declarations import CanonicalTerraformDeclarations


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    verify_native_rule(CanonicalTerraformDeclarations, analyze, fix=_project_fix)


def _project_fix(root: Path, path: Path, source: str) -> str:
    sources = {item: item.read_text() for item in root.glob("*.tf")}
    return consolidate_declarations(sources, selected=tuple(sources)).get(path, source)
