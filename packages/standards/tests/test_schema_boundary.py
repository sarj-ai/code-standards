from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.schema_boundary import (
    HELM_SCHEMA_DIALECTS,
    KUBERNETES_DEFAULT_DIALECT,
    schema_references,
    validate_local_schema,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("schema", "instance", "valid"),
    [
        ('{"$schema":"http://json-schema.org/draft-04/schema#","minimum":1,"exclusiveMinimum":true}', 1, False),
        ('{"$schema":"http://json-schema.org/draft-04/schema#","minimum":1,"exclusiveMinimum":true}', 2, True),
        (
            '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","unevaluatedProperties":false}',
            {"unknown": 1},
            False,
        ),
        (
            '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","unevaluatedProperties":false}',
            {},
            True,
        ),
        ('{"type":"string"}', "value", True),
    ],
    ids=(
        "draft4-exclusive-rejected",
        "draft4-exclusive-accepted",
        "draft2020-unevaluated-rejected",
        "draft2020-unevaluated-accepted",
        "default-draft7",
    ),
)
def test_declared_dialect_is_used_for_schema_and_instance(
    tmp_path: Path, schema: str, instance: object, valid: bool
) -> None:
    path = tmp_path / "schema.json"
    path.write_text(schema)
    assert bool(validate_local_schema(instance, path, (path,))) is not valid


@pytest.mark.parametrize(
    "schema",
    [
        {"$schema": "https://example.invalid/metaschema"},
        {"$schema": "http://json-schema.org/draft-07/schema###"},
        {"properties": {"value": {"$schema": "https://example.invalid/metaschema"}}},
    ],
    ids=("unknown-root-dialect", "noncanonical-dialect-fragment", "unknown-nested-dialect"),
)
def test_unknown_schema_dialects_fail_before_retrieval(schema: object) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        schema_references(schema)


@pytest.mark.parametrize("identifier", ["https://example.invalid/base/", "nested/", "file:///outside/"])
def test_base_changing_identifiers_with_external_refs_are_unproven(identifier: str) -> None:
    with pytest.raises(ValueError, match="base-changing"):
        schema_references({"$id": identifier, "properties": {"value": {"$ref": "child.json"}}})


def test_benign_identifier_with_internal_refs_retains_validation(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"$id":"https://example.invalid/schema","$ref":"#/definitions/value","definitions":{"value":{"type":"integer"}}}'
    )
    assert not validate_local_schema(1, schema, (schema,))
    assert validate_local_schema("invalid", schema, (schema,))


def test_reference_keywords_in_examples_defaults_and_enum_are_data() -> None:
    assert not schema_references(
        {
            "examples": [{"$ref": "https://example.invalid/example"}],
            "default": {"$id": "https://example.invalid/base", "$ref": "data.json"},
            "enum": [{"$schema": "data"}],
        }
    )


def test_json_pointer_target_under_unknown_keyword_is_still_a_schema() -> None:
    schema = {"$ref": "#/opaque/value", "opaque": {"value": {"$ref": "https://example.invalid/remote"}}}
    assert "https://example.invalid/remote" in schema_references(schema)


def test_external_json_pointer_target_is_also_inspected() -> None:
    assert schema_references({"opaque": {"value": {"$ref": "remote.json"}}}, fragment="/opaque/value") == (
        "remote.json",
    )


def test_percent_encoded_internal_json_pointer_cannot_hide_reference() -> None:
    schema = {"$ref": "#%2Fopaque%2Fvalue", "opaque": {"value": {"$ref": "https://example.invalid/remote"}}}
    assert "https://example.invalid/remote" in schema_references(schema)


def test_recursive_json_pointer_resource_remains_bounded() -> None:
    assert schema_references({"$ref": "#/definitions/node", "definitions": {"node": {"$ref": "#/definitions/node"}}})


def test_modern_dynamic_reference_cannot_hide_network_access() -> None:
    assert schema_references(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "$dynamicRef": "https://example.invalid/remote"}
    ) == ("https://example.invalid/remote",)


def test_modern_subresources_inherit_dynamic_reference_semantics() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "properties": {"value": {"$dynamicRef": "https://example.invalid/remote"}},
    }
    assert "https://example.invalid/remote" in schema_references(schema)


def test_kubeconform_default_draft4_legacy_id_controls_reference_base() -> None:
    schema = {"id": "https://example.invalid/base/", "properties": {"value": {"$ref": "child.json"}}}
    with pytest.raises(ValueError, match="base-changing"):
        schema_references(schema, default_dialect=KUBERNETES_DEFAULT_DIALECT)


def test_helm_undeclared_hybrid_schema_detects_legacy_id_base() -> None:
    schema = {"id": "https://example.invalid/base/", "properties": {"value": {"$ref": "child.json"}}}
    with pytest.raises(ValueError, match="base-changing"):
        schema_references(schema, dialects=HELM_SCHEMA_DIALECTS, legacy_identifiers=True)


def test_helm_native_identifier_sibling_of_ref_still_changes_base() -> None:
    with pytest.raises(ValueError, match="base-changing"):
        schema_references(
            {"$id": "https://example.invalid/base/", "$ref": "child.json"},
            dialects=HELM_SCHEMA_DIALECTS,
            legacy_identifiers=True,
        )


def test_legacy_unknown_dynamic_reference_is_ignored_like_upstream() -> None:
    assert not schema_references({"$dynamicRef": "https://example.invalid/data"})


@pytest.mark.parametrize(
    "dialect", ["https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"]
)
def test_helm_supports_modern_schema_dialects(dialect: str) -> None:
    assert not schema_references({"$schema": dialect}, dialects=HELM_SCHEMA_DIALECTS)


def test_duplicate_schema_keys_are_invalid_input(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text('{"type":"integer","type":"string"}')
    with pytest.raises(ValueError, match="duplicate"):
        validate_local_schema("value", path, (path,))
