from copy import deepcopy
import json
from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.external import run_process
from sarj_standards.libs.linting.prepared_kubernetes import (
    OMISSION_CHECK,
    ExceptionSet,
    build_config,
    normalize_findings,
    policy_resource,
)
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from pathlib import Path


def _object(value: object) -> dict[object, object]:
    assert is_object_mapping(value)
    return value


def _first_report(native: dict[object, object]) -> dict[object, object]:
    reports = native["Reports"]
    assert is_object_list(reports)
    assert reports
    return _object(reports[0])


def _pod() -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "test", "namespace": "work"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "test",
                    "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False},
                }
            ],
        },
    }


def _target() -> dict[str, object]:
    return {"id": "test-target", "source": "release.tf", "namespace": "work"}


@pytest.mark.parametrize(
    ("api_version", "kind", "path"),
    [
        ("custom.example/v1", "Pod", ("spec",)),
        ("custom.example/v1", "Deployment", ("spec", "template", "spec")),
        ("extensions/v1beta1", "Deployment", ("spec", "template", "spec")),
        ("custom.example/v1", "Worker", ("spec", "template", "spec")),
    ],
    ids=("crd-pod-collision", "crd-deployment-collision", "obsolete-version", "custom-podspec-owner"),
)
def test_unsupported_gvk_podspec_requires_explicit_adapter(api_version: str, kind: str, path: tuple[str, ...]) -> None:
    spec: object = _pod()["spec"]
    for key in reversed(path):
        spec = {key: spec}
    assert is_object_mapping(spec)
    resource: dict[str, object] = {"apiVersion": api_version, "kind": kind}
    resource.update({key: value for key, value in spec.items() if isinstance(key, str)})
    with pytest.raises(ValueError, match="unsupported Kubernetes GVK"):
        build_config(resource)


def test_custom_kind_name_without_podspec_is_not_builtin_workload() -> None:
    resource: dict[str, object] = {"apiVersion": "custom.example/v1", "kind": "Pod", "spec": {"value": "data"}}
    assert "customChecks" not in build_config(resource)


def _native(resource: dict[str, object], tmp_path: Path) -> str:
    config, input_path = tmp_path / "policy.yaml", tmp_path / "input.yaml"
    config.write_text(yaml.safe_dump(build_config(resource)), encoding="utf-8")
    input_path.write_text(yaml.safe_dump(policy_resource(resource)), encoding="utf-8")
    result = run_process(
        [
            "kube-linter",
            "lint",
            "--format",
            "json",
            "--config",
            str(config),
            "--fail-if-no-objects-found",
            "--fail-on-invalid-resource",
            str(input_path),
        ],
        cwd=tmp_path,
    )
    assert result.returncode in {0, 1}, result.stderr
    assert result.stdout.strip(), result.stderr
    return result.stdout


def _exception(
    *, check: str = OMISSION_CHECK, container: str = "app", container_kind: str = "containers"
) -> dict[str, object]:
    return {
        "target": "test-target",
        "apiVersion": "v1",
        "kind": "Pod",
        "namespace": "work",
        "name": "test",
        "check": check,
        "containerKind": container_kind,
        "container": container,
        "reason": "Reviewed workload constraint with a tracked remediation.",
    }


@pytest.mark.parametrize(
    ("security", "expected"),
    [
        ({"runAsNonRoot": True, "allowPrivilegeEscalation": False}, set[str]()),
        ({"runAsNonRoot": True}, {OMISSION_CHECK}),
        ({"runAsNonRoot": True, "allowPrivilegeEscalation": True}, {"privilege-escalation-container"}),
        (
            {"runAsNonRoot": True, "allowPrivilegeEscalation": False, "privileged": True},
            {"privileged-container", "privilege-escalation-container"},
        ),
        (
            {"runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"add": ["SYS_ADMIN"]}},
            {"privilege-escalation-container"},
        ),
        ({"allowPrivilegeEscalation": False}, {"run-as-non-root"}),
        ({"allowPrivilegeEscalation": False, "runAsNonRoot": True, "runAsUser": 0}, {"run-as-non-root"}),
    ],
    ids=(
        "secure",
        "omitted-escalation",
        "allowed-escalation",
        "privileged",
        "sys-admin",
        "omitted-non-root",
        "root-uid",
    ),
)
def test_native_security_decisions_and_pinned_message_grammars(
    security: dict[str, object], expected: set[str], tmp_path: Path
) -> None:
    resource = _pod()
    resource["spec"] = {"containers": [{"name": "app", "image": "test", "securityContext": security}]}
    exceptions = ExceptionSet.parse(_target())
    findings = normalize_findings(_native(resource, tmp_path), _target(), resource, "resource-0", exceptions)
    assert {finding.code for finding in findings} == expected
    assert all(finding.location.position is None for finding in findings)
    assert all(str(tmp_path) not in finding.message for finding in findings)
    exceptions.finish()


def test_omission_covers_normal_init_and_ephemeral_containers(tmp_path: Path) -> None:
    resource = _pod()
    resource["spec"] = {
        kind: [{"name": name, "image": "test", "securityContext": {"runAsNonRoot": True}}]
        for kind, name in [("containers", "app"), ("initContainers", "init"), ("ephemeralContainers", "debug")]
    }
    findings = normalize_findings(
        _native(resource, tmp_path), _target(), resource, "resource-0", ExceptionSet.parse(_target())
    )
    assert len(findings) == 3
    assert {finding.code for finding in findings} == {OMISSION_CHECK}
    assert {finding.message.split("]", 1)[0] for finding in findings} == {
        "[resource-0:containers:app",
        "[resource-0:initContainers:init",
        "[resource-0:ephemeralContainers:debug",
    }


@pytest.mark.parametrize(
    "kind", ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "ReplicationController"]
)
def test_omission_uses_original_workload_pod_spec_path(kind: str, tmp_path: Path) -> None:
    resource = _pod()
    pod_spec = {"containers": [{"name": "app", "image": "test", "securityContext": {"runAsNonRoot": True}}]}
    resource["kind"] = kind
    resource["apiVersion"] = (
        "batch/v1" if kind in {"Job", "CronJob"} else "v1" if kind == "ReplicationController" else "apps/v1"
    )
    resource["spec"] = (
        {"jobTemplate": {"spec": {"template": {"spec": pod_spec}}}}
        if kind == "CronJob"
        else {"template": {"spec": pod_spec}}
    )
    findings = normalize_findings(
        _native(resource, tmp_path), _target(), resource, "resource-0", ExceptionSet.parse(_target())
    )
    assert [finding.code for finding in findings] == [OMISSION_CHECK]


def test_windows_gating_preserves_duplicate_environment_check(tmp_path: Path) -> None:
    resource = _pod()
    resource["spec"] = {
        "os": {"name": "windows"},
        "containers": [
            {"name": "app", "image": "test", "env": [{"name": "X", "value": "a"}, {"name": "X", "value": "b"}]}
        ],
    }
    findings = normalize_findings(
        _native(resource, tmp_path), _target(), resource, "resource-0", ExceptionSet.parse(_target())
    )
    assert [finding.code for finding in findings] == ["duplicate-env-var"]


@pytest.mark.parametrize(
    "annotation",
    [
        "ignore-check.kube-linter.io/all",
        "ignore-check.kube-linter.io/explicit-privilege-escalation-disabled",
        "kube-linter.io/ignore-all",
    ],
)
def test_ignore_annotations_cannot_disable_shared_policy(annotation: str, tmp_path: Path) -> None:
    resource = _pod()
    resource["metadata"] = {
        "name": "test",
        "namespace": "work",
        "annotations": {annotation: "skip", "example.com/owner": "team"},
    }
    resource["spec"] = {"containers": [{"name": "app", "image": "test", "securityContext": {"runAsNonRoot": True}}]}
    original = deepcopy(resource)
    findings = normalize_findings(
        _native(resource, tmp_path), _target(), resource, "resource-0", ExceptionSet.parse(_target())
    )
    assert [finding.code for finding in findings] == [OMISSION_CHECK]
    assert resource == original
    assert _object(_object(policy_resource(resource)["metadata"])["annotations"]) == {"example.com/owner": "team"}


@pytest.mark.parametrize("native_blanket_waiver", [False, True])
def test_exception_is_exact_for_one_check_and_one_container(tmp_path: Path, *, native_blanket_waiver: bool) -> None:
    resource = _pod()
    if native_blanket_waiver:
        resource["metadata"] = {
            "name": "test",
            "namespace": "work",
            "annotations": {"kube-linter.io/ignore-all": "Native blanket waiver is not an exact receipt exception."},
        }
    resource["spec"] = {
        "containers": [
            {"name": name, "image": "test", "securityContext": {"runAsNonRoot": True}} for name in ["app", "worker"]
        ]
    }
    target = {**_target(), "exceptions": [_exception()]}
    exceptions = ExceptionSet.parse(target)
    findings = normalize_findings(_native(resource, tmp_path), target, resource, "resource-0", exceptions)
    assert len(findings) == 1
    assert ":worker]" in findings[0].message
    exceptions.finish()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("namespace", "elsewhere"),
        ("containerKind", "initContainers"),
        ("container", "other"),
        ("kind", "Deployment"),
        ("apiVersion", "other/v1"),
        ("name", "other"),
        ("check", "privileged-container"),
    ],
)
def test_exception_cannot_spread_to_other_identity(key: str, value: str, tmp_path: Path) -> None:
    resource = _pod()
    resource["spec"] = {"containers": [{"name": "app", "image": "test", "securityContext": {"runAsNonRoot": True}}]}
    target = {**_target(), "exceptions": [{**_exception(), key: value}]}
    exceptions = ExceptionSet.parse(target)
    findings = normalize_findings(_native(resource, tmp_path), target, resource, "resource-0", exceptions)
    assert [finding.code for finding in findings] == [OMISSION_CHECK]
    with pytest.raises(ValueError, match="stale"):
        exceptions.finish()


@pytest.mark.parametrize(
    "entries",
    [
        [{**_exception(), "reason": " "}],
        [_exception(), _exception()],
        [{**_exception(), "check": "ignore-all"}],
        [{**_exception(), "target": "other"}],
        [{**_exception(), "extra": True}],
    ],
    ids=("blank-reason", "duplicate", "unknown-check", "wrong-target", "extra-field"),
)
def test_invalid_exception_contract_fails_closed(entries: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match=r".+"):
        ExceptionSet.parse({**_target(), "exceptions": entries})


@pytest.mark.parametrize("mutation", ["message", "cel-error", "identity", "checks", "summary"])
def test_unknown_native_protocol_is_rejected_before_exception(mutation: str, tmp_path: Path) -> None:
    resource = _pod()
    resource["spec"] = {"containers": [{"name": "app", "image": "test", "securityContext": {"runAsNonRoot": True}}]}
    native = _object(parse_json(_native(resource, tmp_path)))
    match mutation:
        case "message" | "cel-error":
            _object(_first_report(native)["Diagnostic"])["Message"] = (
                "changed upstream grammar" if mutation == "message" else "error evaluating CEL check expression: error"
            )
        case "identity":
            _object(_object(_first_report(native)["Object"])["K8sObject"])["Name"] = "other"
        case "checks":
            native["Checks"] = []
        case _:
            _object(native["Summary"])["ChecksStatus"] = "Passed"
    target = {**_target(), "exceptions": [_exception()]}
    exceptions = ExceptionSet.parse(target)
    with pytest.raises(ValueError, match=r".+"):
        normalize_findings(json.dumps(native), target, resource, "resource-0", exceptions)
    assert not exceptions.used


def test_ambiguous_container_attribution_cannot_be_suppressed() -> None:
    resource = _pod()
    resource["spec"] = {
        "containers": [{"name": "app", "image": "test"}],
        "initContainers": [{"name": "app", "image": "test"}],
    }
    with pytest.raises(ValueError, match="ambiguous"):
        build_config(resource)
