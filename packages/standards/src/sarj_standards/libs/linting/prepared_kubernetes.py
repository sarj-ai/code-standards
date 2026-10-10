from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, NotRequired, Self, TypedDict

from sarj_standards.libs.diagnostics.models import Diagnostic, Location, Severity
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.kubernetes_context import CONTAINER_KINDS, POD_SPEC_PATHS
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Mapping


NATIVE_CHECKS = (
    "privileged-container",
    "privilege-escalation-container",
    "run-as-non-root",
    "duplicate-env-var",
)
OMISSION_CHECK = "explicit-privilege-escalation-disabled"
_OMISSION_MESSAGE = "CEL check expression returned: missing allowPrivilegeEscalation=false"

_PATTERNS = MappingProxyType(
    {
        "privileged-container": re.compile(r'container "(?P<container>[^\"]+)" is privileged'),
        "privilege-escalation-container": re.compile(
            r'container "(?P<container>[^\"]+)" (?:has AllowPrivilegeEscalation set to true\.|is Privileged hence allows privilege escalation\.|has SYS_ADMIN capability hence allows privilege escalation\.)'
        ),
        "run-as-non-root": re.compile(
            r'container "(?P<container>[^\"]+)" (?:is not set to runAsNonRoot|is set to runAsNonRoot, but runAsUser set to 0)'
        ),
        "duplicate-env-var": re.compile(
            r'Duplicate environment variable .+ in container "(?P<container>[^\"]+)" found'
        ),
    }
)
_EXCEPTION_FIELDS = frozenset(
    {"target", "apiVersion", "kind", "namespace", "name", "check", "containerKind", "container", "reason"}
)


def _table(value: object, label: str) -> dict[str, object]:
    if not is_object_mapping(value) or any(not isinstance(key, str) for key in value):
        msg = f"{label} must be a string-keyed object"
        raise ValueError(msg)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _text(table: Mapping[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{key} must be a nonempty string"
        raise ValueError(msg)
    return value


@dataclass(frozen=True, slots=True)
class PodSpecProjection:
    spec: dict[str, object] | None
    path: tuple[str, ...] = ()


class KubeChecks(TypedDict):
    doNotAutoAddDefaults: bool
    include: list[str]


class KubeCheck(TypedDict):
    name: str
    description: str
    remediation: str
    scope: dict[str, list[str]]
    template: str
    params: dict[str, str]


class KubeConfig(TypedDict):
    checks: KubeChecks
    customChecks: NotRequired[list[KubeCheck]]


def _pod_spec(resource: Mapping[str, object]) -> PodSpecProjection:
    path = POD_SPEC_PATHS.get((_text(resource, "apiVersion"), _text(resource, "kind")))
    if path is None:
        for candidate in set(POD_SPEC_PATHS.values()):
            value: object = resource
            for key in candidate:
                value = value.get(key) if is_object_mapping(value) else None
            if is_object_mapping(value) and any(is_object_list(value.get(key)) for key in CONTAINER_KINDS):
                msg = "unsupported Kubernetes GVK contains a PodSpec; explicit policy adapter is required"
                raise ValueError(msg)
        return PodSpecProjection(None)
    current: object = resource
    for name in path:
        current = _table(current, "PodSpec owner").get(name)
        if current is None:
            msg = "known Kubernetes workload lacks its PodSpec"
            raise ValueError(msg)
    return PodSpecProjection(_table(current, "PodSpec"), path)


def _windows(spec: Mapping[str, object]) -> bool:
    os = spec.get("os")
    return os is not None and _table(os, "Pod OS").get("name") == "windows"


def _containers(spec: Mapping[str, object]) -> tuple[tuple[str, dict[str, object]], ...]:
    result: list[tuple[str, dict[str, object]]] = []
    seen: set[str] = set()
    for kind in CONTAINER_KINDS:
        values = spec.get(kind, [])
        if not is_object_list(values):
            msg = f"PodSpec {kind} must be a sequence"
            raise ValueError(msg)
        for value in values:
            container = _table(value, "container")
            name = _text(container, "name")
            if name in seen:
                msg = f"container attribution is ambiguous for {name}"
                raise ValueError(msg)
            seen.add(name)
            result.append((kind, container))
    return tuple(result)


def build_config(resource: Mapping[str, object]) -> KubeConfig:
    projection = _pod_spec(resource)
    spec = projection.spec
    if spec is not None:
        _containers(spec)  # Validate unique attribution before native execution.
    if spec is not None and _windows(spec):
        return {"checks": {"doNotAutoAddDefaults": True, "include": ["duplicate-env-var"]}}
    config: KubeConfig = {"checks": {"doNotAutoAddDefaults": True, "include": list(NATIVE_CHECKS)}}
    if spec is None:
        return config
    pod = "object." + ".".join(projection.path)
    conditions = " || ".join(
        f"(has({pod}.{kind}) && {pod}.{kind}.exists(c, !has(c.securityContext) || !has(c.securityContext.allowPrivilegeEscalation)))"
        for kind in CONTAINER_KINDS
    )
    check: KubeCheck = {
        "name": OMISSION_CHECK,
        "description": "Require an explicit privilege-escalation decision in Linux containers",
        "remediation": "Set securityContext.allowPrivilegeEscalation to false, or record an exact justified exception.",
        "scope": {"objectKinds": ["Any"]},
        "template": "cel-expression",
        "params": {"check": f"({conditions}) ? 'missing allowPrivilegeEscalation=false' : ''"},
    }
    config["customChecks"] = [check]
    config["checks"] = {"doNotAutoAddDefaults": True, "include": [*NATIVE_CHECKS, OMISSION_CHECK]}
    return config


def policy_resource(resource: Mapping[str, object]) -> dict[str, object]:
    return _table(_policy_value(resource), "policy resource")


def _policy_value(value: object) -> object:
    if is_object_list(value):
        return [_policy_value(item) for item in value]
    if not is_object_mapping(value):
        return value
    result = {key: _policy_value(item) for key, item in value.items()}
    metadata = result.get("metadata")
    if is_object_mapping(metadata) and is_object_mapping(annotations := metadata.get("annotations")):
        metadata["annotations"] = {
            key: item for key, item in annotations.items() if not isinstance(key, str) or not _ignore_annotation(key)
        }
    return result


def _ignore_annotation(key: str) -> bool:
    prefix, separator, _name = key.partition("/")
    return key == "kube-linter.io/ignore-all" or (separator == "/" and prefix == "ignore-check.kube-linter.io")


@dataclass(frozen=True, slots=True)
class ExceptionKey:
    target: str
    api_version: str
    kind: str
    namespace: str
    name: str
    check: str
    container_kind: str
    container: str


@dataclass(slots=True)
class ExceptionSet:
    entries: dict[ExceptionKey, str]
    used: set[ExceptionKey] = field(default_factory=set)

    @classmethod
    def parse(cls, target: Mapping[str, object]) -> Self:
        raw = target.get("exceptions", [])
        if not is_object_list(raw):
            msg = "prepared exceptions must be a sequence"
            raise ValueError(msg)
        entries: dict[ExceptionKey, str] = {}
        for value in raw:
            item = _table(value, "Kubernetes exception")
            if set(item) != _EXCEPTION_FIELDS:
                msg = "Kubernetes exception must declare every exact identity field and reason"
                raise ValueError(msg)
            key = ExceptionKey(
                _text(item, "target"),
                _text(item, "apiVersion"),
                _text(item, "kind"),
                _text(item, "namespace"),
                _text(item, "name"),
                _text(item, "check"),
                _text(item, "containerKind"),
                _text(item, "container"),
            )
            if (
                key.target != _text(target, "id")
                or key.check not in {*NATIVE_CHECKS, OMISSION_CHECK}
                or key.container_kind not in CONTAINER_KINDS
            ):
                msg = "Kubernetes exception has an undeclared target, check or container category"
                raise ValueError(msg)
            if key in entries:
                msg = "Kubernetes exception duplicates an exact identity"
                raise ValueError(msg)
            entries[key] = _text(item, "reason")
        return cls(entries)

    def permits(self, key: ExceptionKey) -> bool:
        if key not in self.entries:
            return False
        self.used.add(key)
        return True

    def finish(self) -> None:
        if set(self.entries) != self.used:
            msg = "Kubernetes exceptions contain stale or unproven matches"
            raise ValueError(msg)


def normalize_findings(
    payload: str, target: Mapping[str, object], resource: Mapping[str, object], identity: str, exceptions: ExceptionSet
) -> tuple[Diagnostic, ...]:
    spec = _pod_spec(resource).spec
    findings: list[Diagnostic] = []
    for report in _native_reports(payload, spec):
        _verify_object(report, resource)
        check = _text(report, "Check")
        message = _text(_table(report.get("Diagnostic"), "native diagnostic"), "Message")
        matches = _matches(check, message, spec)
        for kind, container in matches:
            key = _key(target, resource, check, kind, _text(container, "name"))
            if exceptions.permits(key):
                continue
            findings.append(
                Diagnostic(
                    check,
                    f"[{identity}:{kind}:{key.container}] {message}",
                    Severity.ERROR,
                    "kube-linter",
                    Location(_text(target, "source")),
                    rule_id=check,
                )
            )
    return tuple(findings)


def _verify_object(report: Mapping[str, object], resource: Mapping[str, object]) -> None:
    native = _table(_table(report.get("Object"), "native report object").get("K8sObject"), "native Kubernetes object")
    metadata = _table(resource.get("metadata"), "resource metadata")
    gvk = _table(native.get("GroupVersionKind"), "native object GVK")
    api = _text(resource, "apiVersion").split("/", 1)
    group, version = ("", api[0]) if len(api) == 1 else (api[0], api[1])
    if (native.get("Name"), native.get("Namespace"), gvk.get("Group"), gvk.get("Version"), gvk.get("Kind")) != (
        _text(metadata, "name"),
        metadata.get("namespace", ""),
        group,
        version,
        _text(resource, "kind"),
    ):
        msg = "native kube-linter resource identity does not match original input"
        raise ValueError(msg)


def _matches(check: str, message: str, spec: Mapping[str, object] | None) -> tuple[tuple[str, dict[str, object]], ...]:
    containers = () if spec is None else _containers(spec)
    if check == OMISSION_CHECK:
        if message != _OMISSION_MESSAGE or spec is None or _windows(spec):
            msg = "native CEL check failed evaluation or returned an unknown message"
            raise ValueError(msg)
        matches = tuple(
            (kind, container)
            for kind, container in containers
            if _table(container.get("securityContext") or {}, "security context").get("allowPrivilegeEscalation")
            is None
        )
        if not matches:
            msg = "native omission finding cannot be attributed to original containers"
            raise ValueError(msg)
        return matches
    match = _PATTERNS[check].fullmatch(message)
    if match is None:
        msg = f"unknown pinned kube-linter message grammar for {check}"
        raise ValueError(msg)
    matches = tuple((kind, container) for kind, container in containers if container.get("name") == match["container"])
    if len(matches) != 1:
        msg = "native container finding cannot be attributed uniquely"
        raise ValueError(msg)
    return matches


def _native_reports(payload: str, spec: Mapping[str, object] | None) -> tuple[dict[str, object], ...]:
    parsed = _table(parse_json(payload), "kube-linter output")
    summary = _table(parsed.get("Summary"), "kube-linter summary")
    status = summary.get("ChecksStatus")
    if summary.get("KubeLinterVersion") != "0.8.3" or status not in {"Passed", "Failed"}:
        msg = "kube-linter summary is incomplete or has the wrong version"
        raise ValueError(msg)
    reports: object = parsed.get("Reports")
    if reports is None and status == "Passed":
        reports = []
    if not is_object_list(reports) or (status == "Passed" and reports) or (status == "Failed" and not reports):
        msg = "kube-linter findings do not agree with the completion summary"
        raise ValueError(msg)
    allowed = (
        {"duplicate-env-var"}
        if spec is not None and _windows(spec)
        else {*NATIVE_CHECKS, *((OMISSION_CHECK,) if spec is not None else ())}
    )
    checks = parsed.get("Checks")
    if not is_object_list(checks):
        msg = "kube-linter did not account for its enabled checks"
        raise ValueError(msg)
    names = [_text(_table(check, "native enabled check"), "name") for check in checks]
    if len(names) != len(allowed) or set(names) != allowed:
        msg = "kube-linter enabled check set is incomplete or unexpected"
        raise ValueError(msg)
    result = tuple(_table(value, "kube-linter report") for value in reports)
    if any(_text(report, "Check") not in allowed for report in result):
        msg = "kube-linter reported an unexpected check"
        raise ValueError(msg)
    return result


def _key(
    target: Mapping[str, object], resource: Mapping[str, object], check: str, kind: str, container: str
) -> ExceptionKey:
    metadata = _table(resource.get("metadata"), "resource metadata")
    namespace = _text({"namespace": metadata.get("namespace") or target.get("namespace") or "default"}, "namespace")
    return ExceptionKey(
        _text(target, "id"),
        _text(resource, "apiVersion"),
        _text(resource, "kind"),
        namespace,
        _text(metadata, "name"),
        check,
        kind,
        container,
    )
