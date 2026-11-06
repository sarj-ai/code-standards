from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze, baseline_counts, main
from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rule_base import AutofixPolicy, DefaultLevel
from sarj_iac_lint.rules.no_hardcoded_deployment_location import NoHardcodedDeploymentLocation


@pytest.mark.parametrize(
    "expression",
    [
        '"us-central1"',
        '("us-central1")',
        '"EU"',
        'upper("us-central1")',
        'lower("US-CENTRAL1")',
        'trimspace(" us-central1 ")',
        'join("", ["us-", "central1"])',
        'var.use_primary ? "us-central1" : var.secondary_region',
        'coalesce(var.region, "us-central1")',
        'try(var.settings.region, "us-central1")',
    ],
)
def test_reports_provable_literal_placement(expression: str) -> None:
    source = f'resource "google_storage_bucket" "this" {{\n  location = {expression}\n}}\n'
    findings = NoHardcodedDeploymentLocation().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (2, 3)
    assert findings[0].severity is DefaultLevel.ERROR


@pytest.mark.parametrize(
    "expression",
    ['["us-central1-a", "us-central1-b"]', '[var.zone, "us-central1-b"]', 'toset(["us-central1-a"])'],
)
def test_checks_each_literal_in_list_valued_placement(expression: str) -> None:
    source = f'resource "google_container_cluster" "this" {{\n  node_locations = {expression}\n}}\n'

    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "var.region",
        "upper(var.region)",
        "data.google_client_config.current.region",
        "module.configuration.region",
        "each.value.region",
        "local.unknown",
        "null",
        '""',
        '"global"',
        '"GLOBAL"',
        'trimspace(" global ")',
        '"${var.region}-a"',
        'format("%s", var.region)',
        "coalesce(var.region, var.fallback_region)",
        "try(var.settings.region, var.fallback_region)",
        'join("-", [var.prefix, var.region])',
        "var.primary ? var.primary_region : var.secondary_region",
    ],
)
def test_preserves_inputs_and_provider_global_selectors(expression: str) -> None:
    source = f'resource "google_storage_bucket" "this" {{\n  location = {expression}\n}}\n'

    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    ("header", "attribute", "value"),
    [
        ('provider "google"', "region", '"us-central1"'),
        ('provider "aws"', "region", '"us-east-1"'),
        ('provider "oci"', "region", '"us-ashburn-1"'),
        ('resource "cloudflare_r2_bucket" "this"', "location", '"weur"'),
        ('resource "hcloud_server" "this"', "location", '"hel1"'),
        ('resource "google_compute_disk" "this"', "zone", '"us-central1-a"'),
        ('resource "aws_instance" "this"', "availability_zone", '"us-east-1a"'),
        ('resource "aws_rds_cluster" "this"', "availability_zones", '["us-east-1a", "us-east-1b"]'),
        ('resource "azurerm_resource_group" "this"', "location", '"West Europe"'),
        ('resource "google_firestore_database" "this"', "location_id", '"eur3"'),
        ('resource "google_container_cluster" "this"', "node_locations", '["us-central1-a"]'),
    ],
)
def test_checks_recognized_cloud_placement_arguments(header: str, attribute: str, value: str) -> None:
    source = f"{header} {{\n  {attribute} = {value}\n}}\n"

    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'resource "google_secret_manager_secret" "this" {\n replication { user_managed { replicas { location = "us-central1" } } }\n}\n',
        'resource "google_secret_manager_secret" "this" {\n replication { user_managed { dynamic "replicas" { for_each = var.replicas\n content { location = "us-central1" } } } }\n}\n',
        'resource "google_bigtable_instance" "this" { cluster { zone = "us-central1-a" } }\n',
        'resource "google_dataproc_cluster" "this" { cluster_config { gce_cluster_config { zone = "us-central1-a" } } }\n',
        'resource "google_storage_bucket" "this" { custom_placement_config { data_locations = ["us-central1", "us-east1"] } }\n',
        'resource "google_sql_database_instance" "this" { settings { location_preference { zone = "us-central1-a" } } }\n',
        'resource "aws_secretsmanager_secret" "this" { replica { region = "us-east-1" } }\n',
        'resource "aws_dynamodb_table" "this" { replica { region_name = "us-east-1" } }\n',
        'resource "azurerm_cosmosdb_account" "this" { geo_location { location = "West Europe" } }\n',
        'resource "azurerm_container_registry" "this" { georeplications { location = "West Europe" } }\n',
    ],
)
def test_checks_schema_scoped_nested_placement(source: str) -> None:
    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == 1


def test_follows_closed_local_aliases_and_static_joins() -> None:
    source = (
        'locals {\n primary = local.selected\n selected = join("", ["us-", "central1"])\n}\n'
        'resource "google_storage_bucket" "this" { location = local.primary }\n'
    )
    findings = NoHardcodedDeploymentLocation().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert findings[0].line == 5


def test_follows_a_local_placement_collection() -> None:
    source = (
        'locals { places = toset(["us-central1-a"]) }\n'
        'resource "google_container_cluster" "this" { node_locations = local.places }\n'
    )

    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize(
    "locals_source",
    [
        "locals { primary = local.secondary\n secondary = local.primary }",
        "locals { primary = upper(local.primary) }",
        "locals { primary = var.region }",
    ],
)
def test_cyclic_or_input_aliases_are_not_evaluated_as_constants(locals_source: str) -> None:
    source = locals_source + '\nresource "google_storage_bucket" "this" { location = local.primary }\n'

    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        'variable "region" { type = string\n default = "us-central1" }\n',
        'locals { region = "us-central1" }\n',
        'module "service" { source = "./service"\n region = "us-central1" }\n',
        'resource "kubernetes_config_map_v1" "this" { data = { region = "business-area" } }\n',
        'resource "google_storage_bucket" "this" { labels = { location = "business-area" } }\n',
        'resource "aws_cloudfront_distribution" "this" { restrictions { geo_restriction { locations = ["US"] } } }\n',
        'resource "google_storage_bucket" "this" { lifecycle { prevent_destroy = true } }\n',
        'provider "custom" { region = "business-area" }\n',
        'resource "aws_codebuild_project" "this" { source { location = "https://example.invalid/repository.git" } }\n',
        'resource "aws_route53_record" "this" { zone_id = "Z012345" }\n',
        'resource "cloudflare_zone" "this" { zone = "example.invalid" }\n',
        'resource "hcloud_zone_rrset" "this" { zone = "example.invalid" }\n',
        'data "hcloud_zone_rrset" "this" { zone = "12345" }\n',
        'locals { text = "location = us-central1" }\n',
    ],
)
def test_preserves_configuration_owners_and_nonplacement_constants(source: str) -> None:
    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("path", ["fixtures/main.tf", "generated/main.tf", "terraform.tfvars", "main.tf.json", "x.hcl"])
def test_excludes_fixture_and_input_value_files(path: str) -> None:
    source = 'resource "google_storage_bucket" "this" { location = "us-central1" }\n'

    assert NoHardcodedDeploymentLocation().check(Path(path), source) == []


@pytest.mark.parametrize(
    "source",
    [
        '# resource "google_storage_bucket" "this" { location = "us-central1" }\n',
        '# Generated; do not edit\nresource "google_storage_bucket" "this" { location = "us-central1" }\n',
        'locals { text = <<DOC\nlocation = "us-central1"\nDOC\n}\n',
        'resource "google_storage_bucket" "this" { location = "us-central1"\n',
    ],
)
def test_preserves_opaque_data_and_rejects_malformed_hcl(source: str) -> None:
    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


def test_documented_examples_and_explicit_error_policy() -> None:
    spec = NoHardcodedDeploymentLocation.native_spec()
    assert spec is not None
    assert spec.default_level is DefaultLevel.ERROR
    assert spec.autofix is AutofixPolicy.NONE
    verify_native_rule(NoHardcodedDeploymentLocation, analyze)
    source = 'resource "google_storage_bucket" "this" { location = "us-central1" }\n'
    assert fix_source(Path("main.tf"), source, rule_ids=["no-hardcoded-deployment-location"]) == source


def test_error_is_blocking_and_uses_existing_baseline_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "google_storage_bucket" "this" { location = "us-central1" }\n')

    assert main(["check", "--rule", "no-hardcoded-deployment-location", str(path)]) == 1
    assert "SARJ219" in capsys.readouterr().out
    findings = analyze(["no-hardcoded-deployment-location"], [path])
    assert list(baseline_counts(findings).values()) == [{"SARJ219": 1}]


def test_placement_error_owns_overlapping_literal_guidance(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "google_storage_bucket" "a" { location = "us-central1" }\n'
        'resource "google_storage_bucket" "b" { location = "us-central1" }\n'
    )

    assert [
        finding.code
        for finding in analyze(["no-hardcoded-deployment-location", "no-duplicate-deployment-literal"], [path])
    ] == ["SARJ219", "SARJ219"]
    assert [finding.code for finding in analyze(["no-duplicate-deployment-literal"], [path])] == ["SARJ218"]
    assert [finding.code for finding in analyze(["no-hardcoded-deployment-location"], [path])] == ["SARJ219", "SARJ219"]


def test_placement_error_preserves_unrelated_scope_guidance(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "google_storage_bucket" "a" {\n project = "example-project"\n location = "us-central1"\n}\n'
        'resource "google_storage_bucket" "b" {\n project = "example-project"\n location = "us-central1"\n}\n'
    )

    findings = analyze(["no-hardcoded-deployment-location", "no-duplicate-deployment-literal"], [path])

    assert sorted(finding.code for finding in findings) == ["SARJ218", "SARJ219", "SARJ219"]
    assert next(finding for finding in findings if finding.code == "SARJ218").message.startswith("project repeats")


def test_physical_crlf_location_and_unicode_are_preserved() -> None:
    source = (
        'locals { label = "雪" }\r\nresource "google_storage_bucket" "this" {\r\n  location = "us-central1"\r\n}\r\n'
    )
    findings = NoHardcodedDeploymentLocation().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (3, 3)


@pytest.mark.parametrize(("code", "count"), [("SARJ219", 0), ("SARJ218", 1)])
def test_only_the_exact_suppression_code_applies(tmp_path: Path, code: str, count: int) -> None:
    path = tmp_path / "main.tf"
    path.write_text(
        'resource "google_storage_bucket" "this" {\n'
        f' location = "us-central1" # sarj-noqa: {code} -- required external contract\n'
        "}\n"
    )

    assert len(analyze(["no-hardcoded-deployment-location"], [path])) == count
