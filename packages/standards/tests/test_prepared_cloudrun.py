from __future__ import annotations

from hashlib import sha256
import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import PreparedTarget
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.prepared_devops import analyze_prepared


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _receipt(root: Path, document: Mapping[str, object], schema: Mapping[str, object], binding: str) -> Path:
    source = root / "delivery.tf"
    source.write_text("authored Cloud Run configuration\n", encoding="utf-8")
    directory = root / "prepared"
    directory.mkdir()
    (directory / "resource.json").write_text(json.dumps(document), encoding="utf-8")
    (directory / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    receipt = directory / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "version": 1,
                "targets": [
                    {
                        "id": "cloudrun",
                        "source": "delivery.tf",
                        "source_sha256": sha256(source.read_bytes()).hexdigest(),
                        "kind": "cloud-run",
                        "manifests": ["resource.json"],
                        "schema_bindings": {binding: "schema.json"},
                        "artifacts": {
                            name: sha256((directory / name).read_bytes()).hexdigest()
                            for name in ("resource.json", "schema.json")
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return receipt


@pytest.mark.parametrize(
    ("api_version", "kind"),
    [("serving.knative.dev/v1", "Service"), ("run.googleapis.com/v1", "Job")],
)
@pytest.mark.parametrize("valid", [False, True])
def test_cloudrun_exact_gvk_uses_hashed_local_schema(
    tmp_path: Path, api_version: str, kind: str, *, valid: bool
) -> None:
    document = {"apiVersion": api_version, "kind": kind, "metadata": {"name": "example" if valid else 123}}
    schema = {
        "type": "object",
        "required": ["apiVersion", "kind", "metadata"],
        "properties": {
            "apiVersion": {"const": api_version},
            "kind": {"const": kind},
            "metadata": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    }
    path = _receipt(tmp_path, document, schema, f"{api_version}/{kind}")
    [report] = analyze_prepared((path,), root=tmp_path, declared=(PreparedTarget("cloudrun", "delivery.tf"),))
    assert report.completion is Completion.COMPLETE
    assert not report.issues
    assert bool(report.diagnostics) is not valid
    assert all(item.source == "devops-schema" and item.rule_id == "cloud-run" for item in report.diagnostics)


@pytest.mark.parametrize(
    ("api_version", "kind", "binding", "schema"),
    [
        ("run.googleapis.com/v1", "Job", "serving.knative.dev/v1/Service", {"type": "object"}),
        ("run.googleapis.com/v2", "Job", "run.googleapis.com/v2/Job", {"type": "object"}),
        ("run.googleapis.com/v1", "WorkerPool", "run.googleapis.com/v1/WorkerPool", {"type": "object"}),
        ("batch/v1", "Job", "batch/v1/Job", {"type": "object"}),
        ("run.googleapis.com/v1", "Service", "run.googleapis.com/v1/Service", {"type": "object"}),
        ("run.googleapis.com/v1", "Job", "run.googleapis.com/v1/Job", {"$ref": "https://example.invalid/job.json"}),
        ("run.googleapis.com/v1", "Job", "run.googleapis.com/v1/Job", {"$ref": "../outside.json"}),
    ],
)
def test_cloudrun_unknown_gvk_missing_binding_and_open_schema_fail_closed(
    tmp_path: Path, api_version: str, kind: str, binding: str, schema: dict[str, object]
) -> None:
    document = {"apiVersion": api_version, "kind": kind, "metadata": {"name": "example"}}
    path = _receipt(tmp_path, document, schema, binding)
    [report] = analyze_prepared((path,), root=tmp_path, declared=(PreparedTarget("cloudrun", "delivery.tf"),))
    assert report.completion is Completion.FAILED
    assert report.issues
    assert not report.diagnostics


def test_cloudrun_job_schema_tampering_fails_before_validation(tmp_path: Path) -> None:
    document = {"apiVersion": "run.googleapis.com/v1", "kind": "Job", "metadata": {"name": "example"}}
    path = _receipt(tmp_path, document, {"type": "object"}, "run.googleapis.com/v1/Job")
    (path.parent / "schema.json").write_text("{}", encoding="utf-8")
    [report] = analyze_prepared((path,), root=tmp_path, declared=(PreparedTarget("cloudrun", "delivery.tf"),))
    assert report.completion is Completion.FAILED
    assert "hash does not match" in report.issues[0].message
