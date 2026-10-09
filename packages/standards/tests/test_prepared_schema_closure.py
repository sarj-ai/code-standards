from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import PreparedTarget
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.devops_tools import checked_tool, invoke
from sarj_standards.libs.linting.prepared_devops import analyze_prepared
from sarj_standards.libs.schema_boundary import validate_local_schema
from sarj_standards.libs.typed_containers import is_object_mapping


if TYPE_CHECKING:
    from sarj_standards.libs.diagnostics import ToolReport


_DIALECT = "http://json-schema.org/draft-04/schema#"


@dataclass(frozen=True, slots=True)
class _ClosureFixture:
    root: Path
    schema: Path
    shared: Path
    target: dict[str, object]


def _closure(root: Path, reference: object) -> _ClosureFixture:
    schema = root / "nested" / "pod.json"
    schema.parent.mkdir(parents=True)
    schema.write_text(json.dumps({"$schema": _DIALECT, "$ref": reference}), encoding="utf-8")
    shared = root / "shared.json"
    shared.write_text('{"definitions":{"value":{"type":"object","required":["metadata"]}}}', encoding="utf-8")
    source = root / "deploy.yaml"
    source.write_text("authored source\n", encoding="utf-8")
    manifest = root / "resource.yaml"
    manifest.write_text(
        "apiVersion: serving.knative.dev/v1\nkind: Service\nmetadata:\n  name: example\n", encoding="utf-8"
    )
    target: dict[str, object] = {
        "id": "example",
        "source": "deploy.yaml",
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "kind": "cloud-run",
        "manifests": ["resource.yaml"],
        "schema_bindings": {"serving.knative.dev/v1/Service": "nested/pod.json"},
        "artifacts": {
            path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in (schema, shared, manifest)
        },
    }
    return _ClosureFixture(root, schema, shared, target)


def _report(fixture: _ClosureFixture) -> ToolReport:
    artifacts = fixture.target["artifacts"]
    assert is_object_mapping(artifacts)
    artifacts["nested/pod.json"] = sha256(fixture.schema.read_bytes()).hexdigest()
    receipt = fixture.root / "receipt.json"
    receipt.write_text(json.dumps({"version": 1, "targets": [fixture.target]}), encoding="utf-8")
    [report] = analyze_prepared((receipt,), root=fixture.root, declared=(PreparedTarget("example", "deploy.yaml"),))
    return report


@pytest.mark.parametrize(
    "reference",
    [
        "../shared.json#/definitions/value",
        "./../shared.json#/definitions/value",
        "absent/../../shared.json#/definitions/value",
    ],
    ids=("contained-parent", "dot-parent", "canceled-missing-segment"),
)
def test_contained_relative_schema_closure_matches_native_resolution(tmp_path: Path, reference: str) -> None:
    fixture = _closure(tmp_path, reference)
    assert _report(fixture).completion is Completion.COMPLETE
    schema, shared = fixture.schema, fixture.shared
    tool = checked_tool("kubeconform", root=tmp_path)
    assert tool.version == "0.8.0"
    for valid in (True, False):
        instance: dict[str, object] = {"apiVersion": "v1", "kind": "Pod"}
        if valid:
            instance["metadata"] = {"name": "example"}
        assert bool(validate_local_schema(instance, schema, (schema, shared))) is not valid
        manifest = tmp_path / "pod.json"
        manifest.write_text(json.dumps(instance), encoding="utf-8")
        output = invoke(
            tool,
            ("-strict", "-verbose", "-summary", "-output", "json", "-schema-location", str(schema), str(manifest)),
            root=tmp_path,
        )
        assert output.returncode == (0 if valid else 1), output.stderr
        payload = parse_json(output.stdout)
        assert isinstance(payload, dict)
        assert payload["summary"] == {"valid": int(valid), "invalid": int(not valid), "errors": 0, "skipped": 0}


@pytest.mark.parametrize(
    "reference",
    [
        "../../outside.json",
        "https://example.invalid/schema.json",
        "//example.invalid/schema.json",
        "/schema.json",
        "file:///schema.json",
        "../%73hared.json",
        "../shared.json?query",
        "..\\shared.json",
    ],
    ids=("escape", "network", "network-relative", "absolute", "file-uri", "encoded", "query", "backslash"),
)
def test_relative_schema_closure_retains_reference_admission(tmp_path: Path, reference: str) -> None:
    fixture = _closure(tmp_path, reference)
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues


@pytest.mark.parametrize("mutation", ["missing-hash", "changed-hash", "symlink", "symlink-directory", "missing-file"])
def test_normalized_schema_reference_retains_artifact_checks(tmp_path: Path, mutation: str) -> None:
    fixture = _closure(tmp_path, "../shared.json#/definitions/value")
    shared = fixture.shared
    artifacts = fixture.target["artifacts"]
    assert is_object_mapping(artifacts)
    match mutation:
        case "missing-hash":
            artifacts.pop("shared.json")
        case "changed-hash":
            shared.write_text("{}", encoding="utf-8")
        case "symlink":
            original = shared.with_name("original.json")
            shared.rename(original)
            shared.symlink_to(original)
        case "symlink-directory":
            (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
            fixture.schema.write_text('{"$ref":"../alias/shared.json"}', encoding="utf-8")
            artifacts["alias/shared.json"] = sha256(shared.read_bytes()).hexdigest()
        case _:
            shared.unlink()
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues
    if mutation.startswith("symlink"):
        assert "symlink" in report.issues[0].message


@pytest.mark.parametrize(
    "body",
    [
        '{"$ref":',
        '{"$ref":2}',
        '{"$ref":"../shared.json#/missing"}',
        '{"$ref":"../shared.json","$ref":"../other.json"}',
        '{"$schema":"http://json-schema.org/draft-04/schema#","id":"https://example.invalid/base/","properties":{"value":{"$ref":"../shared.json"}}}',
    ],
    ids=("malformed-json", "malformed-ref", "missing-pointer", "duplicate-ref", "base-changing-id"),
)
def test_normalized_schema_closure_rejects_invalid_semantics(tmp_path: Path, body: str) -> None:
    fixture = _closure(tmp_path, "../shared.json")
    fixture.schema.write_text(body, encoding="utf-8")
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues


def test_relative_schema_cycle_is_bounded_and_example_refs_are_data(tmp_path: Path) -> None:
    fixture = _closure(tmp_path, "../shared.json")
    shared = fixture.shared
    shared.write_text(
        '{"type":"object","properties":{"next":{"$ref":"nested/../nested/pod.json"}},"examples":[{"$ref":"https://example.invalid/data"}]}',
        encoding="utf-8",
    )
    artifacts = fixture.target["artifacts"]
    assert is_object_mapping(artifacts)
    artifacts["shared.json"] = sha256(shared.read_bytes()).hexdigest()
    assert _report(fixture).completion is Completion.COMPLETE
    assert _report(fixture).completion is Completion.COMPLETE
