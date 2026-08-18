from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rules.no_comment_cruft import NoCommentCruft


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoCommentCruft.public_examples()


def _check(source: str, name: str = "main.tf") -> list[Diagnostic]:
    return NoCommentCruft().check(Path(name), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoCommentCruft().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_commented_out_resource():
    src = """
# resource "google_storage_bucket" "old" {
resource "google_storage_bucket" "new" {}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "Commented-out" in diags[0].message


def test_flags_commented_out_attribute():
    src = 'name = "x"\n# ttl = 3600\n'
    assert len(_check(src)) == 1


def test_flags_section_banner():
    src = "# ============================================\nlocals {}\n"
    assert len(_check(src)) == 1


def test_flags_double_slash_comment_code():
    src = '// module "vpc" {\nmodule "vpc2" {}\n'
    assert len(_check(src)) == 1


def test_allows_prose_why_comment():
    src = '# keep this bucket in us-central1 for data residency\nresource "x" "y" {}\n'
    assert _check(src) == []


def test_allows_directive_comments():
    src = """
# tflint-ignore: terraform_unused_declarations
# checkov:skip=CKV_GCP_1: justified
# sarj-noqa: SARJ201 — ephemeral
# TODO: split this module
variable "x" {}
"""
    assert _check(src) == []


def test_yaml_only_flags_banners_not_keys():
    # In YAML, `key: value` prose must NOT be treated as commented-out code.
    src = "# note: remember to bump the chart version\n# ------------------------------\nname: app\n"
    diags = _check(src, name="values.yaml")
    assert len(diags) == 1
    assert "banner" in diags[0].message.lower()


def test_allows_short_equals_in_prose():
    src = "# use == for comparison in the policy\nx = 1\n"
    assert _check(src) == []


def test_allows_prose_legend_with_equals():
    # A doc comment legend ("deploy = provision the stack") is not commented code.
    src = """
//   deploy = provision the self-hosted SFU stack (it runs, but no traffic).
//   active = repoint LIVEKIT_URL to it.
variable "x" {}
"""
    assert _check(src) == []


def test_still_flags_commented_attr_with_value():
    src = '# bucket = "old-name"\n# ttl = 3600\n# enabled = true\nresource "x" "y" {}\n'
    assert len(_check(src)) == 3


def test_tfvars_commented_inputs_not_flagged_only_banners():
    # Commented `key = ""` menus in .tfvars are conventional, not dead code.
    src = '# twilio_account_sid = ""\n# =========================\nstack = "prod"\n'
    diags = _check(src, name="prod.tfvars")
    assert len(diags) == 1
    assert "banner" in diags[0].message.lower()


def test_testdata_can_encode_removed_configuration():
    src = '# module "child" {\n#   source = "./child"\n# }\n'

    assert _check(src, name="testdata/removed-module/main.tf") == []


def test_ignores_comment_lines_inside_heredoc_body():
    # `#` and `key = 3` lines inside a heredoc are data, not dead HCL.
    src = """
script = <<-EOT
  # this is a shell comment, not dead Terraform
  retry = 3
  resource "x" "y" {
EOT
resource "real" "one" {}
"""
    assert _check(src) == []


def test_digit_prose_rhs_not_flagged():
    # `# retry = 3 attempts` is prose, not commented HCL — consistent with the
    # word-RHS prose case that is already allowed.
    src = '# retry = 3 attempts before giving up\nresource "x" "y" {}\n'
    assert _check(src) == []


def test_bare_number_attribute_still_flagged():
    src = '# ttl = 3600\nresource "x" "y" {}\n'
    assert len(_check(src)) == 1


def test_allows_a_usage_example_inside_a_prose_doc_header():
    src = """
# Example usage of this module.
#
# Copy the block below into your root module and set the variables
# you need; every input is documented in variables.tf.
#
# module "litellm" {
#     source  = "github.com/BerriAI/litellm//terraform/litellm/gcp?ref=<tag>"
# }
#
# See the README for the full list of supported regions.
resource "google_project_service" "run" {}
"""
    assert _check(src) == []


def test_flags_a_run_that_is_mostly_disabled_code():
    """The boundary: a genuine disabled block is code-dominant and must still fire."""
    src = _PUBLIC_EXAMPLES[0].focus_file.source
    diags = _check(src)
    assert len(diags) == _PUBLIC_EXAMPLES[0].expected_count
    assert all("Commented-out Terraform" in d.message for d in diags)


def test_flags_a_half_code_run_at_the_threshold():
    """The boundary: the threshold is >= 50%, not > 50%."""
    src = """
# keep the legacy bucket around until Q3
# force_destroy = true
resource "google_storage_bucket" "new" {}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_a_lone_attribute_line_is_still_code_dominant():
    """The boundary: a one-line run of pure code is 100% code and must fire."""
    src = """
# ttl = 3600
resource "google_dns_record_set" "a" {}
"""
    assert len(_check(src)) == 1


def test_banner_detection_is_unaffected_by_run_dominance():
    """A prose-dominant comment run does not stop its banner lines being banners."""
    src = """
# ============================================================
# Networking — VPC, subnets and the private service connection
# ============================================================
resource "google_compute_network" "vpc" {}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message
    assert diags[0].line == 2


def test_each_banner_in_a_file_is_reported_once():
    """Two banners are two findings: the collapse is per banner, not per file."""
    src = """
################
# A
################

resource "x" "y" {}

################
# B
################
"""
    diags = _check(src)
    assert [d.line for d in diags] == [2, 8]


def test_a_lone_divider_with_no_title_is_still_one_finding():
    """A single rule line is its own banner group; nothing to collapse."""
    src = """
# ------------------------------------------------------------
resource "x" "y" {}
"""
    assert len(_check(src)) == 1


def test_a_blank_line_between_rules_starts_a_new_banner():
    """A blank line breaks the comment run, so these are two banners."""
    src = """
# ============================================================

# ============================================================
resource "x" "y" {}
"""
    assert [d.line for d in _check(src)] == [2, 4]


def test_a_mixed_character_rule_is_a_banner():
    """`# -=-=-=-=` has no 4-run of any single character — only the full-body regex sees it."""
    src = '# -=-=-=-=\nresource "google_compute_network" "vpc" {}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


def test_a_rule_with_a_title_after_it_is_a_banner():
    """`# ==== Section ====` has letters, so the full-body regex cannot see it."""
    src = '# ==== Networking ====\nresource "google_compute_network" "vpc" {}\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "Section-banner" in diags[0].message


def test_four_characters_is_already_a_banner():
    """The lower boundary: the threshold is four, and four must fire."""
    assert len(_check('# ====\nresource "google_compute_network" "vpc" {}\n')) == 1


@pytest.mark.parametrize("body", ["==", "---"])
def test_a_run_shorter_than_four_is_not_a_banner(body: str):
    """The other side of the boundary: two or three characters do not read as a rule."""
    assert _check(f'# {body}\nresource "google_compute_network" "vpc" {{}}\n') == []


def test_a_directive_that_happens_to_contain_a_rule_is_not_a_banner():
    """A `# TODO` about banners is a directive first — otherwise SARJ202 flags its own fix."""
    src = '# TODO: replace the ==== dividers in this file with real blocks\nresource "google_storage_bucket" "b" {}\n'
    assert _check(src) == []


def test_directives_do_not_vote_on_whether_a_run_is_code():
    """Directives are neither prose nor code; counting them as prose hides real dead code."""
    src = """
# tflint-ignore: terraform_unused_declarations
# checkov:skip=CKV_GCP_1: justified
# TODO: remove after the migration lands
# bucket        = "legacy-artifacts"
# force_destroy = true
resource "google_storage_bucket" "new" {}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [5, 6]
    assert all("Commented-out Terraform" in d.message for d in diags)


@pytest.mark.parametrize(
    "body",
    [
        "# ==========================================\n    # bootstrap\n    # ==========================================",
        '# bucket        = "legacy"\n    # force_destroy = true',
    ],
    ids=["banner-shaped", "code-shaped"],
)
def test_a_heredoc_body_is_never_comment_cruft(body: str):
    """A shell script's `#` lines are the script, not a disabled Terraform block."""
    src = f"""
resource "google_compute_instance" "node" {{
  metadata_startup_script = <<-EOT
    {body}
    set -euo pipefail
  EOT
}}
"""
    assert _check(src) == []


def test_the_same_lines_outside_a_heredoc_are_still_judged():
    """The boundary: the heredoc is what excuses them, not their content."""
    src = '# bucket        = "legacy"\n# force_destroy = true\nresource "google_storage_bucket" "new" {}\n'
    assert len(_check(src)) == 2


@pytest.mark.parametrize(
    "separator",
    ['resource "google_compute_network" "vpc" {}', ""],
    ids=["real-hcl", "blank-line"],
)
def test_a_prose_run_does_not_dilute_a_neighbouring_dead_code_run(separator: str):
    """Merge the two runs and the file's five voting lines are only 40% code — silence."""
    src = f"""
# Networking module.
# See the README for the supported regions and the private service
# connection prerequisites before enabling this.
{separator}
# name          = "legacy"
# force_destroy = true
resource "google_storage_bucket" "new" {{}}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [6, 7]
    assert all("Commented-out Terraform" in d.message for d in diags)
