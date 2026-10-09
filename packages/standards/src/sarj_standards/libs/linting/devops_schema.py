from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from jsonschema import Draft7Validator
from pydantic import JsonValue, TypeAdapter
from referencing import Registry, Resource
import yaml
from yaml.nodes import MappingNode, Node, SequenceNode

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    SourceDocument,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import cloudbuild
from sarj_standards.libs.typed_containers import is_object_mapping
from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from jsonschema.exceptions import ValidationError
    from referencing.jsonschema import Schema

_SCHEMAS = Path(__file__).resolve().parents[2] / "configs" / "schemas"
_SKAFFOLD_SHA256 = "c391a01232cdbf2db42b92664f62fce3bd0e37bf8d0c1de77abacb81b82951bc"
_CLOUDDEPLOY_VERSION = "deploy.cloud.google.com/v1"
_MAX_YAML_DEPTH = 64
_STRING: Mapping[str, object] = MappingProxyType({"type": "string", "minLength": 1})
_STRINGS: Mapping[str, object] = MappingProxyType({"type": "array", "items": {"type": "string"}})
_METADATA: Mapping[str, object] = MappingProxyType(
    {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": _STRING,
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
            "annotations": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    }
)
_DEPLOY_COMMON: Mapping[str, object] = MappingProxyType(
    {
        "type": "object",
        "required": ["apiVersion", "kind", "metadata"],
        "properties": {
            "apiVersion": {"const": _CLOUDDEPLOY_VERSION},
            "kind": _STRING,
            "metadata": _METADATA,
            "description": {"type": "string"},
            "suspended": {"type": "boolean"},
        },
    }
)
_DEPLOY_FIELDS: Mapping[str, dict[str, object]] = MappingProxyType(
    {
        "DeliveryPipeline": {
            "serialPipeline": {
                "type": "object",
                "properties": {
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["targetId"],
                            "properties": {
                                "targetId": _STRING,
                                "profiles": _STRINGS,
                            },
                        },
                    },
                },
            }
        },
        "Target": {
            "requireApproval": {"type": "boolean"},
            "executionConfigs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "usages": _STRINGS,
                        "workerPool": _STRING,
                        "serviceAccount": _STRING,
                        "artifactStorage": _STRING,
                        "executionTimeout": _STRING,
                        "verbose": {"type": "boolean"},
                    },
                },
            },
            **{field: {"type": "object"} for field in ("gke", "run", "anthosCluster", "customTarget", "multiTarget")},
        },
        "CustomTargetType": {
            "customActions": {"type": "object", "properties": {"renderAction": _STRING, "deployAction": _STRING}},
            "tasks": {"type": "object"},
        },
    }
)


def analyze_source_schemas(*, root: Path, paths: tuple[str, ...]) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    for relative in paths:
        path = (root / relative).resolve()
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            path.relative_to(root.resolve())
            source = path.read_text(encoding="utf-8")
            nodes = _documents(source)
        except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
            if "skaffold" in path.stem or "clouddeploy" in path.stem:
                reports.append(_failed("devops-schema", error))
            continue
        for node in nodes:
            if not isinstance(node, MappingNode):
                continue
            version = _schema_version(node)
            if version is None or not version.startswith(("skaffold/", "deploy.cloud.google.com/")):
                continue
            reports.append(_validate_document(root, path, source, node, version))
    return tuple(reports)


def _schema_version(node: MappingNode) -> str | None:
    return next(
        (
            cloudbuild.scalar_text(value)
            for key, value in mapping_items(node)
            if cloudbuild.scalar_text(key) == "apiVersion"
        ),
        None,
    )


def _documents(source: str) -> list[Node | None]:
    return cloudbuild.compose_documents(source)


def _validate_document(root: Path, path: Path, source: str, node: MappingNode, version: str) -> ToolReport:
    name = "skaffold-schema" if version.startswith("skaffold/") else "clouddeploy-structure"
    try:  # ruff: ignore[too-many-statements-in-try-clause] -- normalize the external schema and YAML boundaries into one fatal coverage report.
        schema = _skaffold_schema(version) if version.startswith("skaffold/") else _deploy_schema(node, version)
        _validate_keys(node)
        loader = yaml.SafeLoader("")
        try:
            instance: object = loader.construct_document(node)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] -- safe YAML constructor boundary.
        finally:
            loader.dispose()  # pyright: ignore[reportUnknownMemberType] -- PyYAML loader cleanup boundary.
        resource: Resource[Schema] = Resource.from_contents(schema)
        registry: Registry[Schema] = Registry()
        registry = registry.with_resource("urn:sarj:devops-source", resource)
        validator = Draft7Validator(schema, registry=registry)
        normalized = TypeAdapter[JsonValue](JsonValue).validate_python(instance)
        errors: Iterable[ValidationError] = validator.iter_errors(normalized)  # pyright: ignore[reportUnknownMemberType] -- jsonschema validation boundary.
        document = SourceDocument(path, source)
        findings = tuple(_schema_diagnostic(root, path, document, node, error, name=name) for error in errors)  # pyright: ignore[reportAny] -- external jsonschema iterator stub exposes validated errors as Any.
        return ToolReport(name, Completion.COMPLETE, diagnostics=findings, file_count=1)
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
        return _failed(name, error)


def _skaffold_schema(version: str) -> Schema:
    if version != "skaffold/v4beta7":
        message = f"No reviewed local Skaffold schema covers {version}"
        raise ValueError(message)
    payload = (_SCHEMAS / "skaffold-v4beta7.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != _SKAFFOLD_SHA256:
        message = "Pinned upstream Skaffold schema digest does not match"
        raise ValueError(message)
    return _schema(parse_json(payload.decode("utf-8")))


def _validate_keys(node: Node, *, depth: int = 0) -> None:
    if depth >= _MAX_YAML_DEPTH:
        message = "Excessively nested YAML cannot be validated"
        raise ValueError(message)
    if isinstance(node, MappingNode):
        for value in cloudbuild.mapping_fields(node).values():
            _validate_keys(value, depth=depth + 1)
    elif isinstance(node, SequenceNode):
        for item in sequence_items(node):
            _validate_keys(item, depth=depth + 1)


def _deploy_schema(node: MappingNode, version: str) -> Schema:
    if version != _CLOUDDEPLOY_VERSION:
        message = f"No reviewed structural Cloud Deploy contract covers {version}"
        raise ValueError(message)
    kind = cloudbuild.scalar_text(cloudbuild.mapping_fields(node).get("kind"))
    if kind is None or kind not in _DEPLOY_FIELDS:
        message = f"No structural Cloud Deploy contract covers kind {kind}"
        raise ValueError(message)
    # This deliberately permits additional fields. Google publishes a YAML
    # reference, not a complete standalone JSON schema; this contract checks
    # documented known field types and never pretends to replace native API validation.
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "allOf": [
            _DEPLOY_COMMON,
            {"properties": _DEPLOY_FIELDS[kind]},
        ],
    }


def _schema(value: object) -> Schema:
    if not is_object_mapping(value) or not all(isinstance(key, str) for key in value):
        message = "Upstream schema must contain a JSON object with string keys"
        raise ValueError(message)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _schema_diagnostic(
    root: Path, path: Path, document: SourceDocument, node: Node, error: ValidationError, *, name: str
) -> Diagnostic:
    while len(error.context) == 1:
        error = error.context[0]
    parts: tuple[object, ...] = tuple(error.absolute_path)
    located = node
    position_node = node
    for part in parts:
        if isinstance(part, str) and isinstance(located, MappingNode):
            located = cloudbuild.mapping_fields(located).get(part, located)
        elif isinstance(part, int) and isinstance(located, SequenceNode):
            children = sequence_items(located)
            if 0 <= part < len(children):
                located = children[part]
        if located.start_mark.line >= position_node.start_mark.line:
            position_node = located
    message: str = error.message
    return Diagnostic(
        "schema",
        message,
        Severity.ERROR,
        "devops-schema",
        Location(
            path.relative_to(root.resolve()).as_posix(),
            position=document.point(line=position_node.start_mark.line + 1, column=position_node.start_mark.column + 1),
        ),
        rule_id=name,
    )


def _failed(name: str, error: Exception) -> ToolReport:
    return ToolReport(
        name, Completion.FAILED, issues=(ExecutionIssue("devops-schema", "coverage-failure", str(error)),), file_count=1
    )
