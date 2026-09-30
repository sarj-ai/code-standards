from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
import yaml

from sarj_standards.libs.diagnostics import Diagnostic, Location, Severity, SourceDocument
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


SecurityTool = Literal["zizmor", "checkov"]
VERSIONS: Final[Mapping[SecurityTool, str]] = MappingProxyType({"zizmor": "1.30.1", "checkov": "3.3.20"})
TOOLS: Final[tuple[SecurityTool, ...]] = ("zizmor", "checkov")
TERRAFORM_CHECKS: Final = ("CKV_GCP_41", "CKV_GCP_95", "CKV_GCP_97")
KUBERNETES_CHECKS: Final = ("CKV_K8S_10", "CKV_K8S_12", "CKV_K8S_13", "CKV_K8S_43")
CHECKOV_CHECKS: Final = frozenset((*TERRAFORM_CHECKS, *KUBERNETES_CHECKS))
ZIZMOR_RULES: Final = frozenset(
    {
        "adhoc-packages",
        "anonymous-definition",
        "archived-uses",
        "artipacked",
        "bot-conditions",
        "cache-poisoning",
        "concurrency-limits",
        "dangerous-triggers",
        "dependabot-cooldown",
        "dependabot-execution",
        "excessive-permissions",
        "forbidden-uses",
        "github-app",
        "github-env",
        "hardcoded-container-credentials",
        "impostor-commit",
        "insecure-commands",
        "insecure-url-scheme",
        "known-vulnerable-actions",
        "misfeature",
        "obfuscation",
        "overprovisioned-secrets",
        "ref-confusion",
        "ref-version-mismatch",
        "secrets-inherit",
        "secrets-outside-env",
        "self-hosted-runner",
        "self-repository",
        "stale-action-refs",
        "superfluous-actions",
        "template-injection",
        "typosquat-uses",
        "undocumented-permissions",
        "unpinned-images",
        "unpinned-tools",
        "unpinned-uses",
        "unredacted-secrets",
        "unsound-condition",
        "unsound-contains",
        "unsound-ternary",
        "use-trusted-publishing",
    }
)
_MAX_SOURCE_BYTES: Final = 2 * 1024 * 1024
_PLACEHOLDER: Final = re.compile(r"\$\{|\{\{")


class _ProtocolModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)


class _CheckResult(_ProtocolModel):
    result: Literal["FAILED"]


class _CheckovFinding(_ProtocolModel):
    check_id: str = Field(min_length=1)
    check_name: str = Field(min_length=1)
    check_result: _CheckResult
    file_path: str = Field(min_length=1)
    file_abs_path: str | None = None
    file_line_range: tuple[int, int]
    resource: str = Field(min_length=1)
    guideline: str | None = None


class _CheckovResults(_ProtocolModel):
    failed_checks: tuple[_CheckovFinding, ...]
    parsing_errors: tuple[str, ...]
    passed_checks: tuple[object, ...]
    skipped_checks: tuple[object, ...]


class _CheckovSummary(_ProtocolModel):
    checkov_version: str
    parsing_errors: int = Field(ge=0)


class _CheckovReport(_ProtocolModel):
    check_type: Literal["terraform", "kubernetes"]
    results: _CheckovResults
    summary: _CheckovSummary


class _CheckovEmptySummary(_ProtocolModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)

    passed: int = Field(ge=0, le=0)
    failed: int = Field(ge=0, le=0)
    skipped: int = Field(ge=0, le=0)
    parsing_errors: int = Field(ge=0, le=0)
    resource_count: int = Field(ge=0, le=0)
    checkov_version: str


class _SarifDriver(_ProtocolModel):
    name: Literal["zizmor"]
    version: str


class _SarifTool(_ProtocolModel):
    driver: _SarifDriver


class _SarifMessage(_ProtocolModel):
    text: str = Field(min_length=1)


class _SarifArtifact(_ProtocolModel):
    uri: str = Field(min_length=1)


class _SarifRegion(_ProtocolModel):
    start_line: int = Field(alias="startLine", ge=1)
    start_column: int = Field(default=1, alias="startColumn", ge=1)


class _SarifPhysical(_ProtocolModel):
    artifact: _SarifArtifact = Field(alias="artifactLocation")
    region: _SarifRegion


class _SarifLocation(_ProtocolModel):
    physical: _SarifPhysical = Field(alias="physicalLocation")


class _SarifResult(_ProtocolModel):
    rule_id: str = Field(alias="ruleId", min_length=1)
    message: _SarifMessage
    locations: tuple[_SarifLocation, ...] = Field(min_length=1)


class _SarifInvocation(_ProtocolModel):
    execution_successful: bool = Field(alias="executionSuccessful")


class _SarifRun(_ProtocolModel):
    tool: _SarifTool
    results: tuple[_SarifResult, ...]
    invocations: tuple[_SarifInvocation, ...] = ()


class _SarifReport(_ProtocolModel):
    version: Literal["2.1.0"]
    runs: tuple[_SarifRun, ...] = Field(min_length=1)


_CHECKOV_ADAPTER: Final[TypeAdapter[_CheckovReport | tuple[_CheckovReport, ...] | _CheckovEmptySummary]] = TypeAdapter(
    _CheckovReport | tuple[_CheckovReport, ...] | _CheckovEmptySummary
)


@dataclass(frozen=True, slots=True)
class SecurityInputs:
    workflows: tuple[str, ...]
    terraform: tuple[str, ...]
    kubernetes: tuple[str, ...]


def command(name: SecurityTool, *, offline: bool = True) -> tuple[str, ...]:
    return (
        "uvx",
        "--no-config",
        "--isolated",
        *(("--offline",) if offline else ()),
        "--python",
        "3.12",
        "--from",
        f"{name}=={VERSIONS[name]}",
        name,
    )


def select_inputs(files: Iterable[str], *, root: Path) -> SecurityInputs:
    workflows: list[str] = []
    terraform: list[str] = []
    kubernetes: list[str] = []
    for raw_path in sorted(set(files)):
        path = Path(raw_path).resolve()
        relative = path.relative_to(root.resolve())
        if not path.is_file():
            continue
        if path.name.endswith((".tf", ".tf.json")):
            terraform.append(str(path))
            continue
        if path.suffix.casefold() not in {".yaml", ".yml"}:
            continue
        if relative.parts[:2] == (".github", "workflows") or path.name in {"action.yml", "action.yaml"}:
            workflows.append(str(path))
            continue
        text = _source(path)
        if re.search(r"(?m)^apiVersion\s*:", text) and re.search(r"(?m)^kind\s*:", text):
            kubernetes.append(str(path))
    return SecurityInputs(tuple(workflows), tuple(terraform), tuple(kubernetes))


def parse_zizmor(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    report = _SarifReport.model_validate_json(payload)
    diagnostics: list[Diagnostic] = []
    for run in report.runs:
        if run.tool.driver.version != VERSIONS["zizmor"]:
            msg = "zizmor reported an unexpected version"
            raise ValueError(msg)
        if any(not invocation.execution_successful for invocation in run.invocations):
            msg = "zizmor reported an incomplete invocation"
            raise ValueError(msg)
        for finding in run.results:
            rule_id = finding.rule_id.removeprefix("zizmor/")
            if rule_id not in ZIZMOR_RULES:
                msg = "zizmor returned an audit outside the pinned registry"
                raise ValueError(msg)
            physical = finding.locations[0].physical
            uri = urlparse(physical.artifact.uri)
            if uri.scheme not in {"", "file"} or uri.netloc:
                msg = "zizmor reported a nonlocal artifact"
                raise ValueError(msg)
            path = _contained_path(unquote(uri.path), root)
            diagnostics.append(
                _diagnostic(
                    "zizmor",
                    rule_id,
                    finding.message.text,
                    path=path,
                    root=root,
                    line=physical.region.start_line,
                    column=physical.region.start_column,
                )
            )
    return tuple(diagnostics)


def parse_checkov(payload: str, *, root: Path) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for report in _checkov_reports(payload):
        for finding in report.results.failed_checks:
            if finding.check_id not in CHECKOV_CHECKS:
                msg = "Checkov returned a check outside the managed selection"
                raise ValueError(msg)
            path = (
                _contained_path(finding.file_abs_path, root)
                if finding.file_abs_path is not None
                else _contained_path(finding.file_path.removeprefix("/"), root)
            )
            if finding.file_line_range[1] < finding.file_line_range[0]:
                msg = "Checkov returned a reversed line range"
                raise ValueError(msg)
            diagnostics.append(
                _diagnostic(
                    "checkov",
                    finding.check_id,
                    finding.check_name,
                    path=path,
                    root=root,
                    line=finding.file_line_range[0],
                    column=1,
                    deferred_digest=report.check_type == "kubernetes"
                    and finding.check_id == "CKV_K8S_43"
                    and _has_image_placeholder(path, finding.resource),
                )
            )
    return tuple(diagnostics)


def _checkov_reports(payload: str) -> tuple[_CheckovReport, ...]:
    parsed = _CHECKOV_ADAPTER.validate_json(payload)
    if isinstance(parsed, _CheckovEmptySummary):
        if parsed.checkov_version != VERSIONS["checkov"]:
            msg = "Checkov reported an unexpected version"
            raise ValueError(msg)
        return ()
    reports = (parsed,) if isinstance(parsed, _CheckovReport) else parsed
    if not reports:
        msg = "Checkov returned no framework reports"
        raise ValueError(msg)
    for report in reports:
        if report.summary.checkov_version != VERSIONS["checkov"]:
            msg = "Checkov reported an unexpected version"
            raise ValueError(msg)
        if report.results.parsing_errors or report.summary.parsing_errors:
            msg = "Checkov could not parse all selected inputs"
            raise ValueError(msg)
    return reports


def _diagnostic(
    tool: str,
    rule: str,
    message: str,
    *,
    path: Path,
    root: Path,
    line: int,
    column: int,
    deferred_digest: bool = False,
) -> Diagnostic:
    document = SourceDocument.read(path)
    position = None if document is None else document.point(line=line, column=column)
    if position is None:
        msg = "security analyzer reported a position outside readable source"
        raise ValueError(msg)
    return Diagnostic(
        rule,
        message.replace(str(root), "."),
        Severity.INFO if deferred_digest else Severity.WARNING,
        tool,
        Location(path.relative_to(root.resolve()).as_posix(), position=position),
        rule_id=rule,
        notes=("Image digest validation is deferred until this template is rendered; scan the rendered artifact.",)
        if deferred_digest
        else (),
    )


def _contained_path(raw_path: str, root: Path) -> Path:
    path = Path(raw_path)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        msg = "security analyzer reported a path outside the repository"
        raise ValueError(msg)
    return resolved


def _source(path: Path) -> str:
    if path.stat().st_size > _MAX_SOURCE_BYTES:
        msg = "security source exceeds the 2 MiB size limit"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


def _has_image_placeholder(path: Path, resource: str) -> bool:
    def images(value: object) -> tuple[str, ...]:
        if is_object_mapping(value):
            return tuple(
                image
                for key, child in value.items()
                for image in ((child,) if key == "image" and isinstance(child, str) else images(child))
            )
        if is_object_list(value):
            return tuple(image for child in value for image in images(child))
        return ()

    try:
        documents: tuple[object, ...] = tuple(yaml.safe_load_all(_source(path)))
    except yaml.YAMLError as exc:
        msg = "cannot parse the source image template"
        raise ValueError(msg) from exc
    for document in documents:
        if not is_object_mapping(document):
            continue
        metadata = document.get("metadata")
        if not is_object_mapping(metadata):
            continue
        identity = f"{document.get('kind')}.{metadata.get('namespace', 'default')}.{metadata.get('name')}"
        if resource != identity:
            continue
        values = images(document)
        return bool(values) and all(_PLACEHOLDER.search(image) is not None for image in values)
    return False
