from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tarfile
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import Manifest, PreparedTarget, load
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.external import ProcessOutput
from sarj_standards.libs.linting.prepared_devops import analyze_prepared
from sarj_standards.libs.linting.prepared_kubernetes import NATIVE_CHECKS, OMISSION_CHECK
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml_documents


if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class _ReceiptFixture:
    path: Path
    target: dict[str, object]


def _receipt(root: Path, *, kind: str = "kubernetes") -> _ReceiptFixture:
    (root / "deploy.yaml").write_text("authored source\n", encoding="utf-8")
    directory = root / "prepared"
    directory.mkdir()
    (directory / "resource.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: example\n", encoding="utf-8"
    )
    (directory / "schema.json").write_text(
        '{"type":"object","required":["apiVersion","kind","metadata"]}', encoding="utf-8"
    )
    target: dict[str, object] = {
        "id": "example",
        "source": "deploy.yaml",
        "source_sha256": sha256((root / "deploy.yaml").read_bytes()).hexdigest(),
        "kind": kind,
        "kubernetes_version": "1.33.0",
        "manifests": ["resource.yaml"],
        "schema_bindings": {"v1/ConfigMap": "schema.json"},
        "artifacts": {
            name: sha256((directory / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
        },
    }
    path = directory / "receipt.json"
    _write_receipt(path, target)
    return _ReceiptFixture(path, target)


def _write_receipt(path: Path, target: dict[str, object]) -> None:
    path.write_text(json.dumps({"version": 1, "targets": [target]}), encoding="utf-8")


def _native(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    assert cwd.is_dir()
    if tuple(argv) == ("kubeconform", "-v"):
        return ProcessOutput(0, "v0.8.0\n", "")
    if tuple(argv) == ("kube-linter", "version"):
        return ProcessOutput(0, "0.8.3\n", "")
    if argv[0] == "kubeconform":
        assert "-strict" in argv
        assert "-ignore-missing-schemas" not in argv
        [resource] = parse_yaml_documents(Path(argv[-1]).read_text(encoding="utf-8"))
        assert is_object_mapping(resource)
        metadata = resource["metadata"]
        assert is_object_mapping(metadata)
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "resources": [
                        {
                            "filename": argv[-1],
                            "version": resource["apiVersion"],
                            "kind": resource["kind"],
                            "name": metadata["name"],
                            "status": "statusValid",
                        }
                    ],
                    "summary": {"valid": 1, "invalid": 0, "errors": 0, "skipped": 0},
                }
            ),
            "",
        )
    assert argv[0] == "kube-linter"
    return ProcessOutput(
        0,
        json.dumps(
            {
                "Checks": [{"name": name} for name in NATIVE_CHECKS],
                "Reports": None,
                "Summary": {"ChecksStatus": "Passed", "KubeLinterVersion": "0.8.3"},
            }
        ),
        "",
    )


def test_native_null_clean_report_is_complete(tmp_path: Path) -> None:
    path = _receipt(tmp_path).path
    reports = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )
    assert reports[0].completion is Completion.COMPLETE
    assert not reports[0].diagnostics


@pytest.mark.parametrize("stage", ["install", "upgrade"], ids=("install-hook", "upgrade-hook"))
def test_real_helm_stages_keep_ordinary_hooks_in_security_validation(tmp_path: Path, stage: str) -> None:
    fixture = _helm_receipt(tmp_path, stage)
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.COMPLETE
    assert [item.rule_id for item in reports[0].diagnostics] == [OMISSION_CHECK]


def _helm_receipt(root: Path, stage: str) -> _ReceiptFixture:
    fixture = _receipt(root, kind="helm")
    directory = fixture.path.parent
    archive = directory / "chart.tgz"
    _write_hook_chart(archive)
    (directory / "resource.yaml").write_text(_hook_resource(f"pre-{stage}"), encoding="utf-8")
    fixture.target.update(
        {
            "helm_version": "3.19.0",
            "release": "example",
            "namespace": "work",
            "stage": stage,
            "archive": archive.name,
            "archive_sha256": sha256(archive.read_bytes()).hexdigest(),
            "schema_bindings": {"v1/Pod": "schema.json"},
            "artifacts": {
                name: sha256((directory / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
            },
        }
    )
    _write_receipt(fixture.path, fixture.target)
    return fixture


def _write_hook_chart(path: Path) -> None:
    files = {
        "example/Chart.yaml": "apiVersion: v2\nname: example\nversion: 1.0.0\ndescription: Hook security fixture\n",
        "example/values.yaml": "{}\n",
        "example/values.schema.json": '{"type":"object"}',
        "example/templates/hook.yaml": _hook_resource(
            "{{ if .Release.IsUpgrade }}pre-upgrade{{ else }}pre-install{{ end }}"
        ),
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, text in files.items():
            body = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(body)
            archive.addfile(member, BytesIO(body))


def _hook_resource(hook: str) -> str:
    return (
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: ordinary-hook\n  annotations:\n"
        f"    helm.sh/hook: {hook}\nspec:\n  containers:\n  - name: helper\n"
        "    image: example@sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
        "    securityContext:\n      runAsNonRoot: true\n"
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [("id", "unknown"), ("source", "other.yaml"), ("source_sha256", "0" * 64), ("kind", "unrecognized")],
)
def test_rejects_unknown_identity_and_stale_source(tmp_path: Path, key: str, value: str) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    target[key] = value
    _write_receipt(path, target)
    reports = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues
    assert not reports[0].diagnostics


def test_missing_and_duplicate_targets_are_infrastructure_failures(tmp_path: Path) -> None:
    path = _receipt(tmp_path).path
    declared = (PreparedTarget("example", "deploy.yaml"), PreparedTarget("second", "deploy.yaml"))
    assert analyze_prepared((path,), root=tmp_path, declared=declared, runner=_native)[0].issues
    assert analyze_prepared((path, path), root=tmp_path, declared=declared, selected=("example",), runner=_native)[
        0
    ].issues
    assert analyze_prepared((path,), root=tmp_path, declared=declared, selected=("unknown",), runner=_native)[0].issues
    assert (
        analyze_prepared((path,), root=tmp_path, declared=declared, selected=("example",), runner=_native)[0].completion
        is Completion.COMPLETE
    )


@pytest.mark.parametrize("name", ["../resource.yaml", "/private/tmp/resource.yaml", "resource\\file.yaml"])
def test_artifacts_cannot_escape_receipt_directory(tmp_path: Path, name: str) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    target["manifests"] = [name]
    target["artifacts"] = {
        name: "0" * 64,
        "schema.json": sha256((path.parent / "schema.json").read_bytes()).hexdigest(),
    }
    _write_receipt(path, target)
    reports = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )
    assert reports[0].issues


def test_hashes_cover_values_and_manifests(tmp_path: Path) -> None:
    path = _receipt(tmp_path).path
    (path.parent / "resource.yaml").write_text("changed\n", encoding="utf-8")
    assert analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )[0].issues


def test_authored_input_changes_invalidate_receipts(tmp_path: Path) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    catalog = tmp_path / "applications.json"
    catalog.write_text("{}", encoding="utf-8")
    target["source_inputs"] = {
        "deploy.yaml": target["source_sha256"],
        "applications.json": sha256(catalog.read_bytes()).hexdigest(),
    }
    _write_receipt(path, target)
    declared = (PreparedTarget("example", "deploy.yaml"),)
    assert (
        analyze_prepared((path,), root=tmp_path, declared=declared, runner=_native)[0].completion is Completion.COMPLETE
    )
    catalog.write_text('{"changed":true}', encoding="utf-8")
    assert analyze_prepared((path,), root=tmp_path, declared=declared, runner=_native)[0].issues


def test_list_resources_are_checked_individually_and_duplicates_rejected(tmp_path: Path) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    resource = path.parent / "resource.yaml"
    resource.write_text(
        "apiVersion: v1\nkind: List\nitems:\n- apiVersion: v1\n  kind: ConfigMap\n  metadata:\n    name: example\n",
        encoding="utf-8",
    )
    target["artifacts"] = {
        name: sha256((path.parent / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(path, target)
    declared = (PreparedTarget("example", "deploy.yaml"),)
    assert (
        analyze_prepared((path,), root=tmp_path, declared=declared, runner=_native)[0].completion is Completion.COMPLETE
    )
    resource.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: example\n---\n" * 2, encoding="utf-8")
    target["artifacts"] = {
        name: sha256((path.parent / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(path, target)
    assert analyze_prepared((path,), root=tmp_path, declared=declared, runner=_native)[0].issues


def test_local_schema_closure_cannot_fetch_http(tmp_path: Path) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    (path.parent / "schema.json").write_text('{"$ref":"https://example.invalid/schema.json"}', encoding="utf-8")
    target["artifacts"] = {
        name: sha256((path.parent / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(path, target)
    assert analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )[0].issues


@pytest.mark.parametrize("explicit_first", [False, True], ids=("omitted-first", "explicit-first"))
def test_target_namespace_cannot_hide_duplicate_workload_identity(tmp_path: Path, explicit_first: bool) -> None:
    fixture = _receipt(tmp_path)
    path, target = fixture.path, fixture.target
    target["namespace"] = "work"
    body = "apiVersion: v1\nkind: Pod\nmetadata:\n  name: example\n"
    explicit = f"{body}  namespace: work\n"
    (path.parent / "resource.yaml").write_text(f"{explicit}---\n{body}" if explicit_first else f"{body}---\n{explicit}")
    target["artifacts"] = {
        name: sha256((path.parent / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(path, target)
    [report] = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=_native
    )
    assert report.completion is Completion.FAILED
    assert report.issues
    assert "duplicate Kubernetes object identities" in report.issues[0].message


@pytest.mark.parametrize("status", ["statusSkipped", "statusError", "unknown"])
def test_native_missing_schema_and_skipped_resources_never_pass(tmp_path: Path, status: str) -> None:
    path = _receipt(tmp_path).path

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "kubeconform" and "-strict" in argv:
            return ProcessOutput(0, json.dumps({"resources": [{"status": status}]}), "")
        return _native(argv, cwd=cwd)

    reports = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=runner
    )
    assert reports[0].issues
    assert not reports[0].diagnostics


def test_manifest_prepared_declarations_round_trip(tmp_path: Path) -> None:
    manifest = Manifest("8.2.0", (), ".", ".", prepared_targets=(PreparedTarget("example", "deploy.yaml"),))
    (tmp_path / ".sarj-standards.toml").write_text(manifest.render(), encoding="utf-8")
    assert load(tmp_path) == manifest


def test_duplicate_declarations_fail(tmp_path: Path) -> None:
    manifest = Manifest(
        "8.2.0",
        (),
        ".",
        ".",
        prepared_targets=(PreparedTarget("example", "deploy.yaml"), PreparedTarget("example", "deploy.yaml")),
    )
    (tmp_path / ".sarj-standards.toml").write_text(manifest.render(), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate prepared target"):
        load(tmp_path)


@pytest.mark.parametrize("field", ["filename", "version", "kind", "name"])
@pytest.mark.parametrize("missing", [False, True], ids=("mismatched", "missing"))
def test_native_schema_result_must_identify_submitted_resource(field: str, *, missing: bool, tmp_path: Path) -> None:
    path = _receipt(tmp_path).path

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        output = _native(argv, cwd=cwd)
        if argv[0] != "kubeconform" or "-strict" not in argv:
            return output
        parsed = parse_json(output.stdout)
        assert is_object_mapping(parsed)
        resources = parsed["resources"]
        assert is_object_list(resources)
        native: object = resources[0]
        assert is_object_mapping(native)
        parsed["resources"] = [
            {
                key: "another-resource" if key == field else value
                for key, value in native.items()
                if not (missing and key == field)
            }
        ]
        return ProcessOutput(0, json.dumps(parsed), "")

    [report] = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=runner
    )
    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    assert "resource identity" in report.issues[0].message


def test_wrong_schema_resource_identity_supersedes_schema_violation(tmp_path: Path) -> None:
    path = _receipt(tmp_path).path

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        output = _native(argv, cwd=cwd)
        if argv[0] != "kubeconform" or "-strict" not in argv:
            return output
        return ProcessOutput(
            1,
            json.dumps(
                {
                    "resources": [
                        {
                            "filename": argv[-1],
                            "version": "v1",
                            "kind": "ConfigMap",
                            "name": "other",
                            "status": "statusInvalid",
                            "msg": "invalid other object",
                        }
                    ],
                    "summary": {"valid": 0, "invalid": 1, "errors": 0, "skipped": 0},
                }
            ),
            "",
        )

    [report] = analyze_prepared(
        (path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),), runner=runner
    )
    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    assert "resource identity" in report.issues[0].message


def _scalar_receipt(root: Path, *, name: object, value: object, privileged: bool = False) -> _ReceiptFixture:
    fixture = _receipt(root)
    directory = fixture.path.parent
    resource = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "public-pod", "annotations": {"example.com/state": "Y"}},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "public-example:1",
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "runAsNonRoot": True,
                        "privileged": privileged,
                    },
                    "env": [{"name": name, "value": value}],
                }
            ]
        },
    }
    (directory / "resource.yaml").write_text(json.dumps(resource), encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "properties": {
                    "containers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "env": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
                                    },
                                }
                            },
                        },
                    }
                },
            }
        },
    }
    (directory / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    fixture.target["schema_bindings"] = {"v1/Pod": "schema.json"}
    fixture.target["artifacts"] = {
        name: sha256((directory / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(fixture.path, fixture.target)
    return fixture


@pytest.mark.parametrize("value", ["Y", "N", "y", "n", "yes", "no", "true", "false", "001", "1e3", "2026-10-09", ""])
def test_native_prepared_resources_preserve_string_scalar_types(tmp_path: Path, value: str) -> None:
    fixture = _scalar_receipt(tmp_path, name="Y", value=value)
    original = (fixture.path.parent / "resource.yaml").read_bytes()
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.COMPLETE
    assert not reports[0].diagnostics
    assert not reports[0].issues
    assert (fixture.path.parent / "resource.yaml").read_bytes() == original


def test_quoted_scalar_security_findings_keep_upstream_ownership(tmp_path: Path) -> None:
    fixture = _scalar_receipt(tmp_path, name="N", value="Y", privileged=True)
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.COMPLETE
    findings = reports[0].diagnostics
    assert {finding.code for finding in findings} == {"privileged-container", "privilege-escalation-container"}
    assert len(findings) == 2
    assert all(finding.source == "kube-linter" and finding.location.path == "deploy.yaml" for finding in findings)
    assert all(finding.location.position is None for finding in findings)


@pytest.mark.parametrize(("name", "value"), [(True, "value"), ("APP", 42)])
def test_prepared_serialization_cannot_turn_invalid_scalar_types_into_strings(
    tmp_path: Path, name: object, value: object
) -> None:
    fixture = _scalar_receipt(tmp_path, name=name, value=value)
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues


def test_prepared_null_value_retains_native_schema_diagnostic(tmp_path: Path) -> None:
    fixture = _scalar_receipt(tmp_path, name="APP", value=None)
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.COMPLETE
    assert [finding.code for finding in reports[0].diagnostics] == ["schema"]


def test_prepared_yaml_date_scalar_retains_native_supported_behavior(tmp_path: Path) -> None:
    fixture = _scalar_receipt(tmp_path, name="APP", value="value")
    resource = fixture.path.parent / "resource.yaml"
    resource.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: public-pod\nspec:\n  containers:\n  - name: app\n"
        "    image: public-example:1\n    securityContext:\n      allowPrivilegeEscalation: false\n"
        "      runAsNonRoot: true\n    env:\n    - name: APP\n      value: 2026-10-09\n",
        encoding="utf-8",
    )
    fixture.target["artifacts"] = {
        name: sha256((fixture.path.parent / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
    }
    _write_receipt(fixture.path, fixture.target)
    reports = analyze_prepared((fixture.path,), root=tmp_path, declared=(PreparedTarget("example", "deploy.yaml"),))
    assert reports[0].completion is Completion.COMPLETE
    assert not reports[0].diagnostics
