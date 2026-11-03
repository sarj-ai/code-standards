from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rules.no_terraform_comments import NoTerraformComments


def test_documented_examples() -> None:
    verify_native_rule(NoTerraformComments, analyze)


@pytest.mark.parametrize("comment", ["# rationale", "// rationale", "/* rationale */"])
def test_rejects_each_comment_syntax(comment: str) -> None:
    findings = NoTerraformComments().check(Path("main.tf"), f"locals {{\n  value = 1 {comment}\n}}\n")

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (2, 13)


def test_reports_multiline_comment_once() -> None:
    source = '/* first\n * second\n */\nvariable "region" { type = string }\n'

    assert [(d.line, d.col) for d in NoTerraformComments().check(Path("main.tf"), source)] == [(1, 1)]


def test_preserves_comment_markers_in_strings_and_heredocs() -> None:
    source = 'locals {\n  url = "https://example.com/#anchor"\n  script = <<DOC\n# shell comment\n/* text */\nDOC\n}\n'

    assert NoTerraformComments().check(Path("main.tf"), source) == []


def test_rejects_real_comment_inside_template_interpolation() -> None:
    source = 'locals {\n  text = "${1 /* rationale */ + 2}"\n}\n'

    assert len(NoTerraformComments().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("path", ["values.tfvars", "test.tftest.hcl", "example.yaml"])
def test_only_bans_terraform_source_comments(path: str) -> None:
    assert NoTerraformComments().check(Path(path), "# configuration\n") == []


def test_comment_ban_cannot_suppress_itself(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text("# sarj-noqa: SARJ216 -- bypass\nlocals { value = 1 }\n")

    assert len(analyze([NoTerraformComments.id], [path])) == 1


def test_ban_takes_precedence_over_narrower_comment_rules(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text("# ==== Resources ====\nlocals { value = 1 }\n")

    findings = analyze(["no-comment-cruft", "no-restated-comment", NoTerraformComments.id], [path])

    assert [finding.code for finding in findings] == [NoTerraformComments.code]
