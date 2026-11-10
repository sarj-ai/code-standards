from dataclasses import replace
from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rule_base import DefaultLevel
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


@pytest.mark.parametrize(
    ("level", "codes"),
    [(DefaultLevel.WARNING, ["SARJ202", "SARJ216"]), (DefaultLevel.ERROR, ["SARJ216"])],
)
def test_warning_preserves_existing_errors_until_ban_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: DefaultLevel, codes: list[str]
) -> None:
    path = tmp_path / "main.tf"
    path.write_text("# ==== Resources ====\nlocals { value = 1 }\n")
    authored = NoTerraformComments.documentation
    assert authored is not None
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Authored class-level severity lookup is the precedence behavior under test.
        NoTerraformComments, "documentation", replace(authored, default_level=level)
    )

    findings = analyze(["no-comment-cruft", "no-restated-comment", NoTerraformComments.id], [path])

    assert [finding.code for finding in findings] == codes


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_module_summary_requires_explicit_opt_in(newline: str) -> None:
    source = newline.join(["# Voice runtime", "", 'resource "example_service" "voice" {}', ""])

    assert [item.code for item in NoTerraformComments().check(Path("main.tf"), source)] == ["SARJ216"]
    assert NoTerraformComments(module_summaries=True).check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("services.tf", '# Voice runtime\n\nresource "example_service" "voice" {}\n'),
        ("main.tf", '\n# Voice runtime\n\nresource "example_service" "voice" {}\n'),
        ("main.tf", '// Voice runtime\n\nresource "example_service" "voice" {}\n'),
        ("main.tf", '/* Voice runtime */\n\nresource "example_service" "voice" {}\n'),
        ("main.tf", '# Voice runtime\nresource "example_service" "voice" {}\n'),
        ("main.tf", '# Voice runtime\n \nresource "example_service" "voice" {}\n'),
        ("main.tf", '# Voice runtime \n\nresource "example_service" "voice" {}\n'),
        ("main.tf", "# sarj-noqa: SARJ216 -- bypass\n\nlocals { value = 1 }\n"),
        ("main.tf", "# checkov:skip=CKV_EXAMPLE\n\nlocals { value = 1 }\n"),
        ("main.tf", "# Value = 1\n\nlocals { value = 1 }\n"),
        ("main.tf", "# Voice { runtime }\n\nlocals { value = 1 }\n"),
        ("main.tf", "# =====\n\nlocals { value = 1 }\n"),
        ("main.tf", "# \n\nlocals { value = 1 }\n"),
    ],
)
def test_opt_in_does_not_allow_other_comment_forms(name: str, source: str) -> None:
    assert len(NoTerraformComments(module_summaries=True).check(Path(name), source)) == 1


@pytest.mark.parametrize("body", ["", "locals { value =\n", 'resource "example_service" "voice" {}\n'])
def test_summary_classification_leaves_body_validation_to_terraform(body: str) -> None:
    assert NoTerraformComments(module_summaries=True).check(Path("main.tf"), "# Voice runtime\n\n" + body) == []


@pytest.mark.parametrize(
    "marker",
    [
        "nosemgrep",
        "NOSEMGREP",
        "nosemgrep; other text",
        "Runtime nosemgrep",
        "noqa",
        "noqa.",
        "nosec",
        "nolint",
        "NOSONAR",
        "sarj-noqa",
        "kics-scan ignore",
        "Code generated by a tool. DO NOT EDIT.",
        "Generated source, don't edit",
        "Do not edit generated source",
    ],
)
def test_summary_exception_cannot_mark_source_suppressed_or_generated(marker: str) -> None:
    source = f'# {marker}\n\nresource "example_service" "voice" {{}}\n'

    assert len(NoTerraformComments(module_summaries=True).check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize("caption", ["Terraform module wiring", "Generated report storage", "Voice runtime"])
def test_plain_purpose_near_misses_are_still_allowed(caption: str) -> None:
    source = f'# {caption}\n\nresource "example_service" "voice" {{}}\n'

    assert NoTerraformComments(module_summaries=True).check(Path("main.tf"), source) == []


@pytest.mark.parametrize("length", [79, 80, 81])
def test_module_summary_length_boundary(length: int) -> None:
    source = "# " + "A" * (length - 2) + '\n\nresource "example_service" "voice" {}\n'

    assert len(NoTerraformComments(module_summaries=True).check(Path("main.tf"), source)) == int(length > 80)


def test_opt_in_still_reports_every_other_comment(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text("# Voice runtime\n\n# sarj-noqa: SARJ216 -- bypass\nlocals { value = 1 /* note */ }\n")

    findings = analyze([NoTerraformComments.id], [path], module_summaries=True)

    assert [(item.line, item.code) for item in findings] == [(3, "SARJ216"), (4, "SARJ216")]
    assert all(not item.suppressible for item in findings)
