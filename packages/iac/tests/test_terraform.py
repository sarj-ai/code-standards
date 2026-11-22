from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from sarj_iac_lint.__main__ import analyze, main
from sarj_iac_lint.guard_contracts import GuardContracts, contracts_for_source
from sarj_iac_lint.module_outputs import unused_module_outputs
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules.canonical_terraform_declarations import CanonicalTerraformDeclarations
from sarj_iac_lint.rules.conditional_resource_presence import ConditionalResourcePresence
from sarj_iac_lint.rules.no_boolean_enable_variable import NoBooleanEnableVariable
from sarj_iac_lint.rules.no_hardcoded_deployment_location import NoHardcodedDeploymentLocation
from sarj_iac_lint.rules.no_terraform_comments import NoTerraformComments
from sarj_iac_lint.rules.no_terraform_guard_blocks import NoTerraformGuardBlocks
from sarj_iac_lint.terraform import terraform_blocks


@pytest.mark.parametrize("extension", [".tf", ".tf.json"])
def test_promoted_declaration_policy_blocks_the_native_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str
) -> None:
    path = tmp_path / f"service{extension}"
    path.write_text(
        json.dumps({"variable": {"region": {"type": "string"}}})
        if extension == ".tf.json"
        else 'variable "region" { type = string }\n'
    )
    arguments = ["check", "--rule", CanonicalTerraformDeclarations.id, str(path)]
    metadata = CanonicalTerraformDeclarations.documentation
    assert metadata is not None
    assert metadata.default_level == DefaultLevel.ERROR
    assert main(arguments) == 1
    assert "SARJ224" in capsys.readouterr().out


def test_json_expression_objects_do_not_inherit_terraform_block_keywords() -> None:
    source = json.dumps(
        {
            "resource": {
                "terraform_data": {
                    "this": {
                        "input": {
                            "backend": {"service": "api"},
                            "depends_on": "ordinary application data",
                            "dynamic": {"mode": "strict"},
                            "//": "ordinary expression-object member",
                        }
                    }
                }
            }
        }
    )

    blocks = terraform_blocks(Path("main.tf.json"), source)
    assert len(blocks) == 1
    assert NoTerraformGuardBlocks().check(Path("main.tf.json"), source) == []
    assert NoTerraformComments().check(Path("main.tf.json"), source) == []


@pytest.mark.parametrize("extension", [".tf", ".tf.json"])
@pytest.mark.parametrize("record_type", ["A", "TXT", "unknown"])
def test_dns_payload_meaning_depends_on_record_type(extension: str, record_type: str) -> None:
    attributes = {"type": record_type, "rrdatas": ["10.42.0.2"]}
    source = (
        json.dumps({"resource": {"google_dns_record_set": {"this": attributes}}})
        if extension == ".tf.json"
        else f'resource "google_dns_record_set" "this" {{\n type = "{record_type}"\n rrdatas = ["10.42.0.2"]\n}}\n'
    )

    assert len(NoHardcodedDeploymentLocation().check(Path(f"main{extension}"), source)) == (record_type == "A")


def test_module_owned_resource_names_and_protocol_hosts_remain_constants() -> None:
    source = """resource "google_compute_address" "query" {
  name = "query-internal-ip"
  address = var.query_ip
}
resource "google_dns_record_set" "metadata" {
  type = "CNAME"
  rrdatas = ["metadata.google.internal."]
}
"""

    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("extension", [".tf", ".tf.json"])
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('cidrsubnet("2001:db8::/32", 8, 1)', 1),
        ("cidrhost(var.subnet_cidr, 2)", 0),
        ('format("https://service.europe-west3.example.invalid/%s", var.path)', 1),
        ('"https://accounts.google.com"', 0),
    ],
)
def test_contextual_endpoint_and_cidr_expression_arguments(extension: str, expression: str, expected: int) -> None:
    source = (
        json.dumps({"resource": {"google_compute_address": {"this": {"address": "${" + expression + "}"}}}})
        if extension == ".tf.json"
        else f'resource "google_compute_address" "this" {{\n address = {expression}\n}}\n'
    )

    assert len(NoHardcodedDeploymentLocation().check(Path(f"main{extension}"), source)) == expected


@pytest.mark.parametrize("array", [False, True])
def test_json_variable_validation_covers_repeated_cross_variable_guards(*, array: bool) -> None:
    body = {
        "type": "bool",
        "validation": [
            {"condition": "${!var.enabled || var.ready}", "error_message": "Readiness is required."},
            {"condition": "${var.enabled == var.other}", "error_message": "Modes must agree."},
        ],
    }
    variables = [{"enabled": body}] if array else {"enabled": body}
    source = json.dumps({"variable": variables}, indent=2)

    findings = NoTerraformGuardBlocks().check(Path("variables.tf.json"), source)

    assert len(findings) == 2
    assert len({(item.line, item.col) for item in findings}) == 2
    assert all(item.code == "SARJ222" for item in findings)


def test_json_provider_condition_object_is_not_variable_validation() -> None:
    source = json.dumps(
        {
            "resource": {
                "example_service": {
                    "app": {
                        "validation": {"condition": True},
                        "lifecycle": {"prevent_destroy": True},
                    }
                }
            }
        }
    )

    assert NoTerraformGuardBlocks().check(Path("main.tf.json"), source) == []


def test_json_action_does_not_hide_a_variable_validation() -> None:
    source = json.dumps(
        {
            "action": {"aws_lambda_invoke": {"refresh": {"config": {"function_name": "${var.function_name}"}}}},
            "variable": {
                "function_name": {
                    "type": "string",
                    "validation": {
                        "condition": "${length(var.function_name) > 0}",
                        "error_message": "A target is required.",
                    },
                }
            },
        }
    )

    blocks = terraform_blocks(Path("main.tf.json"), source)

    assert blocks[0].labels == ("aws_lambda_invoke", "refresh")
    assert len(NoTerraformGuardBlocks().check(Path("main.tf.json"), source)) == 1


def test_json_guard_precedence_reports_ban_once(tmp_path: Path) -> None:
    path = tmp_path / "variables.tf.json"
    path.write_text(
        json.dumps(
            {
                "variable": {
                    "enabled": {
                        "type": "bool",
                        "nullable": False,
                        "validation": [{"condition": "${var.enabled != null}", "error_message": "Required."}],
                    }
                }
            }
        )
    )

    findings = analyze(["no-terraform-guard-blocks", "no-redundant-variable-validation"], [path])

    assert [item.code for item in findings] == ["SARJ222"]


def test_existing_validation_contract_reports_its_migration_constraint(tmp_path: Path) -> None:
    path = tmp_path / "variables.tf"
    source = 'variable "ready" {\n type = bool\n validation {\n condition = var.ready\n error_message = "Routing ownership must be ready."\n }\n}\n'
    path.write_text(source)
    contracts = GuardContracts(tmp_path, frozenset(contracts_for_source("variables.tf", source)))

    retained = NoTerraformGuardBlocks(contracts).check(path, source)
    changed = NoTerraformGuardBlocks(contracts).check(path, source.replace("var.ready", "!var.ready"))

    assert len(retained) == 1
    assert retained[0].severity.value == "warning"
    assert "Migration is constrained" in retained[0].message
    assert not retained[0].baselineable
    assert [item.severity.value for item in changed] == ["error"]


@pytest.mark.parametrize(
    "payload",
    [
        '{"variable":{"x":{}},"variable":{"y":{}}}',
        '{"variable":{"x":{"default":NaN}}}',
        '{"variable":{"x":',
        '{"variable":{"x":{"validation":5}}}',
    ],
)
def test_malformed_json_cannot_qualify(payload: str, tmp_path: Path) -> None:
    path = tmp_path / "variables.tf.json"
    path.write_text(payload)

    with pytest.raises(ValueError, match=r"Terraform|JSON|Expecting"):
        analyze(["no-terraform-guard-blocks"], [path])


@pytest.mark.parametrize("extension", ["tf", "tf.json"])
def test_invalid_utf8_cannot_qualify_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str
) -> None:
    path = tmp_path / f"main.{extension}"
    path.write_bytes(b'{"locals":{"text":"\xff"}}' if extension == "tf.json" else b'locals { text = "\xff" }\n')

    assert main(["check", "--rule", "no-terraform-guard-blocks", str(path)]) == 2
    assert "decode" in capsys.readouterr().err


def test_malformed_sibling_cannot_qualify_a_partial_module(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "google_storage_bucket" "app" { location = var.region }\n')
    (tmp_path / "variables.tf").write_text('variable "region" {\n')

    with pytest.raises(ValueError, match="Terraform"):
        analyze(["no-hardcoded-deployment-location"], [path])


@pytest.mark.parametrize("extension", ["tf", "tf.json"])
def test_deployment_alias_is_resolved_across_module_files(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"main.{extension}"
    if extension == "tf":
        path.write_text('resource "google_storage_bucket" "app" { location = local.location }\n')
        (tmp_path / "locals.tf").write_text('locals { location = "us-central1" }\n')
    else:
        path.write_text(json.dumps({"resource": {"google_storage_bucket": {"app": {"location": "${local.location}"}}}}))
        (tmp_path / "locals.tf.json").write_text(json.dumps({"locals": {"location": "us-central1"}}))

    assert len(analyze(["no-hardcoded-deployment-location"], [path])) == 1


@pytest.mark.parametrize(
    "value",
    [
        '"api.${var.environment}.example.com."',
        'format("api.%s.example.com.", var.environment)',
        '"http://10.20.0.4/${var.path}"',
    ],
)
def test_contextual_deployment_templates_are_checked(value: str) -> None:
    source = f'resource "google_dns_record_set" "app" {{ name = {value} }}\n'

    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'resource "google_dns_record_set" "app" { name = "api.${var.domain}." }\n',
        'resource "google_storage_bucket" "app" { location = "global" }\n',
        'module "app" {\n source = "registry.example.com/team/module/provider"\n domain = "app.example.com"\n}\n',
        'terraform {\n backend "gcs" { bucket = "deployment-state" }\n}\nresource "google_storage_bucket" "app" { location = "us-central1" }\n',
        'resource "google_storage_bucket" "app" {\n description = "Call https://api.example.com or 10.0.0.0/8"\n}\n',
    ],
)
def test_deployment_choices_and_non_deployment_literals_remain_valid(source: str) -> None:
    assert NoHardcodedDeploymentLocation().check(Path("main.tf"), source) == []


@pytest.mark.parametrize("description", ["", 'description = "Intentional default for the supported deployment."'])
def test_reusable_deployment_defaults_require_documented_intent(description: str) -> None:
    source = f'variable "region" {{\n type = string\n default = "us-central1"\n {description}\n}}\nresource "google_storage_bucket" "app" {{ location = var.region }}\n'

    assert len(NoHardcodedDeploymentLocation().check(Path("main.tf"), source)) == (0 if description else 1)


def test_json_literal_payloads_and_real_expression_comments_are_distinct() -> None:
    source = json.dumps(
        {
            "//": "JSON provenance",
            "variable": {
                "payload": {
                    "default": "${1 /* literal default data */ + 2}",
                }
            },
            "locals": {"script": "# shell\nhttps://example.com/*literal*/", "value": "${1 /* HCL */ + 2}"},
        }
    )

    findings = NoTerraformComments().check(Path("main.tf.json"), source)

    assert len(findings) == 1
    assert "HCL comment" in findings[0].message


def test_json_comment_properties_are_data_inside_expressions() -> None:
    source = '{"locals":{"payload":{"//":"${module.child.used}"}},"variable":{"payload":{"default":{"//":"${1 /* literal */ + 2}"}}}}'
    local, variable = terraform_blocks(Path("main.tf.json"), source)

    payload = local.attribute("payload")
    assert payload is not None
    assert '"//"' in payload.value
    assert "module.child.used" in payload.value
    assert not variable.blocks
    assert NoTerraformComments().check(Path("main.tf.json"), source) == []


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ('{"locals":{"payload":{"//":"${1 /* HCL */ + 2}"}}}', 1),
        ('{"locals":{"payload":{"nested":{"//":"${1 /* HCL */ + 2}"}}}}', 1),
        ('{"//":"${1 /* ignored block-body metadata */ + 2}","locals":{"value":1}}', 0),
        ('{"variable":{"payload":{"default":{"//":"${1 /* literal default */ + 2}"}}}}', 0),
        ('{"locals":{"payload":{"//":"https://example.com/*data*/"}}}', 0),
    ],
)
def test_json_comment_keys_do_not_hide_executable_template_comments(source: str, count: int) -> None:
    assert len(NoTerraformComments().check(Path("main.tf.json"), source)) == count


def test_json_numbers_keep_arbitrary_precision_and_exponents() -> None:
    source = '{"locals":{"large":1234567890123456789012345678901234567890,"fraction":0.123456789012345678901234567890,"exponent":1e999}}'
    (block,) = terraform_blocks(Path("main.tf.json"), source)

    assert [attribute.value for attribute in block.attributes] == [
        "1234567890123456789012345678901234567890",
        "0.123456789012345678901234567890",
        "1e999",
    ]


def test_json_temporary_flag_expiry_uses_injected_clock() -> None:
    source = json.dumps(
        {
            "variable": {
                "enabled": {
                    "type": "bool",
                    "default": True,
                    "description": "Retire by: 2026-11-21\nRemove when: Both deployments pass rollback qualification; review count addresses before removal.",
                }
            }
        }
    )
    path = Path("variables.tf.json")

    assert NoBooleanEnableVariable(today=date(2026, 11, 21)).check(path, source) == []
    expired = NoBooleanEnableVariable(today=date(2026, 11, 22)).check(path, source)
    assert len(expired) == 1
    assert "rollback readiness" in expired[0].message


def test_constant_module_gate_requires_preserving_instance_addresses() -> None:
    source = 'module "app" {\n source = "./app"\n count = true ? 1 : 0\n}\n'

    findings = ConditionalResourcePresence().check(Path("main.tf"), source)

    assert len(findings) == 1
    assert "Boolean-literal" in findings[0].message
    assert "Keep the count/for_each attribute" in findings[0].message


def test_unknown_external_output_usage_is_not_declared_unused() -> None:
    sources = {
        "main.tf": 'module "child" { source = "./child" }',
        "child/outputs.tf": 'output "external" { value = true }',
    }

    assert unused_module_outputs(sources) == ()
    assert len(unused_module_outputs(sources, internal_modules=("child",))) == 1
    assert unused_module_outputs(sources, internal_modules=("child",), external_outputs=(("child", "external"),)) == ()


def test_json_block_locations_preserve_minified_and_multiline_declarations() -> None:
    source = json.dumps({"variable": {"first": {}, "second": {}}})
    first, second = terraform_blocks(Path("variables.tf.json"), source)

    assert first.labels == ("first",)
    assert second.labels == ("second",)
    assert first.col < second.col


@pytest.mark.parametrize("path", ["variables.tf", "outputs.tf", "variables.tf.json", "outputs.tf.json"])
def test_canonical_interface_files_are_not_required_when_empty(path: str) -> None:
    source = "{}" if path.endswith(".json") else ""

    assert CanonicalTerraformDeclarations().check(Path(path), source) == []


@pytest.mark.parametrize(
    ("indent", "complex_guard"),
    [
        pytest.param(None, False, id="compact-simple-guard"),
        pytest.param(None, True, id="compact-complex-guard"),
        pytest.param(2, False, id="indented-simple-guard"),
        pytest.param(2, True, id="indented-complex-guard"),
    ],
)
def test_guard_precedence_preserves_unrelated_json_attributes(
    tmp_path: Path, indent: int | None, *, complex_guard: bool
) -> None:
    condition = " && ".join(['var.x != ""'] * 9) if complex_guard else 'var.x != ""'
    payload = {
        "variable": {
            "a": {"type": "number"},
            "x": {
                "type": "string",
                "validation": [{"condition": "${" + condition + "}", "error_message": "Required."}],
            },
        },
        "locals": {"large": "${" + " + ".join(["var.a"] * 15) + "}"},
    }
    path = tmp_path / "main.tf.json"
    path.write_text(json.dumps(payload, indent=indent))

    standalone = analyze(["expression-complexity"], [path])
    combined = analyze(["no-terraform-guard-blocks", "expression-complexity"], [path])

    assert len(standalone) == (2 if complex_guard else 1)
    assert [item.code for item in combined] == ["SARJ222", "SARJ217"]
    [outside] = [item for item in standalone if item.message.startswith("Terraform statement")]
    assert combined[1] == outside


@pytest.mark.parametrize(
    ("source", "comments"),
    [
        pytest.param('variable /* legal */ "name" { type = string }', ("/* legal */",), id="label-comment"),
        pytest.param('locals { url = "https://host/#data" }', (), id="url-data"),
        pytest.param('locals { value = "${1 /* metadata */ + 2}" }', ("/* metadata */",), id="template-comment"),
        pytest.param("locals { value = <<EOT\n# shell data\nEOT\n}", (), id="heredoc-data"),
    ],
)
def test_shared_comment_inventory_is_lexical(source: str, comments: tuple[str, ...]) -> None:
    from sarj_iac_lint.terraform import comment_texts  # ruff: ignore[import-outside-top-level] -- exercise the public lexical metadata proof directly.

    assert comment_texts(source) == comments
