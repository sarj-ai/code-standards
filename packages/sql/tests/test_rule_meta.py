from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from sarj_sql_lint.rule_base import ExampleFile, ExampleOutcome, Rule, RuleExample
from sarj_sql_lint.rules import REGISTRY


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_self_documenting_meta(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    assert issubclass(cls, Rule)

    assert cls.id == rule_id, f"REGISTRY key {rule_id!r} != cls.id {cls.id!r}"
    assert cls.id
    assert cls.id.replace("-", "").replace("_", "").isalnum()

    assert cls.code, f"{rule_id}: missing code"
    assert cls.code.startswith("SARJ"), f"{rule_id}: code {cls.code!r} must start with SARJ"

    assert cls.description, f"{rule_id}: empty description"
    assert len(cls.description) >= 10


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id


def test_historical_aliases_are_documentation_only() -> None:
    aliases = {
        alias: rule_id
        for rule_id, cls in REGISTRY.items()
        if cls.documentation is not None
        for alias in cls.documentation.aliases
    }

    assert aliases["no-limit-offset"] == "no-offset-pagination"
    assert aliases["add-constraint-not-valid"] == "add-constraint-requires-not-valid"
    assert set(aliases).isdisjoint(REGISTRY)


def test_every_rule_has_valid_source_owned_documentation() -> None:
    missing = sorted(rule_id for rule_id, cls in REGISTRY.items() if cls.documentation is None)
    assert not missing, f"rules missing source-owned documentation: {', '.join(missing)}"

    documented = {rule_id: cls.native_spec() for rule_id, cls in REGISTRY.items()}

    for rule_id, spec in documented.items():
        assert spec is not None
        assert spec.key == f"sql:{rule_id}"
        assert spec.rule_id == rule_id
        assert spec.code == REGISTRY[rule_id].code
        assert spec.summary == REGISTRY[rule_id].description
        assert {example.outcome for example in spec.public_examples} == {"match", "no-match"}


def test_rule_examples_are_private_by_default_path_aware_and_multi_file() -> None:
    example = RuleExample(
        example_id="schema-and-migration",
        title="Multi-file SQL fixture",
        outcome=ExampleOutcome.NO_MATCH,
        files=(
            ExampleFile.sql("schema/current.sql", "CREATE TABLE item (id BIGINT);\n"),
            ExampleFile.sql("migrations/001_item.sql", "CREATE TABLE item (id BIGINT);\n"),
        ),
        focus_path=PurePosixPath("migrations/001_item.sql"),
        expected_count=0,
    )

    assert example.public is False
    assert example.focus_file.path == PurePosixPath("migrations/001_item.sql")
    assert len(example.files) == 2


@pytest.mark.parametrize("path", ["/private/migration.sql", "../outside.sql", "db/../../outside.sql"])
def test_rule_example_files_reject_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative paths"):
        ExampleFile.sql(path, "SELECT 1;\n")
