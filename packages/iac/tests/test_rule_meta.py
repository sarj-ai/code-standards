from __future__ import annotations

from pathlib import PurePosixPath
import warnings

import pytest

from sarj_iac_lint.rule_base import ExampleFile, ExampleOutcome, Rule, RuleExample
from sarj_iac_lint.rules import REGISTRY


MIN_DESCRIPTION_LEN = 10


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_self_documenting_meta(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    assert issubclass(cls, Rule)
    assert cls.id == rule_id, f"REGISTRY key {rule_id!r} != cls.id {cls.id!r}"
    assert cls.id
    assert cls.id.replace("-", "").replace("_", "").isalnum()
    assert cls.code, f"{rule_id}: missing code"
    assert cls.code.startswith("SARJ"), f"{rule_id}: code must start with SARJ"
    assert cls.description
    assert len(cls.description) >= MIN_DESCRIPTION_LEN


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id


def test_codes_unique() -> None:
    codes = [cls.code for cls in REGISTRY.values()]
    assert len(codes) == len(set(codes)), "duplicate SARJ codes"


def test_authored_rule_documentation_contract_is_valid_warning_first() -> None:
    documented = {rule_id: cls.native_spec() for rule_id, cls in REGISTRY.items() if cls.documentation is not None}
    assert len(documented) >= 3, "the source-derived documentation migration lost an IaC rule record"

    for rule_id, spec in documented.items():
        assert spec is not None
        assert spec.key == f"iac:{rule_id}"
        assert spec.rule_id == rule_id
        assert spec.code == REGISTRY[rule_id].code
        assert spec.summary == REGISTRY[rule_id].description
        assert {example.outcome for example in spec.public_examples} == {"match", "no-match"}

    missing = sorted(set(REGISTRY) - set(documented))
    if missing:
        warnings.warn(
            f"source-derived rule documentation migration is incomplete: {len(missing)} IaC rules remain",
            stacklevel=1,
        )


def test_rule_examples_are_private_by_default_path_aware_and_multi_file() -> None:
    example = RuleExample(
        example_id="module-and-root",
        title="Multi-file IaC fixture",
        outcome=ExampleOutcome.NO_MATCH,
        files=(
            ExampleFile.iac("modules/storage/main.tf", 'resource "null_resource" "module" {}\n'),
            ExampleFile.iac("main.tf", 'module "storage" { source = "./modules/storage" }\n'),
        ),
        focus_path=PurePosixPath("main.tf"),
        expected_count=0,
    )

    assert example.public is False
    assert example.focus_file.path == PurePosixPath("main.tf")
    assert len(example.files) == 2


@pytest.mark.parametrize("path", ["/private/main.tf", "../outside.tf", "modules/../../outside.tf"])
def test_rule_example_files_reject_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative paths"):
        ExampleFile.iac(path, 'resource "null_resource" "example" {}\n')
