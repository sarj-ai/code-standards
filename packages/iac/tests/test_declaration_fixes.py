from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_iac_lint.declaration_fixes import consolidate_declarations


def _sources() -> dict[Path, str]:
    return {
        Path(
            "main.tf"
        ): 'variable "region" { type = string }\nresource "terraform_data" "this" { input = var.region }\noutput "value" { value = terraform_data.this.output }\n',
        Path("variables.tf"): 'variable "project" { type = string }\n',
        Path("outputs.tf"): 'output "project" { value = var.project }\n',
    }


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_moves_only_interfaces_within_one_module_and_converges(ending: str) -> None:
    sources = {path: source.replace("\n", ending) for path, source in _sources().items()}
    fixed = consolidate_declarations(sources, selected=tuple(sources))

    assert fixed[Path("main.tf")] == f'resource "terraform_data" "this" {{ input = var.region }}{ending}'
    assert fixed[Path("variables.tf")].endswith(f'variable "region" {{ type = string }}{ending}')
    assert fixed[Path("outputs.tf")].endswith(f'output "value" {{ value = terraform_data.this.output }}{ending}')
    assert consolidate_declarations(sources | fixed, selected=tuple(sources)) == {}


@pytest.mark.parametrize("target", ["variables.tf", "outputs.tf"])
def test_missing_or_unselected_destination_is_never_created_or_written(target: str) -> None:
    sources = _sources()
    selected = tuple(path for path in sources if path.name != target)
    changes = consolidate_declarations(sources, selected=selected)
    assert Path(target) not in changes
    sources.pop(Path(target))
    assert Path(target) not in consolidate_declarations(sources, selected=tuple(sources))


@pytest.mark.parametrize(
    "comment",
    [
        "# SPDX-License-Identifier: MIT",
        "# tflint-ignore: terraform_typed_variables",
        "# rationale",
        "/* owned metadata */",
    ],
)
def test_comments_and_functional_metadata_refuse_movement(comment: str) -> None:
    sources = {Path("main.tf"): f'{comment}\nvariable "region" {{ type = string }}\n', Path("variables.tf"): "\n"}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}


@pytest.mark.parametrize("override", ["override.tf", "custom_override.tf", "custom_override.tf.json"])
def test_override_semantics_are_not_reordered(override: str) -> None:
    sources = _sources() | {Path(override): "{}" if override.endswith("json") else ""}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}


def test_duplicate_native_json_interfaces_prevent_movement() -> None:
    sources = _sources() | {Path("extra.tf.json"): json.dumps({"variable": {"region": {"type": "string"}}})}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}


@pytest.mark.parametrize(
    "value", ['file("main.tf")', '"${file("main.tf")}"', 'filesha256("variables.tf")', 'templatefile("main.tf", {})']
)
def test_source_observation_functions_prevent_movement(value: str) -> None:
    sources = _sources() | {Path("locals.tf"): f"locals {{ observed = {value} }}\n"}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}


def test_string_data_that_mentions_a_file_function_does_not_block_a_fix() -> None:
    sources = _sources() | {Path("locals.tf"): 'locals { text = "file(main.tf)" }\n'}
    assert consolidate_declarations(sources, selected=tuple(sources))


def test_substantive_validations_and_output_conditions_are_not_moved() -> None:
    sources = {
        Path(
            "main.tf"
        ): 'variable "region" {\n type = string\n validation {\n condition = var.region != ""\n error_message = "An existing safeguard."\n }\n}\noutput "guarded" {\n value = var.region\n precondition {\n condition = var.region != ""\n error_message = "Preserve output safety."\n }\n}\n',
        Path("variables.tf"): "\n",
        Path("outputs.tf"): "\n",
    }
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}


def test_shared_physical_lines_json_and_tfvars_remain_reviewed() -> None:
    for path, source in (
        (Path("main.tf"), 'variable "region" { type = string } locals { value = "owned" }\n'),
        (Path("main.tf.json"), '{"variable":{"region":{"type":"string"}}}'),
        (Path("prod.auto.tfvars"), 'region = "prod"\n'),
    ):
        sources = {path: source, Path("variables.tf"): "\n"}
        assert consolidate_declarations(sources, selected=tuple(sources)) == {}


def test_mixed_line_endings_are_refused_and_other_modules_are_untouched() -> None:
    sources = {Path("main.tf"): 'variable "region" { type = string }\r\n', Path("variables.tf"): "\n"}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}
    sources = {Path("main.tf"): 'variable "region" { type = string }\n', Path("child/variables.tf"): "\n"}
    assert consolidate_declarations(sources, selected=tuple(sources)) == {}
