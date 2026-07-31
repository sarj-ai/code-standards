from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_iac_lint.rules.no_comment_cruft import NoCommentCruft


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic


def _check(source: str, name: str = "main.tf") -> list[Diagnostic]:
    return NoCommentCruft().check(Path(name), source)


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


# --- the commented-out half judges the RUN, not the line --------------------------
#
# `_HCL_CODE_RE` classified any HCL-shaped line as dead code, including an indented
# usage example inside a prose documentation header. 12 of the 31 commented-out
# findings in the corpus sat in prose-dominant runs.


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
    src = """
# resource "google_storage_bucket" "old" {
#   name          = "legacy-artifacts"
#   location      = "US"
#   force_destroy = true
# }
resource "google_storage_bucket" "new" {}
"""
    diags = _check(src)
    assert len(diags) == 5
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
    """Banners are a house-style call and are judged per line, not per run."""
    src = """
# ============================================================
# Networking — VPC, subnets and the private service connection
# ============================================================
resource "google_compute_network" "vpc" {}
"""
    diags = _check(src)
    assert len(diags) == 2
    assert all("Section-banner" in d.message for d in diags)
