from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catch bounded native-runner failures.
import tempfile
from typing import TYPE_CHECKING

import yaml

from sarj_standards.libs.diagnostics.models import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_json, parse_unique_json
from sarj_standards.libs.linting.chart_schemas import validate_chart_schemas
from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool, invoke
from sarj_standards.libs.linting.external import ProcessRunner, run_process
from sarj_standards.libs.linting.prepared_kubernetes import (
    ExceptionSet,
    build_config,
    normalize_findings,
    policy_resource,
)
from sarj_standards.libs.schema_boundary import (
    DEFAULT_DIALECT,
    KUBERNETES_DEFAULT_DIALECT,
    schema_references,
    validate_local_schema,
)
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml_documents


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_standards.libs.adoption.manifest import PreparedTarget
    from sarj_standards.libs.linting.external import ProcessOutput


_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_SHA256_LENGTH = 64
_HELM_RELEASE_LENGTH = 53
_TARGET_FIELDS = frozenset(
    {
        "id",
        "source",
        "source_sha256",
        "source_inputs",
        "kind",
        "profile",
        "stage",
        "helm_version",
        "kubernetes_version",
        "api_versions",
        "release",
        "namespace",
        "archive",
        "archive_sha256",
        "values",
        "set",
        "manifests",
        "schema_bindings",
        "artifacts",
        "exceptions",
    }
)


def _table(value: object, label: str) -> dict[str, object]:
    if not is_object_mapping(value) or any(not isinstance(key, str) for key in value):
        msg = f"{label} must be an object"
        raise ValueError(msg)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _text(table: Mapping[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"prepared target {key} must be a nonempty string"
        raise ValueError(msg)
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not is_object_list(value) or any(not isinstance(item, str) or not item for item in value):
        msg = f"{label} must be a list of nonempty strings"
        raise ValueError(msg)
    return tuple(item for item in value if isinstance(item, str))


def contained_file(directory: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        msg = f"prepared path must stay beneath its directory: {name}"
        raise ValueError(msg)
    cursor = directory.resolve()
    for part in path.parts:
        cursor /= part
        if cursor.is_symlink():
            msg = f"prepared path cannot contain a symlink: {name}"
            raise ValueError(msg)
    if not cursor.is_file() or not cursor.resolve().is_relative_to(directory.resolve()):
        msg = f"prepared artifact is missing or outside its directory: {name}"
        raise ValueError(msg)
    return cursor


def _verify_hash(path: Path, digest: str) -> None:
    if len(digest) != _SHA256_LENGTH or digest != sha256(path.read_bytes()).hexdigest():
        msg = f"prepared artifact hash does not match: {path.name}"
        raise ValueError(msg)


def analyze_prepared(
    receipts: Sequence[Path],
    *,
    root: Path,
    declared: Sequence[PreparedTarget],
    selected: Sequence[str] = (),
    runner: ProcessRunner = run_process,
) -> tuple[ToolReport, ...]:
    try:
        return _analyze_receipts(receipts, root=root, declared=declared, selected=selected, runner=runner)
    except (OSError, TypeError, ValueError, yaml.YAMLError, subprocess.SubprocessError, RecursionError) as exc:
        return (
            ToolReport(
                "prepared-devops",
                Completion.FAILED,
                issues=(ExecutionIssue("prepared-devops", "invalid-input", str(exc)),),
            ),
        )


def _analyze_receipts(
    receipts: Sequence[Path],
    *,
    root: Path,
    declared: Sequence[PreparedTarget],
    selected: Sequence[str],
    runner: ProcessRunner,
) -> tuple[ToolReport, ...]:
    wanted = set(selected) if selected else {target.id for target in declared}
    if not wanted:
        msg = "prepared validation requires at least one declared target"
        raise ValueError(msg)
    if len(selected) != len(set(selected)) or wanted - {target.id for target in declared}:
        msg = "prepared target selection contains duplicate or undeclared IDs"
        raise ValueError(msg)
    targets: dict[str, tuple[Path, dict[str, object]]] = {}
    for receipt in receipts:
        path = receipt if receipt.is_absolute() else root / receipt
        for identifier, target in _receipt(path, root, declared).items():
            if identifier in targets:
                msg = f"prepared target appears in multiple receipts: {identifier}"
                raise ValueError(msg)
            targets[identifier] = (path.parent, target)
    if missing := wanted - targets.keys():
        msg = f"missing prepared targets: {', '.join(sorted(missing))}"
        raise ValueError(msg)
    return tuple(_analyze_target(*targets[identifier], root=root, runner=runner) for identifier in sorted(wanted))


def _receipt(path: Path, root: Path, declared: Sequence[PreparedTarget]) -> dict[str, dict[str, object]]:
    if path.is_symlink() or path.stat().st_size > _MAX_RECEIPT_BYTES:
        msg = "prepared receipt must be a bounded regular file"
        raise ValueError(msg)
    receipt = _table(parse_unique_json(path.read_text(encoding="utf-8")), "prepared receipt")
    if type(receipt.get("version")) is not int or receipt.get("version") != 1 or set(receipt) != {"version", "targets"}:
        msg = "prepared receipt requires version 1 and targets"
        raise ValueError(msg)
    targets = receipt.get("targets")
    if not is_object_list(targets):
        msg = "prepared receipt targets must be a list"
        raise ValueError(msg)
    allowed = {target.id: target.source for target in declared}
    result: dict[str, dict[str, object]] = {}
    for item in targets:
        target = _table(item, "prepared target")
        if set(target) - _TARGET_FIELDS:
            msg = "prepared target contains unsupported fields"
            raise ValueError(msg)
        identifier = _text(target, "id")
        source = _text(target, "source")
        if identifier in result or allowed.get(identifier) != source:
            msg = f"prepared target is duplicated, undeclared, or bound to the wrong source: {identifier}"
            raise ValueError(msg)
        _verify_hash(contained_file(root, source), _text(target, "source_sha256"))
        if "source_inputs" in target:
            inputs = _table(target["source_inputs"], "prepared authored input hashes")
            if inputs.get(source) != target.get("source_sha256"):
                msg = "prepared authored inputs must include the declared source hash"
                raise ValueError(msg)
            for name in inputs:
                _verify_hash(contained_file(root, name), _text(inputs, name))
        _verify_artifacts(path.parent, target)
        result[identifier] = target
    return result


def _verify_artifacts(directory: Path, target: Mapping[str, object]) -> None:
    artifacts = _table(target.get("artifacts"), "prepared artifact hashes")
    required = (*_strings(target.get("values", []), "values"), *_strings(target.get("manifests", []), "manifests"))
    bindings = _table(target.get("schema_bindings"), "prepared schema bindings")
    for name in (*required, *bindings.values()):
        if not isinstance(name, str) or name not in artifacts:
            msg = f"prepared artifact lacks its content hash: {name}"
            raise ValueError(msg)
    for name in artifacts:
        _verify_hash(contained_file(directory, name), _text(artifacts, name))


def _analyze_target(directory: Path, target: Mapping[str, object], *, root: Path, runner: ProcessRunner) -> ToolReport:
    identifier = _text(target, "id")
    source = _text(target, "source")
    try:
        input_hash = sha256(json.dumps(dict(target), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        diagnostics = tuple(
            replace(
                item,
                fingerprint=sha256(f"{input_hash}:{item.source}:{item.rule_id}:{item.message}".encode()).hexdigest(),
            )
            for item in _target_diagnostics(directory, target, root=root, runner=runner)
        )
        return ToolReport(f"prepared-devops:{identifier}", Completion.COMPLETE, diagnostics=diagnostics, file_count=1)
    except (OSError, TypeError, ValueError, yaml.YAMLError, subprocess.SubprocessError, RecursionError) as exc:
        return ToolReport(
            f"prepared-devops:{identifier}",
            Completion.FAILED,
            issues=(ExecutionIssue("prepared-devops", "validation-failure", f"{source} [{identifier}]: {exc}"),),
        )


def _target_diagnostics(
    directory: Path, target: Mapping[str, object], *, root: Path, runner: ProcessRunner
) -> tuple[Diagnostic, ...]:
    kind = _text(target, "kind")
    if kind not in {"helm", "kubernetes", "cloud-run"}:
        msg = f"prepared target kind requires an explicit schema adapter: {kind}"
        raise ValueError(msg)
    with tempfile.TemporaryDirectory(prefix="sarj-devops-") as temporary:
        manifests = (
            _render_helm(directory, target, root=root, runner=runner)
            if kind == "helm"
            else _read_manifests(directory, target)
        )
        if kind == "cloud-run":
            return _validate_cloudrun(manifests, target, directory=directory)
        return _validate_manifests(
            manifests, target, directory=directory, work=Path(temporary), root=root, runner=runner
        )


def _validate_cloudrun(manifests: str, target: Mapping[str, object], *, directory: Path) -> tuple[Diagnostic, ...]:
    if len(manifests.encode()) > _MAX_MANIFEST_BYTES:
        msg = "Cloud Run manifests exceed 2 MiB"
        raise ValueError(msg)
    objects = [item for item in parse_yaml_documents(manifests) if item is not None]
    if not objects:
        msg = "Cloud Run target contains no documents"
        raise ValueError(msg)
    findings: list[Diagnostic] = []
    bindings = _table(target.get("schema_bindings"), "schema_bindings")
    closure = tuple(
        contained_file(directory, name)
        for name in _table(target.get("artifacts"), "artifacts")
        if name.endswith(".json")
    )
    for index, value in enumerate(objects):
        obj = _table(value, "Cloud Run resource")
        gvk = f"{_text(obj, 'apiVersion')}/{_text(obj, 'kind')}"
        if gvk not in {"serving.knative.dev/v1/Service", "run.googleapis.com/v1/Job"}:
            msg = "Cloud Run adapter requires a supported v1 Service or Job GVK"
            raise ValueError(msg)
        schema = contained_file(directory, _text(bindings, gvk))
        _closed_schema(schema, directory, target)
        findings.extend(
            _diagnostic(target, "devops-schema", "cloud-run", message, f"{_text(target, 'id')}:{index}")
            for message in validate_local_schema(obj, schema, closure)
        )
    return tuple(findings)


def _read_manifests(directory: Path, target: Mapping[str, object]) -> str:
    return "\n---\n".join(
        contained_file(directory, name).read_text(encoding="utf-8")
        for name in _strings(target.get("manifests"), "manifests")
    )


def _render_helm(directory: Path, target: Mapping[str, object], *, root: Path, runner: ProcessRunner) -> str:
    release = _text(target, "release")
    if len(release) > _HELM_RELEASE_LENGTH or re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", release) is None:
        msg = "prepared Helm release must be a valid release name, never a command option"
        raise ValueError(msg)
    tool = checked_tool("helm", root=root, runner=runner)
    if _text(target, "helm_version") != tool.version:
        msg = "prepared Helm version differs from checked tool"
        raise ValueError(msg)
    archive = contained_file(directory, _text(target, "archive"))
    _verify_hash(archive, _text(target, "archive_sha256"))
    validate_chart_schemas(archive)
    values = _strings(target.get("values", []), "values")
    args: list[str] = []
    for value in values:
        args.extend(("--values", str(contained_file(directory, value))))
    settings = target.get("set", [])
    if not is_object_list(settings):
        msg = "prepared set must be a list"
        raise ValueError(msg)
    for raw in settings:
        setting = _table(raw, "prepared set")
        setting_type = _text(setting, "type")
        if setting_type not in {"value", "string"}:
            msg = "prepared set type must be value or string"
            raise ValueError(msg)
        value = setting.get("value")
        if not isinstance(value, str):
            msg = "prepared set value must be a string"
            raise TypeError(msg)
        args.extend(
            (
                "--set-string" if setting_type == "string" else "--set",
                f"{_text(setting, 'name')}={value}",
            )
        )
    lint = invoke(
        tool,
        (
            "lint",
            "--strict",
            "--with-subcharts",
            "--kube-version",
            _text(target, "kubernetes_version"),
            str(archive),
            *args,
        ),
        root=root,
        runner=runner,
    )
    if lint.returncode:
        msg = f"Helm strict lint failed: {lint.stdout.strip()} {lint.stderr.strip()}"
        raise NativeToolError(msg)
    api_args = tuple(
        value for api in _strings(target.get("api_versions", []), "api_versions") for value in ("--api-versions", api)
    )
    command = (
        "template",
        _text(target, "release"),
        str(archive),
        "--namespace",
        _text(target, "namespace"),
        "--kube-version",
        _text(target, "kubernetes_version"),
        "--include-crds",
        "--skip-tests",
        *api_args,
        *args,
    )
    stage = _text(target, "stage")
    if stage not in {"install", "upgrade"}:
        msg = "Helm target stage must be install or upgrade"
        raise ValueError(msg)
    output = invoke(tool, (*command, *(("--is-upgrade",) if stage == "upgrade" else ())), root=root, runner=runner)
    if output.returncode:
        msg = f"Helm template failed: {output.stderr.strip()}"
        raise NativeToolError(msg)
    if parse_yaml_documents(output.stdout) != parse_yaml_documents(_read_manifests(directory, target)):
        msg = "Helm rendering differs from the hashed prepared manifests"
        raise ValueError(msg)
    return output.stdout


def _validate_manifests(
    manifests: str, target: Mapping[str, object], *, directory: Path, work: Path, root: Path, runner: ProcessRunner
) -> tuple[Diagnostic, ...]:
    if len(manifests.encode()) > _MAX_MANIFEST_BYTES:
        msg = "prepared manifest exceeds the bounded 2 MiB validation input"
        raise ValueError(msg)
    objects = _resources(manifests, namespace=_target_namespace(target))
    if not objects:
        msg = "prepared target rendered no resources"
        raise ValueError(msg)
    bindings = _table(target.get("schema_bindings"), "schema_bindings")
    if not bindings:
        msg = "prepared target must supply a closed local Kubernetes schema set"
        raise ValueError(msg)
    conform = checked_tool("kubeconform", root=root, runner=runner)
    linter = checked_tool("kube-linter", root=root, runner=runner)
    config = work / "kube-linter.yaml"
    exceptions = ExceptionSet.parse(target)
    diagnostics: list[Diagnostic] = []
    for index, resource in enumerate(objects):
        obj = _table(resource, "Kubernetes resource")
        config.write_text(yaml.safe_dump(build_config(obj)), encoding="utf-8")
        schema = contained_file(directory, _text(bindings, f"{_text(obj, 'apiVersion')}/{_text(obj, 'kind')}"))
        _closed_schema(schema, directory, target)
        metadata = _table(obj.get("metadata"), "Kubernetes metadata")
        identity = f"{_text(target, 'id')}:{_text(obj, 'apiVersion')}:{_text(obj, 'kind')}:{metadata.get('namespace', '')}:{_text(metadata, 'name')}:{index}"
        path = work / f"resource-{index}.yaml"
        path.write_text(yaml.safe_dump(obj), encoding="utf-8")
        output = invoke(
            conform,
            (
                "-strict",
                "-verbose",
                "-summary",
                "-output",
                "json",
                "-kubernetes-version",
                _text(target, "kubernetes_version"),
                "-schema-location",
                str(schema),
                str(path),
            ),
            root=root,
            runner=runner,
        )
        diagnostics.extend(_conform_findings(output, target, identity))
        path.write_text(yaml.safe_dump(policy_resource(obj)), encoding="utf-8")
        lint = invoke(
            linter,
            (
                "lint",
                "--format",
                "json",
                "--config",
                str(config),
                "--fail-if-no-objects-found",
                "--fail-on-invalid-resource",
                str(path),
            ),
            root=root,
            runner=runner,
        )
        if lint.returncode != (1 if _table(parse_json(lint.stdout), "kube-linter output").get("Reports") else 0):
            msg = "kube-linter exit does not agree with structured reports"
            raise ValueError(msg)
        diagnostics.extend(normalize_findings(lint.stdout, target, obj, identity, exceptions))
    exceptions.finish()
    return tuple(diagnostics)


def _target_namespace(target: Mapping[str, object]) -> str:
    namespace = target.get("namespace", "default")
    if not isinstance(namespace, str) or not namespace.strip():
        msg = "prepared target namespace must be a nonempty string"
        raise TypeError(msg)
    return namespace


def _resources(manifests: str, *, namespace: str = "default") -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    identities: set[tuple[str, str, str, str]] = set()

    def collect(value: object) -> None:
        obj = _table(value, "Kubernetes resource")
        version, kind = _text(obj, "apiVersion"), _text(obj, "kind")
        if version == "v1" and kind == "List":
            items = obj.get("items")
            if not is_object_list(items):
                msg = "Kubernetes List requires an items sequence"
                raise ValueError(msg)
            for item in items:
                collect(item)
            return
        metadata = _table(obj.get("metadata"), "Kubernetes metadata")
        resource_namespace = metadata.get("namespace", "")
        if not isinstance(resource_namespace, str):
            msg = "Kubernetes namespace must be a string"
            raise TypeError(msg)
        identity = (version, kind, resource_namespace, _text(metadata, "name"))
        counterpart = (version, kind, namespace if not resource_namespace else "", identity[3])
        if identity in identities or (
            (not resource_namespace or resource_namespace == namespace) and counterpart in identities
        ):
            msg = "prepared target contains duplicate Kubernetes object identities"
            raise ValueError(msg)
        identities.add(identity)
        result.append(obj)

    for document in parse_yaml_documents(manifests):
        if document is not None:
            collect(document)
    return tuple(result)


def _conform_findings(output: ProcessOutput, target: Mapping[str, object], identity: str) -> tuple[Diagnostic, ...]:
    payload = _table(parse_json(output.stdout), "kubeconform output")
    results = payload.get("resources")
    if not is_object_list(results) or len(results) != 1:
        msg = "kubeconform did not account for the required resource"
        raise ValueError(msg)
    result = _table(results[0], "kubeconform result")
    status = result.get("status")
    if status not in {"statusValid", "statusInvalid"}:
        msg = f"Kubernetes schema coverage is incomplete: {result}"
        raise ValueError(msg)
    summary = _table(payload.get("summary"), "kubeconform summary")
    expected = {
        "valid": 1 if status == "statusValid" else 0,
        "invalid": 1 if status == "statusInvalid" else 0,
        "errors": 0,
        "skipped": 0,
    }
    if (
        any(type(summary.get(key)) is not int or summary.get(key) != value for key, value in expected.items())
        or output.returncode != expected["invalid"]
    ):
        msg = "kubeconform summary or exit does not account for the required resource"
        raise ValueError(msg)
    if status == "statusInvalid":
        return (_diagnostic(target, "kubeconform", "schema", str(result.get("msg", "invalid resource")), identity),)
    return ()


def _diagnostic(target: Mapping[str, object], source: str, rule: str, message: str, identity: str) -> Diagnostic:
    return Diagnostic(
        rule, f"[{identity}] {message}", Severity.ERROR, source, Location(_text(target, "source")), rule_id=rule
    )


def _closed_schema(
    path: Path,
    directory: Path,
    target: Mapping[str, object],
    seen: set[tuple[Path, str]] | None = None,
    fragment: str = "",
) -> None:
    visited: set[tuple[Path, str]] = set() if seen is None else seen
    key = (path, fragment)
    if key in visited:
        return
    visited.add(key)
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        msg = "local schema exceeds 2 MiB"
        raise ValueError(msg)
    data = parse_unique_json(path.read_text(encoding="utf-8"))
    for reference in schema_references(
        data,
        fragment=fragment,
        default_dialect=DEFAULT_DIALECT if target.get("kind") == "cloud-run" else KUBERNETES_DEFAULT_DIALECT,
    ):
        name = reference.split("#", 1)[0]
        if not name:
            continue
        if ":" in name or "?" in name or "%" in name or "\\" in name or name.startswith("/"):
            msg = f"schemas must not resolve network or absolute references: {reference}"
            raise ValueError(msg)
        artifact = (path.parent / name).relative_to(directory).as_posix()
        hashes = _table(target.get("artifacts"), "artifact hashes")
        child = contained_file(directory, artifact)
        _verify_hash(child, _text(hashes, artifact))
        _closed_schema(child, directory, target, visited, reference.partition("#")[2])
