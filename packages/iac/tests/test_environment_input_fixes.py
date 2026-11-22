from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rules.no_dead_environment_input import NoDeadEnvironmentInput, remove_stale_assignments


_ROOT = Path("/selected")
_VARIABLES = 'variable "live" {\n type = bool\n default = true\n}\n'


def _sources(source: str, name: str = "terraform.tfvars") -> dict[Path, str]:
    return {_ROOT / "variables.tf": _VARIABLES, _ROOT / name: source}


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_hcl_preserves_retained_values_comments_and_formatting_and_converges(newline: str) -> None:
    source = "# deployment inputs\nlive = false\nretired = true\n# retained explanation\n"
    sources = _sources(source.replace("\n", newline))
    path = _ROOT / "terraform.tfvars"
    changes = remove_stale_assignments(sources, selected=(path,))
    assert changes[path] == "# deployment inputs\nlive = false\n# retained explanation\n".replace("\n", newline)
    fixed = {**sources, **changes}
    assert remove_stale_assignments(fixed, selected=(path,)) == {}
    assert (
        NoDeadEnvironmentInput.check_project(_ROOT, {PurePosixPath(p.relative_to(_ROOT)): s for p, s in fixed.items()})
        == []
    )


@pytest.mark.parametrize(
    "items",
    [
        {"retired": True, "live": False},
        {"live": False, "retired": True},
        {"old": None, "retired": True, "live": False},
        {"live": False, "old": 42, "retired": True},
        {"old": 42, "live": False, "retired": True},
        {"retired": True},
    ],
)
@pytest.mark.parametrize("indent", [None, 2])
def test_json_separator_edits_preserve_every_declared_value(
    items: dict[str, bool | int | None], indent: int | None
) -> None:
    source = json.dumps(items, indent=indent) + "\n"
    sources = _sources(source, "terraform.tfvars.json")
    path = _ROOT / "terraform.tfvars.json"
    changes = remove_stale_assignments(sources, selected=(path,))
    assert json.loads(changes[path]) == {key: value for key, value in items.items() if key == "live"}
    assert remove_stale_assignments({**sources, **changes}, selected=(path,)) == {}


@pytest.mark.parametrize(
    ("name", "source", "extra"),
    [
        ("dev.tfvars", "retired = true\n", {}),
        ("terraform.tfvars", 'retired = "potential-secret"\n', {}),
        ("terraform.tfvars.json", '{"retired":"potential-secret"}\n', {}),
        ("terraform.tfvars", 'retired = ["potential-secret"]\n', {}),
        ("terraform.tfvars", "# generated - do not edit\nretired = true\n", {}),
        ("terraform.tfvars", "retired = true # retained directive\n", {}),
        ("terraform.tfvars", "retired = true # sarj-noqa: SARJ205 -- retained contract\n", {}),
        ("terraform.tfvars", "retired = true\n", {"override.tf": 'variable "retired" { default = false }\n'}),
        (
            "terraform.tfvars",
            "retired = true\n",
            {"main.tf": 'locals { fingerprint = filesha256("${path.module}/terraform.tfvars") }\n'},
        ),
        ("terraform.tfvars", "retired = true\nretired = false\n", {}),
        ("terraform.tfvars.json", '{"retired":true,"retired":false}', {}),
        ("terraform.tfvars", "retired = [\n", {}),
        ("terraform.tfvars", "retired = .5\n", {}),
        ("terraform.tfvars", "retired = \u0661\n", {}),
        ("terraform.tfvars", "retired = true\u00a0\n", {}),
        ("terraform.tfvars", "retired = (true)\n", {}),
        ("terraform.tfvars", "retired = 1e10000000000\n", {}),
        ("terraform.tfvars.json", '{"retired":1e10000000000}', {}),
        ("terraform.tfvars", 'retired = "true"\n', {}),
        ("terraform.tfvars.json", '{"retired":"true"}', {}),
        ("terraform.tfvars.json", '{"retired":"123456"}', {}),
    ],
)
def test_unsupported_fixes_preserve_the_original_source(name: str, source: str, extra: dict[str, str]) -> None:
    sources = {**_sources(source, name), **{_ROOT / key: value for key, value in extra.items()}}
    assert remove_stale_assignments(sources, selected=(_ROOT / name,)) == {}
    assert fix_source(_ROOT / name, source, rule_ids=(NoDeadEnvironmentInput.id,)) == source


def test_auto_loaded_precedence_is_preserved_and_default_equal_is_not_removed() -> None:
    sources = _sources("live = true\nretired = true\n")
    sources[_ROOT / "later.auto.tfvars"] = "live = false\n"
    changes = remove_stale_assignments(sources, selected=tuple(sources))
    assert changes == {_ROOT / "terraform.tfvars": "live = true\n"}


def test_only_selected_files_are_fixed_and_json_declarations_are_consumers() -> None:
    sources = _sources("retired = true\n")
    sources[_ROOT / "variables.tf.json"] = '{"variable":{"retired":{"type":"bool"}}}\n'
    assert remove_stale_assignments(sources, selected=tuple(sources)) == {}
    sources.pop(_ROOT / "variables.tf.json")
    assert remove_stale_assignments(sources, selected=(_ROOT / "variables.tf",)) == {}


@pytest.mark.parametrize(
    "consumer",
    [
        'output "hash" { value = filesha1("${path.module}/terraform.tfvars") }\n',
        'output "opaque" { value = provider::opaque::read("terraform.tfvars") }\n',
        'data "external" "opaque" { program = ["inspect-config"] }\n',
        'resource "terraform_data" "opaque" {\n provisioner "local-exec" { command = "inspect-config" }\n}\n',
    ],
)
def test_source_bytes_and_unknown_execution_contracts_prevent_deletion(consumer: str) -> None:
    sources = _sources("retired = true\n")
    sources[_ROOT / "consumer.tf"] = consumer
    assert remove_stale_assignments(sources, selected=(_ROOT / "terraform.tfvars",)) == {}


def test_last_variable_removal_still_reports_stale_assignments() -> None:
    sources = {PurePosixPath("main.tf"): "terraform {}\n", PurePosixPath("terraform.tfvars"): "retired = true\n"}
    findings = NoDeadEnvironmentInput.check_project(_ROOT, sources)
    assert len(findings) == 1
    assert "orphaned-key" in findings[0].message


@pytest.mark.parametrize(
    "source", ["retired = [\n", "live =\n", "retired = true\nretired = false\n", '{"retired":true,"retired":false}']
)
def test_malformed_assignments_make_project_analysis_incomplete(source: str) -> None:
    name = "terraform.tfvars.json" if source.startswith("{") else "terraform.tfvars"
    sources = _sources(source, name)
    with pytest.raises(ValueError, match="malformed"):
        NoDeadEnvironmentInput.check_project(
            _ROOT, {PurePosixPath(p.relative_to(_ROOT)): s for p, s in sources.items()}
        )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        pytest.param(False, 1, id="literal-comment"),
        pytest.param("source ownership note", 1, id="ownership-comment"),
        pytest.param({"generator": "unknown"}, 1, id="structured-comment"),
        pytest.param("generated - do not edit", 0, id="generated-source-owner"),
        pytest.param("sarj-noqa: SARJ205 -- retain configuration", 1, id="tool-directive-review"),
    ],
)
def test_json_comment_metadata_is_not_configuration_and_prevents_automatic_edits(
    metadata: bool | str | dict[str, str], expected: int
) -> None:
    source = json.dumps({"retired": True, "//": metadata, "live": False}) + "\n"
    sources = _sources(source, "terraform.tfvars.json")
    findings = NoDeadEnvironmentInput.check_project(
        _ROOT, {PurePosixPath(p.relative_to(_ROOT)): s for p, s in sources.items()}
    )
    assert len(findings) == expected
    assert all("`retired`" in finding.message for finding in findings)
    assert remove_stale_assignments(sources, selected=(_ROOT / "terraform.tfvars.json",)) == {}


@pytest.mark.parametrize(
    "value",
    ["0.5", "-1e+2", "null", "1e308", "1e-308"],
    ids=["decimal", "negative-exponent", "null", "upper-supported", "lower-supported"],
)
def test_supported_hcl_scalar_literals_are_removed_without_altering_live_inputs(value: str) -> None:
    sources = _sources("live = false\nretired = " + value + "\n")
    path = _ROOT / "terraform.tfvars"
    assert remove_stale_assignments(sources, selected=(path,)) == {path: "live = false\n"}


@pytest.mark.parametrize(
    "opaque",
    [
        pytest.param('module "reader" { source = "./reader" }\n', id="module-call"),
        pytest.param('provider "opaque" {}\n', id="provider"),
        pytest.param('resource "opaque_file" "reader" { source = "terraform.tfvars" }\n', id="resource"),
        pytest.param('data "opaque_file" "reader" { filename = "terraform.tfvars" }\n', id="data"),
        pytest.param('terraform { backend "local" {} }\n', id="backend"),
    ],
)
def test_opaque_consumers_in_unchanged_project_source_prevent_all_deletions(opaque: str) -> None:
    sources = _sources("retired = true\n")
    sources[_ROOT / "unchanged/reader.tf"] = opaque
    assert remove_stale_assignments(sources, selected=(_ROOT / "terraform.tfvars",)) == {}


def test_pure_configuration_uses_parsed_constructs_instead_of_words_in_strings() -> None:
    sources = _sources("live = false\nretired = true\n")
    sources[_ROOT / "main.tf"] = (
        'terraform { required_version = ">= 1.17.0" }\n'
        'locals { description = "module provider resource data backend" }\n'
        'output "live" { value = var.live }\n'
    )
    path = _ROOT / "terraform.tfvars"
    assert remove_stale_assignments(sources, selected=(path,)) == {path: "live = false\n"}
