from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import PreparedTarget
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.prepared_devops import analyze_prepared


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("namespace", "completion"),
    [("work", Completion.COMPLETE), ("other", Completion.FAILED)],
)
def test_helm_strict_lint_uses_declared_namespace(tmp_path: Path, namespace: str, completion: Completion) -> None:
    source = tmp_path / "deploy.yaml"
    source.write_text("authored deployment\n", encoding="utf-8")
    manifest = (
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: example\n  namespace: work\ndata:\n  value: fixture\n"
    )
    template = (
        '{{ if eq .Release.Namespace "work" }}\n'
        f"{manifest}"
        "{{ else }}\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: INVALID_NAME\n{{ end }}\n"
    )
    files = {
        "example/Chart.yaml": "apiVersion: v2\nname: example\nversion: 1.0.0\ndescription: Namespace contract\n",
        "example/values.yaml": "{}\n",
        "example/values.schema.json": '{"type":"object"}',
        "example/templates/config.yaml": template,
    }
    chart = tmp_path / "chart.tgz"
    with tarfile.open(chart, "w:gz") as archive:
        for name, text in files.items():
            content = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    (tmp_path / "resource.yaml").write_text(manifest, encoding="utf-8")
    (tmp_path / "schema.json").write_text(
        '{"type":"object","required":["apiVersion","kind","metadata"]}', encoding="utf-8"
    )
    target: dict[str, object] = {
        "id": "example",
        "source": source.name,
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "kind": "helm",
        "helm_version": "3.19.0",
        "release": "example",
        "namespace": namespace,
        "stage": "install",
        "kubernetes_version": "1.33.0",
        "archive": chart.name,
        "archive_sha256": sha256(chart.read_bytes()).hexdigest(),
        "manifests": ["resource.yaml"],
        "schema_bindings": {"v1/ConfigMap": "schema.json"},
        "artifacts": {
            name: sha256((tmp_path / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
        },
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"version": 1, "targets": [target]}), encoding="utf-8")
    [report] = analyze_prepared((receipt,), root=tmp_path, declared=(PreparedTarget("example", source.name),))
    assert report.completion is completion
    assert not report.diagnostics
    assert bool(report.issues) is (completion is Completion.FAILED)
