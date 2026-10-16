from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rule_base import is_suppressed
from sarj_iac_lint.rules.no_environment_conditional import (
    ENVIRONMENT_SEGMENTS,
    QUALIFIED_SEGMENTS,
    NoEnvironmentConditional,
    uses_environment_conditional,
)


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic


def _check(source: str, name: str = "main.tf") -> list[Diagnostic]:
    return NoEnvironmentConditional().check(Path(name), source)


def test_flags_equality_against_an_environment_literal():
    src = """
resource "google_redis_instance" "cache" {
  tier = var.environment == "production" ? "STANDARD_HA" : "BASIC"
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert 'var.environment == "production"' in diags[0].message
    assert diags[0].code == "SARJ204"


def test_flags_inequality_against_an_environment_literal():
    src = """
resource "google_storage_bucket" "b" {
  count = var.environment != "prod" ? 1 : 0
}
"""
    assert len(_check(src)) == 1


def test_flags_terraform_workspace_comparison():
    src = """
resource "google_storage_bucket" "b" {
  count = terraform.workspace == "prod" ? 1 : 0
}
"""
    assert len(_check(src)) == 1


def test_flags_a_literal_first_comparison():
    src = """
resource "google_storage_bucket" "b" {
  count = "prod" == var.environment ? 1 : 0
}
"""
    assert len(_check(src)) == 1


def test_flags_contains_with_a_literal_list_and_the_environment_as_needle():
    src = """
locals {
  ingest = contains(["preview", "sandbox"], var.environment) ? "internal" : "public"
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "contains([...], var.environment)" in diags[0].message


@pytest.mark.parametrize(
    ("expression", "expected_count"),
    [
        pytest.param('!contains(["dev", "preview"], var.cloud_build_branch)', 1, id="cloud-build-approval-gate"),
        pytest.param('contains(["dev", "preview"], var.branch)', 1, id="branch-membership"),
        pytest.param('contains(["platform-prod"], var.project_id)', 1, id="project-membership"),
        pytest.param('contains(["dev", "preview"], var.stack)', 1, id="stack-membership"),
        pytest.param('contains(["platform-prod"], local.stack_name)', 1, id="qualified-stack-membership"),
        pytest.param('contains((["dev", "preview"]), (var.cloud_build_branch))', 1, id="parenthesized-membership"),
        pytest.param('contains(["dev"], lower(trimspace(var.cloud_build_branch)))', 1, id="normalized-branch"),
        pytest.param('contains(["DEV"], upper(var.stack))', 1, id="normalized-stack"),
        pytest.param('var.cloud_build_branch == "prod"', 1, id="branch-comparison"),
        pytest.param('var.stack == "production"', 1, id="stack-comparison"),
        pytest.param('contains(["feature", "release"], var.cloud_build_branch)', 0, id="ordinary-build-branches"),
        pytest.param('contains(["finance", "billing"], var.stack)', 0, id="business-stack-labels"),
        pytest.param('contains(["prod"], var.tree_branch)', 0, id="unrelated-resource-branch"),
        pytest.param('contains(["prod"], var.customer_stack_id)', 0, id="unrelated-resource-stack"),
        pytest.param('contains(["developmental"], var.stack)', 0, id="literal-substring"),
        pytest.param("contains(var.allowed_branches, var.cloud_build_branch)", 0, id="typed-input-list"),
        pytest.param("contains(local.allowed_branches, var.cloud_build_branch)", 0, id="unresolved-local-list"),
        pytest.param('contains(["${var.allowed_branch}"], var.cloud_build_branch)', 0, id="dynamic-list-member"),
        pytest.param('contains(["%{ if var.enabled }dev%{ endif }"], var.stack)', 0, id="dynamic-list-directive"),
        pytest.param('contains(["prod"], coalesce(var.cloud_build_branch, "dev"))', 0, id="arbitrary-function"),
        pytest.param('contains(["prod"], var.stack, true)', 0, id="invalid-arity"),
    ],
)
def test_membership_uses_literal_environment_evidence_for_deployment_selectors(
    expression: str, expected_count: int
) -> None:
    source = f'resource "google_clouddeploy_target" "target" {{\n  require_approval = {expression}\n}}\n'
    diagnostics = _check(source)
    assert [(finding.code, finding.line, finding.col) for finding in diagnostics] == (
        [("SARJ204", 2, 3)] if expected_count else []
    )
    assert diagnostics == _check(source)
    assert uses_environment_conditional(expression) is bool(expected_count)


def test_flags_environment_selected_access_groups():
    src = """locals {
  product_qa_nonprod_groups = contains(["dev", "preview", "sandbox"], var.environment) ? toset([
    "team-product@sarj.ai",
    "team-qa@sarj.ai",
  ]) : toset([])
}
"""
    diagnostics = _check(src)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ204"


def test_flags_a_parenthesized_identity_operand():
    src = """
locals {
  on = (var.environment) == "prod"
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert 'var.environment == "prod"' in diags[0].message


def test_flags_a_doubly_parenthesized_identity_in_a_ternary():
    src = """
resource "google_storage_bucket" "b" {
  count = ((var.environment)) == "prod" ? 1 : 0
}
"""
    assert len(_check(src)) == 1


def test_flags_a_parenthesized_literal_operand():
    src = """
locals {
  on = var.environment == ("prod")
}
"""
    assert len(_check(src)) == 1


def test_flags_a_normalized_environment_compared_to_a_literal():
    src = """
locals {
  on = upper(var.environment) == "PROD"
}
"""
    assert len(_check(src)) == 1


def test_flags_a_parenthesized_operand_inside_a_list_for_expression():
    src = """
locals {
  subnets = [for e in var.subnets : e if (var.environment) == "prod"]
}
"""
    assert len(_check(src)) == 1


def test_flags_a_parenthesized_operand_inside_a_map_for_expression():
    src = """
locals {
  tags = { for k, v in var.tags : k => v if (var.environment) == "prod" }
}
"""
    assert len(_check(src)) == 1


def test_flags_a_normalized_identity_inside_a_for_expression():
    src = """
locals {
  subnets = [for e in var.subnets : e if upper(var.environment) == "PROD"]
}
"""
    assert len(_check(src)) == 1


def test_environment_keyed_map_index_is_data_selection():
    src = """
locals {
  tier = local.tiers[var.environment]
}
"""
    assert _check(src) == []


def test_environment_index_on_a_chained_subject_is_data_selection():
    src = """
locals {
  tier = local.cfg["tiers"][var.environment]
}
"""
    assert _check(src) == []


def test_environment_index_inside_a_call_is_data_selection():
    src = """
locals {
  on = tobool(local.flags[var.environment])
}
"""
    assert _check(src) == []


def test_a_list_literal_holding_the_identity_is_not_an_index():
    src = """
locals {
  on = contains([var.environment], "prod")
}
"""
    assert _check(src) == []


def test_an_index_by_a_plain_string_key_is_not_flagged():
    src = """
locals {
  env = local.cfg["env"]
}
"""
    assert _check(src) == []


def test_a_parenthesized_empty_string_sentinel_stays_exempt():
    src = """
locals {
  host = (var.environment) != "" ? var.environment : "local"
}
"""
    assert _check(src) == []


def test_flags_contains_with_a_parenthesized_needle():
    src = """
locals {
  on = contains(["preview", "prod"], (var.environment)) ? 1 : 0
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "contains([...], var.environment)" in diags[0].message


def test_contains_with_a_normalized_environment_needle_is_flagged():
    src = """
locals {
  on = contains(["preview", "prod"], (upper(var.environment)))
}
"""
    assert len(_check(src)) == 1


def test_lookup_keyed_by_the_environment_is_data_selection():
    src = """
resource "google_privileged_access_manager_entitlement" "access" {
  max_request_duration = lookup(local.durations, var.environment, "3600s")
}
"""
    assert _check(src) == []


def test_flags_a_local_that_branches_on_the_environment():
    src = """
locals {
  roles = var.deployment_slug == "staging-preview" ? ["roles/owner"] : []
}
"""
    assert len(_check(src)) == 1


def test_flags_a_conditional_nested_in_a_dynamic_block():
    src = """
resource "google_project_iam_member" "m" {
  dynamic "condition" {
    for_each = each.value == "roles/x" && var.project == "sarj-platform-dev" ? [1] : []
    content {
      title = "t"
    }
  }
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_never_flags_the_empty_string_sentinel():
    src = """
locals {
  host = var.environment != "" ? var.environment : "local"
}
"""
    assert _check(src) == []


def test_never_flags_an_empty_string_sentinel_on_a_weak_keyword_name():
    src = """
locals {
  ui = var.langfuse_ui_project_id != "" ? var.langfuse_ui_project_id : ""
}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    ("identity", "literal"),
    [
        ("var.project", "analytics"),
        ("var.account", "enterprise"),
        ("var.tenant", "customer-a"),
        ("var.branch", "main"),
        ("var.slug", "billing"),
    ],
)
def test_ambiguous_identity_names_need_environment_evidence(identity: str, literal: str):
    src = f"""\nlocals {{\n  selected = {identity} == "{literal}" ? "a" : "b"\n}}\n"""

    assert _check(src) == []


def test_an_ambiguous_project_name_with_environment_evidence_is_flagged():
    src = """
locals {
  selected = var.gcp_project_id == "platform-prod" ? "a" : "b"
}
"""

    assert len(_check(src)) == 1


def test_an_ambiguous_identity_used_as_a_map_key_is_not_enough_evidence():
    src = """
locals {
  selected = local.projects[var.project]
}
"""

    assert _check(src) == []


def test_flags_the_same_variable_against_a_real_literal():
    src = """
locals {
  ui = var.environment == "prod" ? "a" : "b"
}
"""
    assert len(_check(src)) == 1


def test_never_flags_a_whitespace_only_literal():
    src = """
locals {
  host = var.environment != "   " ? "a" : "b"
}
"""
    assert _check(src) == []


def test_exempts_a_variable_validation_block():
    src = """
variable "environment" {
  type = string
  validation {
    condition     = contains(["prod", "preview", "dev", "sandbox"], var.environment)
    error_message = "unknown environment"
  }
}
"""
    assert _check(src) == []


def test_exempts_a_lifecycle_precondition():
    src = """
resource "google_storage_bucket" "b" {
  lifecycle {
    precondition {
      condition     = var.environment != "production"
      error_message = "canary must not run in prod"
    }
  }
}
"""
    assert _check(src) == []


def test_exempts_a_postcondition():
    src = """
data "google_project" "p" {
  lifecycle {
    postcondition {
      condition     = var.project == "sarj-platform-dev"
      error_message = "wrong project"
    }
  }
}
"""
    assert _check(src) == []


def test_exempts_an_assert_inside_a_check_block():
    src = """
check "environment" {
  assert {
    condition     = var.environment == "prod"
    error_message = "nope"
  }
}
"""
    assert _check(src) == []


def test_exempts_tftest_hcl_files_entirely():
    src = """
run "check" {
  assert_this = var.environment == "prod"
}
"""
    assert _check(src, name="setup.tftest.hcl") == []


def test_still_flags_a_sibling_of_an_exempt_block():
    src = """
variable "environment" {
  validation {
    condition     = contains(["prod", "dev"], var.environment)
    error_message = "unknown"
  }
}

resource "google_storage_bucket" "b" {
  count = var.environment == "prod" ? 1 : 0
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 10


def test_contains_with_the_identity_as_haystack_is_not_flagged():
    src = """
resource "google_secret_manager_secret" "s" {
  count = contains(var.app_managed_secret_ids, "sql-uri") ? 1 : 0
}
"""
    assert _check(src) == []


def test_flags_contains_with_a_non_literal_haystack():
    src = """
locals {
  on = contains(local.prod_like, var.environment)
}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "contains(..., var.environment)" in diags[0].message


def test_flags_contains_even_when_the_haystack_is_itself_an_identity():
    src = """
locals {
  on = contains(var.environments, var.environment)
}
"""
    assert _check(src) == []


def test_contains_with_a_non_identity_needle_is_not_flagged():
    src = """
locals {
  on = contains(local.prod_like, var.service_key)
}
"""
    assert _check(src) == []


def test_lookup_with_the_environment_as_the_default_is_not_flagged():
    src = """
locals {
  name = lookup(local.names, var.service_key, var.environment)
}
"""
    assert _check(src) == []


def test_never_flags_string_interpolation():
    src = """
resource "google_storage_bucket" "b" {
  name = "cache-${var.environment}"
}
"""
    assert _check(src) == []


def test_never_flags_interpolation_inside_a_list():
    src = """
locals {
  names = ["${var.environment}-a", "${var.environment}-b"]
}
"""
    assert _check(src) == []


def test_never_flags_a_comparison_against_an_interpolated_string():
    src = """
locals {
  on = var.environment == "prod-${var.suffix}" ? 1 : 0
}
"""
    assert _check(src) == []


def test_flags_a_comparison_whose_branches_interpolate():
    src = """
locals {
  host = var.environment == "prod" ? "https://${var.domain}" : "http://localhost"
}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("name", "flagged"),
    [
        ("var.environment", True),
        ("var.env", True),
        ("var.deployment_slug", True),
        ("var.project", True),
        ("var.project_id", True),
        ("var.gcp_project_id", True),
        ("var.langfuse_ui_project_id", False),
        ("var.stripe_account_id", False),
        ("var.customer_slug", False),
        ("var.envelope_encryption_key", False),
        ("var.environments", False),
        ("var.region", False),
    ],
)
def test_matches_a_segment_not_a_substring(name: str, flagged: bool):
    src = f"""
locals {{
  x = {name} == "prod" ? "a" : "b"
}}
"""
    assert bool(_check(src)) is flagged


def test_matches_the_final_component_of_a_traversal():
    src = """
locals {
  a = local.config.environment == "prod" ? 1 : 0
  b = var.environment_config.region == "prod" ? 1 : 0
}
"""
    diags = _check(src)
    assert len(diags) == 2
    assert diags[0].line == 3


def test_the_segment_sets_are_exactly_these():
    assert {"environment", "env"} == ENVIRONMENT_SEGMENTS
    assert {"project", "slug", "branch", "account", "tenant", "stage", "workspace", "deployment", "stack"} == (
        QUALIFIED_SEGMENTS
    )


def test_flags_a_module_input_computed_from_the_environment():
    src = """
module "iam" {
  source                             = "./iam"
  team_platform_owner_privilege      = var.environment == "dev"
  developer_secret_access_v2_enabled = var.environment == "dev"
}
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == [4, 5]
    assert "selected typed value" in diags[0].message
    assert "named capability" in diags[0].message
    assert "root configuration" in diags[0].message


def test_does_not_flag_a_module_input_passed_straight_through():
    src = """
module "iam" {
  source                        = "./iam"
  team_platform_owner_privilege = var.team_platform_owner_privilege
}
"""
    assert _check(src) == []


def test_flags_a_count_gate_on_a_module_call():
    src = """
module "sandbox" {
  source = "./sandbox"
  count  = var.environment == "sandbox" ? 1 : 0
}
"""
    assert len(_check(src)) == 1


def test_flags_a_local_wired_into_module_inputs():
    src = """
locals {
  langfuse_host = contains(["preview", "sandbox"], var.environment) ? "internal" : var.langfuse_host
}

module "services" {
  source = "./services"
  host   = local.langfuse_host
}
"""
    assert len(_check(src)) == 1


def test_names_the_attribute_and_its_block_in_the_message():
    src = """
module "iam" {
  source          = "./iam"
  owner_privilege = var.environment == "dev"
}
"""
    (diag,) = _check(src)
    assert '`owner_privilege` in module "iam"' in diag.message


def test_reports_one_finding_per_attribute_not_per_operator():
    src = """
locals {
  on = var.environment == "dev" || var.environment == "preview"
}
"""
    assert len(_check(src)) == 1


def test_reports_every_resource_that_repeats_the_same_gate():
    src = """
resource "cloudflare_r2_bucket" "a" {
  count = var.environment == "sandbox" ? 1 : 0
}

resource "cloudflare_d1_database" "b" {
  count = var.environment == "sandbox" ? 1 : 0
}

resource "cloudflare_worker" "c" {
  count = var.environment == "sandbox" ? 1 : 0
}
"""
    assert len(_check(src)) == 3


def test_reports_the_attribute_line_and_column():
    src = """
resource "google_storage_bucket" "b" {
  count = var.environment == "prod" ? 1 : 0
}
"""
    diags = _check(src)
    assert (diags[0].line, diags[0].col) == (3, 3)


def test_diagnostics_are_in_source_order():
    src = """
resource "google_storage_bucket" "outer" {
  dynamic "x" {
    for_each = var.environment == "dev" ? [1] : []
    content {
      name = "n"
    }
  }

  count = var.environment == "prod" ? 1 : 0
}
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_ignores_non_hcl_files():
    src = """
resource "google_storage_bucket" "b" {
  count = var.environment == "prod" ? 1 : 0
}
"""
    assert _check(src, name="values.yaml") == []


def test_flags_a_terragrunt_top_level_attribute():
    src = 'top_level = var.environment == "prod"\n'
    diags = _check(src, name="terragrunt.hcl")
    assert len(diags) == 1
    assert "`top_level` in the file root" in diags[0].message


def test_flags_a_conditional_inside_a_terragrunt_inputs_map():
    src = """
inputs = {
  enabled = local.environment == "prod" ? 1 : 0
}
"""
    diags = _check(src, name="terragrunt.hcl")
    assert len(diags) == 1
    assert diags[0].line == 2


def test_top_level_and_block_diagnostics_stay_in_source_order():
    src = """
top_level = var.environment == "prod"

locals {
  on = var.environment == "dev" ? 1 : 0
}
"""
    diags = _check(src, name="terragrunt.hcl")
    assert [d.line for d in diags] == [2, 5]


def test_ignores_tfvars():
    assert _check('environment = "prod"\n', name="prod.tfvars") == []


@pytest.mark.parametrize(
    ("identity", "literal"),
    [("var.workspace", "finance"), ("var.stage", "build"), ("var.deployment", "api")],
)
def test_ambiguous_deployment_terms_need_environment_literal_evidence(identity: str, literal: str):
    assert _check(f'locals {{\n  selected = {identity} == "{literal}" ? 1 : 0\n}}\n') == []


@pytest.mark.parametrize("identity", ["var.workspace", "var.stage", "var.deployment"])
def test_ambiguous_deployment_terms_match_with_environment_evidence(identity: str):
    assert len(_check(f'locals {{\n  selected = {identity} == "prod" ? 1 : 0\n}}\n')) == 1


def test_hyphenated_environment_identity_is_detected():
    assert len(_check('locals {\n  selected = var.deployment-stage == "prod" ? 1 : 0\n}\n')) == 1


def test_normalizer_on_the_right_side_is_detected():
    assert len(_check('locals {\n  selected = "PROD" == upper(var.environment) ? 1 : 0\n}\n')) == 1


@pytest.mark.parametrize(
    "expression",
    [
        'contains(["prod"], var.environment, "extra")',
        'contains(["prod"])',
    ],
)
def test_malformed_contains_calls_are_left_to_terraform(expression: str):
    assert _check(f"locals {{\n  selected = {expression}\n}}\n") == []


@pytest.mark.parametrize("name", ["image.pkr.hcl", "job.nomad.hcl", "generic.hcl"])
def test_non_terraform_hcl_dialects_are_not_reported(name: str):
    source = 'locals {\n  selected = var.environment == "prod" ? 1 : 0\n}\n'
    assert _check(source, name=name) == []


def test_an_unrelated_validation_block_does_not_hide_application_logic():
    source = """
validation {
  selected = var.environment == "prod" ? 1 : 0
}
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("directory", ["fixture", "fixtures", "testdata"])
def test_fixture_inputs_are_excluded(directory: str):
    source = 'locals {\n  selected = var.environment == "prod" ? 1 : 0\n}\n'
    assert _check(source, name=f"{directory}/main.tf") == []


def test_generated_terraform_is_excluded():
    source = (
        '# Code generated by a provider. DO NOT EDIT.\nlocals {\n  selected = var.environment == "prod" ? 1 : 0\n}\n'
    )
    assert _check(source) == []


def test_ignores_a_commented_out_conditional():
    src = """
resource "google_storage_bucket" "b" {
  # count = var.environment == "prod" ? 1 : 0
  name = "b"
}
"""
    assert _check(src) == []


def test_ignores_a_conditional_inside_a_heredoc():
    src = """
resource "google_monitoring_alert_policy" "a" {
  filter = <<-EOT
    select(.environment == "prod")
  EOT
}
"""
    assert _check(src) == []


def test_a_multiline_value_reports_at_the_attribute_line():
    src = """
locals {
  node_metadata = merge(
    { disable-legacy-endpoints = "true" },
    var.environment == "production" ? { serial-port-logging-enable = "false" } : {},
  )
}
"""
    (diag,) = _check(src)
    assert diag.line == 3


def test_a_noqa_on_the_attribute_line_suppresses_a_multiline_value():
    src = """
locals {
  node_metadata = merge(  # sarj-noqa: SARJ204 — prod-only org policy
    { disable-legacy-endpoints = "true" },
    var.environment == "production" ? { serial-port-logging-enable = "false" } : {},
  )
}
"""
    (diag,) = _check(src)
    assert is_suppressed(src.splitlines(), diag.line, diag.code)


def test_reads_a_conditional_split_across_lines():
    src = """
resource "google_storage_bucket" "b" {
  count = (
    var.environment == "prod"
  ) ? 1 : 0
}
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("expression", "expected_count"),
    [
        ('var.environment == "prod"', 1),
        ('var.environment != "prod"', 1),
        ('contains(["prod"], var.environment)', 1),
        ("contains(local.prod_like, var.environment)", 1),
        ('upper(var.environment) == "PROD"', 1),
        ('"PROD" == upper(var.environment)', 1),
        ('(var.environment) == ("prod")', 1),
        ('var.gcp_project_id == "platform-prod"', 1),
        ('var.project == "analytics"', 0),
        ("var.enable_cache ? 1 : 0", 0),
        ("local.tiers[var.environment]", 0),
        ('"cache-${var.environment}"', 0),
        ('"var.environment == prod"', 0),
        ('"contains([prod], var.environment)"', 0),
        ('true /* var.environment != "prod" */', 0),
        ("var.region", 0),
    ],
)
def test_branch_candidate_spellings_preserve_native_expression_boundaries(expression: str, expected_count: int) -> None:
    source = f"locals {{\n  ordinary = var.region\n  selected = {expression}\n}}\n"

    diagnostics = _check(source)

    assert [(finding.code, finding.line, finding.col) for finding in diagnostics] == (
        [("SARJ204", 3, 3)] if expected_count else []
    )
    assert diagnostics == _check(source)


@pytest.mark.parametrize("value", ['"unterminated', "/* unterminated", "<<EOF\nbody"])
def test_public_environment_expression_helper_preserves_malformed_input_errors(value: str) -> None:
    with pytest.raises(ValueError, match="incomplete HCL value or comment"):
        uses_environment_conditional(value)


@pytest.mark.parametrize("value", ['"unterminated', "/* unterminated", "<<EOF\nbody"])
def test_non_candidate_attributes_preserve_malformed_document_abstention(value: str) -> None:
    assert _check(f"locals {{\n  ordinary = {value}") == []


@pytest.mark.parametrize(
    ("expression", "expected_count"),
    [
        pytest.param(
            '!contains(["acme-dev:dev", "acme-preview:preview"], "${var.project}:${var.environment}")',
            1,
            id="composed-identity-membership",
        ),
        pytest.param('"${var.project}:${var.environment}" == "acme-dev:dev"', 1, id="template-comparison"),
        pytest.param('"acme-dev:dev" != "${var.project}:${var.environment}"', 1, id="flipped-comparison"),
        pytest.param('"${var.project}" == "acme-prod"', 1, id="qualified-identity-literal-evidence"),
        pytest.param('contains(["acme-dev:dev"], ("${var.project}:${var.environment}"))', 1, id="needle-parentheses"),
        pytest.param('contains((["acme-dev:dev"]), "${var.project}:${var.environment}")', 1, id="list-parentheses"),
        pytest.param('contains(["DEV"], upper("${var.environment}"))', 1, id="outer-normalizer"),
        pytest.param('contains(["dev"], "${trimspace(lower(var.environment))}")', 1, id="inner-normalizers"),
        pytest.param('"dev" == lower("${var.environment}")', 1, id="flipped-normalizer"),
        pytest.param('contains(["dev"], "${terraform.workspace}")', 1, id="workspace-template"),
        pytest.param('contains(["dev"], "${local.deployment.environment}")', 1, id="strong-local-identity"),
        pytest.param('"cache-${var.environment}"', 0, id="resource-naming-only"),
        pytest.param('contains(["dev"], "$${var.environment}")', 0, id="escaped-template-marker"),
        pytest.param('contains(["dev"], "$$${var.environment}")', 0, id="escaped-marker-with-prefix"),
        pytest.param('contains(["dev"], "$${var.project}:$${var.environment}")', 0, id="escaped-composed-identity"),
        pytest.param('contains(["dev"], "var.environment")', 0, id="identity-shaped-literal"),
        pytest.param('contains(["enterprise:billing"], "${var.account}:${var.product}")', 0, id="business-identity"),
        pytest.param('"${var.project}" == "analytics"', 0, id="ambiguous-business-comparison"),
        pytest.param('contains(["acme-prod"], "${var.project}")', 1, id="qualified-membership-literal-evidence"),
        pytest.param('contains(var.allowed_environments, "${var.environment}")', 0, id="typed-input-haystack"),
        pytest.param(
            'contains(local.allowed_environments, "${var.environment}")', 0, id="unresolved-template-haystack"
        ),
        pytest.param('contains(["${var.allowed_environment}"], "${var.environment}")', 0, id="interpolated-haystack"),
        pytest.param(
            'contains(["%{ if var.enabled }dev%{ endif }"], "${var.environment}")',
            0,
            id="directive-haystack",
        ),
        pytest.param('contains(["%%{dev}"], "${var.environment}")', 1, id="escaped-directive-literal-haystack"),
        pytest.param('contains(["dev"], "$${literal}:${var.environment}")', 1, id="mixed-escaped-and-real-markers"),
        pytest.param('contains([1, 2], "${var.environment}")', 0, id="non-string-haystack"),
        pytest.param('contains([], "${var.environment}")', 0, id="empty-haystack"),
        pytest.param('contains([""], "${var.environment}")', 0, id="empty-literal-haystack"),
        pytest.param('"${var.environment}" == "${var.allowed_environment}"', 0, id="dynamic-comparison"),
        pytest.param(
            '"${var.environment}" == "%{ if var.enabled }dev%{ endif }"',
            0,
            id="directive-comparison-operand",
        ),
        pytest.param('"${var.environment}" == "%%{dev}"', 1, id="escaped-directive-comparison-literal"),
        pytest.param('contains(["dev"], "${format("%s", var.environment)}")', 0, id="arbitrary-template-function"),
        pytest.param('contains(["dev"], "${jsondecode("${var.environment}")}")', 0, id="nested-template-opaque"),
        pytest.param(
            'contains(["dev"], "%{ if var.enabled }${var.environment}%{ endif }")', 0, id="template-directive-opaque"
        ),
        pytest.param(
            'contains(["dev"], "${var.environment == "prod" ? "dev" : "qa"}")', 0, id="template-branch-opaque"
        ),
        pytest.param('contains(["dev"], "${local.selected_key}")', 0, id="unresolved-alias-opaque"),
        pytest.param('contains(["dev"], "${var.developmental}")', 0, id="identity-substring-near-miss"),
        pytest.param('true /* contains(["dev"], "${var.environment}") */', 0, id="commented-template-branch"),
    ],
)
def test_template_branch_operands_preserve_expression_boundaries(expression: str, expected_count: int) -> None:
    source = f"locals {{\n  selected = {expression}\n}}\n"

    diagnostics = _check(source)

    assert [(finding.code, finding.line, finding.col) for finding in diagnostics] == (
        [("SARJ204", 2, 3)] if expected_count else []
    )
    assert diagnostics == _check(source)


@pytest.mark.parametrize("name", ["setup.tftest.hcl", "fixtures/main.tf", "testdata/main.tf", "values.yaml"])
def test_template_branch_operands_preserve_file_exclusions(name: str) -> None:
    source = 'locals {\n  selected = contains(["dev"], "${var.environment}")\n}\n'
    assert _check(source, name=name) == []


def test_template_branch_operands_preserve_generated_header_exclusion() -> None:
    source = (
        "# Code generated by a provider. DO NOT EDIT.\n"
        'locals {\n  selected = contains(["dev"], "${var.environment}")\n}\n'
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "wrapper",
    [
        'variable "environment" {{\n  validation {{\n    {condition}\n  }}\n}}',
        'resource "test" "r" {{\n  lifecycle {{\n    precondition {{\n      {condition}\n    }}\n  }}\n}}',
        'resource "test" "r" {{\n  lifecycle {{\n    postcondition {{\n      {condition}\n    }}\n  }}\n}}',
        'check "identity" {{\n  assert {{\n    {condition}\n  }}\n}}',
    ],
    ids=["variable-validation", "lifecycle-precondition", "lifecycle-postcondition", "check-assertion"],
)
@pytest.mark.parametrize("identity", ['"${var.environment}"', "var.cloud_build_branch", "var.stack"])
def test_template_branch_operands_preserve_safety_assertion_exemptions(wrapper: str, identity: str) -> None:
    source = wrapper.format(condition=f'condition = contains(["dev"], {identity})')
    assert _check(source) == []


def test_template_branch_operands_report_once_and_keep_attribute_suppression() -> None:
    source = (
        "locals {\n"
        "  selected = (  # sarj-noqa: SARJ204 -- reviewed identity policy\n"
        '    contains(["dev"], "${var.environment}") || "${var.environment}" == "prod"\n'
        "  )\n"
        "}\n"
    )
    (finding,) = _check(source)
    assert (finding.line, finding.col) == (2, 3)
    assert is_suppressed(source.splitlines(), finding.line, finding.code)


@pytest.mark.parametrize(
    ("expression", "expected_count"),
    [
        pytest.param('"${~ var.env}" == "qa"', 1, id="opening-trim-marker"),
        pytest.param('"${var.env ~}" == "qa"', 1, id="closing-trim-marker"),
        pytest.param('"${~ var.env ~}" == "qa"', 1, id="both-trim-markers"),
        pytest.param('contains(["qa"], "${~ trimspace(lower(var.environment)) ~}")', 1, id="trimmed-normalizer"),
        pytest.param('"acme-prod:prod" != "${~ var.project ~}:${~ var.environment ~}"', 1, id="trimmed-composition"),
        pytest.param('contains(["qa"], "$${~ var.env ~}")', 0, id="escaped-trim-markers"),
        pytest.param('contains(["qa"], "$$${~ var.env ~}")', 0, id="escaped-prefixed-trim-markers"),
        pytest.param('"cache-${~ var.environment ~}"', 0, id="trimmed-naming-only"),
        pytest.param('"${~ var.project ~}" == "analytics"', 0, id="trimmed-business-identity"),
        pytest.param('"${~ coalesce(var.env, "qa") ~}" == "qa"', 0, id="trimmed-arbitrary-function"),
        pytest.param('"${~ var.env /* { brace } */ ~}" == "qa"', 0, id="brace-comment-remains-opaque"),
        pytest.param('"${~~ var.env ~~}" == "qa"', 0, id="repeated-trim-markers-remain-invalid"),
    ],
)
def test_template_trim_markers_preserve_expression_boundaries(expression: str, expected_count: int) -> None:
    diagnostics = _check(f"locals {{\n  selected = {expression}\n}}\n")

    assert [(finding.code, finding.line, finding.col) for finding in diagnostics] == (
        [("SARJ204", 2, 3)] if expected_count else []
    )


@pytest.mark.parametrize("label", ["cache", r"\u0063ache"], ids=["literal", "escaped"])
def test_environment_diagnostic_uses_decoded_resource_labels(label: str) -> None:
    source = f'resource "google_storage_bucket" "{label}" {{\n  count = var.environment == "sandbox" ? 1 : 0\n}}\n'

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert 'resource "google_storage_bucket" "cache"' in diagnostics[0].message


def test_escaped_resource_label_does_not_turn_capability_input_into_environment_branch() -> None:
    source = 'resource "google_storage_bucket" "\\u0063ache" {\n  count = var.enable_object_cache ? 1 : 0\n}\n'

    assert _check(source) == []
