from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.no_duplicate_deployment_literal import NoDuplicateDeploymentLiteral
from sarj_iac_lint.rules.no_environment_conditional import NoEnvironmentConditional


@pytest.mark.parametrize(
    ("source", "count"),
    [
        pytest.param(
            'resource "google_storage_bucket" "a" { project = "example-project" }\n'
            'resource "google_cloud_run_v2_job" "b" { project = "example-project" }\n',
            1,
            id="shared-project",
        ),
        pytest.param(
            'resource "google_organization_iam_member" "a" { org_id = "123456789012" }\n'
            'resource "google_organization_iam_custom_role" "b" { org_id = "123456789012" }\n'
            'data "google_organization" "c" { org_id = "123456789012" }\n',
            1,
            id="one-finding-for-three-uses",
        ),
        pytest.param(
            'resource "aws_instance" "a" { availability_zone = "us-east-1a" }\n'
            'resource "aws_subnet" "b" { availability_zone = "us-east-1a" }\n',
            1,
            id="aws-zone",
        ),
        pytest.param(
            'resource "azurerm_resource_group" "a" { location = "westeurope" }\n'
            'resource "azurerm_storage_account" "b" { location = "westeurope" }\n',
            1,
            id="azure-location",
        ),
        pytest.param(
            'data "google_project" "a" { project_id = "example-project" }\n'
            'data "google_project" "b" { project_id = "example-project" }\n',
            1,
            id="data-source-project-id",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = (("example-project")) }\n'
            'resource "google_storage_bucket" "b" { project = "example-\\u0070roject" }\n',
            1,
            id="grouping-and-literal-escape",
        ),
        pytest.param(
            'resource "google_cloud_run_v2_job" "a" { project = "example-project"\nlocation = "us-central1" }\n'
            'resource "google_cloud_run_v2_job" "b" { project = "example-project"\nlocation = "us-central1" }\n',
            2,
            id="independent-value-groups",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { provider = google.security\nproject = "example-project" }\n'
            'resource "google_storage_bucket" "b" { provider = google.security\nproject = "example-project" }\n',
            1,
            id="same-explicit-provider",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = "example-account" }\n'
            'data "cloudflare_r2_bucket" "b" { account_id = "example-account" }\n',
            1,
            id="cloudflare-resource-and-data-account",
        ),
        pytest.param(
            'data "cloudflare_zone" "a" { zone_id = "example-zone" }\n'
            'resource "cloudflare_dns_record" "b" { zone_id = "example-zone" }\n',
            1,
            id="cloudflare-zone",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { provider = cloudflare.selected\naccount_id = "example-account" }\n'
            'resource "cloudflare_r2_bucket" "b" { provider = cloudflare.selected\naccount_id = "example-account" }\n',
            1,
            id="cloudflare-same-explicit-provider",
        ),
    ],
)
def test_repeated_deployment_assignments(source: str, count: int) -> None:
    findings = NoDuplicateDeploymentLiteral().check(Path("main.tf"), source)
    assert len(findings) == count
    assert all(finding.severity is DefaultLevel.WARNING for finding in findings)
    assert all("example-project" not in finding.message for finding in findings)
    assert len({(finding.line, finding.col) for finding in findings}) == count
    assert findings == NoDuplicateDeploymentLiteral().check(Path("main.tf"), source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('resource "google_storage_bucket" "a" { project = "example-project" }', id="one-use"),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = var.project_id }\n'
            'resource "google_storage_bucket" "b" { project = var.project_id }',
            id="shared-input",
        ),
        pytest.param(
            'locals { project = "example-project" }\n'
            'resource "google_storage_bucket" "a" { project = local.project }\n'
            'resource "google_storage_bucket" "b" { project = local.project }',
            id="shared-local",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = data.google_project.selected.project_id }\n'
            'resource "google_storage_bucket" "b" { project = data.google_project.selected.project_id }',
            id="resource-reference",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = "${var.project_id}" }\n'
            'resource "google_storage_bucket" "b" { project = "${var.project_id}" }',
            id="templates-are-not-static-values",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = "example-a" }\n'
            'resource "google_storage_bucket" "b" { project = "example-b" }',
            id="different-values",
        ),
        pytest.param(
            'provider "google" { project = "example-project" }\n'
            'provider "google" { alias = "security"\nproject = "example-project" }',
            id="provider-composition-boundary",
        ),
        pytest.param(
            'module "a" { source = "./child"\nproject = "example-project" }\n'
            'module "b" { source = "./other"\nproject = "example-project" }',
            id="module-input-intent-is-unknown",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { provider = google.primary\nproject = "example-project" }\n'
            'resource "google_storage_bucket" "b" { provider = google.security\nproject = "example-project" }',
            id="different-provider-bindings",
        ),
        pytest.param(
            'resource "google_compute_global_address" "a" { location = "global" }\n'
            'resource "google_compute_global_address" "b" { location = "global" }',
            id="global-provider-sentinel",
        ),
        pytest.param(
            'locals { snapshot = { a = { parent = "organizations/123456789012"\niam_hash = "fixed-hash" }\n'
            'b = { parent = "organizations/123456789012"\niam_hash = "fixed-hash" } } }',
            id="immutable-evidence-data",
        ),
        pytest.param(
            'resource "google_cloud_run_v2_job" "a" { template { env { name = "PROJECT"\nvalue = "example-project" } } }\n'
            'resource "google_cloud_run_v2_job" "b" { template { env { name = "PROJECT"\nvalue = "example-project" } } }',
            id="embedded-contract-values",
        ),
        pytest.param(
            'resource "random_pet" "a" { project = "example-project" }\n'
            'resource "random_pet" "b" { project = "example-project" }',
            id="unknown-provider-attribute",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = "" }\n'
            'resource "google_storage_bucket" "b" { project = "" }',
            id="empty-values",
        ),
        pytest.param(
            'resource "google_storage_bucket" "a" { project = "example-project" }\n'
            'resource "google_storage_bucket" "b" { project = "example-project"',
            id="malformed-native-input",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = "example-account" }\n',
            id="cloudflare-one-account-use",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = var.account_id }\n'
            'data "cloudflare_r2_bucket" "b" { account_id = var.account_id }',
            id="cloudflare-shared-input",
        ),
        pytest.param(
            'locals { account_id = "example-account" }\n'
            'resource "cloudflare_r2_bucket" "a" { account_id = local.account_id }\n'
            'resource "cloudflare_r2_bucket" "b" { account_id = local.account_id }',
            id="cloudflare-shared-fixed-value",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = data.cloudflare_account.selected.id }\n'
            'resource "cloudflare_r2_bucket" "b" { account_id = data.cloudflare_account.selected.id }',
            id="cloudflare-account-reference",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = "example-a" }\n'
            'resource "cloudflare_r2_bucket" "b" { account_id = "example-b" }',
            id="cloudflare-independent-accounts",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { account_id = "example-scope" }\n'
            'resource "cloudflare_dns_record" "b" { zone_id = "example-scope" }',
            id="cloudflare-independent-scope-kinds",
        ),
        pytest.param(
            'resource "cloudflare_r2_bucket" "a" { provider = cloudflare.primary\naccount_id = "example-account" }\n'
            'resource "cloudflare_r2_bucket" "b" { provider = cloudflare.recovery\naccount_id = "example-account" }',
            id="cloudflare-independent-provider-bindings",
        ),
        pytest.param(
            'resource "cloudflare_dns_record" "a" { content = "example-account" }\n'
            'resource "cloudflare_dns_record" "b" { content = "example-account" }',
            id="cloudflare-record-payload-is-not-scope",
        ),
        pytest.param(
            'resource "cloudflare_ruleset" "a" { rules { action_parameters { account_id = "example-account" } } }\n'
            'resource "cloudflare_ruleset" "b" { rules { action_parameters { account_id = "example-account" } } }',
            id="cloudflare-nested-policy-is-not-scope",
        ),
        pytest.param(
            'locals { expected = { a = { account_id = "example-account" }\nb = { account_id = "example-account" } } }',
            id="cloudflare-security-expectations-remain-policy",
        ),
    ],
)
def test_valid_boundaries(source: str) -> None:
    assert NoDuplicateDeploymentLiteral().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("path", ["values.tfvars", "main.tf.json", "fixtures/main.tf", "generated/main.tf"])
def test_data_and_fixture_inputs_are_excluded(path: str) -> None:
    source = 'resource "google_storage_bucket" "a" { project = "example-project" }\n' * 2
    assert NoDuplicateDeploymentLiteral().check(Path(path), source) == []


def test_comments_heredocs_generated_headers_and_exact_suppression(tmp_path: Path) -> None:
    source = 'resource "google_storage_bucket" "a" { project = "example-project" }\n'
    source += 'resource "google_storage_bucket" "b" {\n  project = "example-project"\n}\n'
    rule = NoDuplicateDeploymentLiteral()
    finding = rule.check(Path("main.tf"), source)[0]
    assert (finding.line, finding.col, finding.code) == (3, 3, "SARJ218")
    assert rule.check(Path("main.tf"), "# Generated; do not edit.\n" + source) == []
    assert rule.check(Path("main.tf"), "# " + source.replace("\n", "\n# ")) == []
    assert rule.check(Path("main.tf"), "locals { script = <<EOT\n" + source + "EOT\n}") == []
    path = tmp_path / "main.tf"
    path.write_text(
        source.replace('  project = "example-project"', '  project = "example-project" # sarj-noqa: SARJ218')
    )
    assert analyze([rule.id], [path]) == []
    path.write_text(
        source.replace('  project = "example-project"', '  project = "example-project" # sarj-noqa: SARJ217')
    )
    assert len(analyze([rule.id], [path])) == 1


def test_no_cross_file_state_or_overlap_with_environment_conditions(tmp_path: Path) -> None:
    rule = NoDuplicateDeploymentLiteral()
    source = 'resource "google_storage_bucket" "a" { project = "example-project" }\n'
    assert rule.check(Path("first.tf"), source) == []
    assert rule.check(Path("second.tf"), source) == []
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "google_storage_bucket" "a" { project = var.environment == "production" ? "example-a" : "example-b" }\n'
    )
    findings = analyze([rule.id, "no-environment-conditional"], [path])
    assert [finding.code for finding in findings] == [NoEnvironmentConditional.code]


def test_documented_examples() -> None:
    verify_native_rule(NoDuplicateDeploymentLiteral, analyze)
