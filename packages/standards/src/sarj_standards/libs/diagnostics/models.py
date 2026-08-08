"""Canonical, tool-neutral diagnostics returned by the Standards facade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Final, NewType, TypedDict
from urllib.parse import urlparse


SCHEMA_VERSION: Final = 1
SCHEMA_URI: Final = "https://standards.sarj.ai/schemas/analysis/v1"
ANALYSIS_SCHEMA: Final = Path(__file__).with_name("analysis.schema.json")
FINGERPRINT_VERSION: Final = 1
_SHA256_HEX_LENGTH: Final = 64
AnalyzerId = NewType("AnalyzerId", str)
InvocationId = NewType("InvocationId", str)


class Severity(StrEnum):
    """Stable diagnostic severity independent of any one lint engine."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Completion(StrEnum):
    """Whether every requested analyzer completed successfully."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class Conclusion(StrEnum):
    """Semantic result, kept separate from execution completeness."""

    PASSED = "passed"
    FINDINGS = "findings"
    INCONCLUSIVE = "inconclusive"


class TrustMode(StrEnum):
    """Whether repository-controlled executable analyzer configuration may run."""

    SAFE = "safe"
    TRUSTED = "trusted"


class CoverageDisposition(StrEnum):
    """Why selected input was not analyzed."""

    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    EXCLUDED = "excluded"
    NOT_REQUESTED = "not-requested"


class FixSafety(StrEnum):
    """Whether a fix may be applied without human review."""

    SAFE = "safe"
    UNSAFE = "unsafe"


class CacheStatus(StrEnum):
    """Cache outcome for one analyzer invocation."""

    DISABLED = "disabled"
    HIT = "hit"
    MISS = "miss"


class _CoverageNotice(TypedDict):
    """Serialized coverage notice returned to protocol consumers."""

    source: str
    reason: str
    fileCount: int
    disposition: str


_AnalysisReport = TypedDict(
    "_AnalysisReport",
    {
        "$schema": str,
        "schemaVersion": int,
        "root": str,
        "completion": str,
        "conclusion": str,
        "exitCode": int,
        "rules": list[dict[str, object]],
        "diagnostics": list[dict[str, object]],
        "issues": list[dict[str, object]],
        "tools": list[dict[str, object]],
        "coverage": list[_CoverageNotice],
    },
)


@dataclass(frozen=True, slots=True)
class CoverageNotice:
    """Requested source that an intentionally narrow analysis did not evaluate."""

    source: str
    reason: str
    file_count: int
    disposition: CoverageDisposition = CoverageDisposition.FAILED

    def __post_init__(self) -> None:
        _require_text(self.source, "coverage source")
        _require_text(self.reason, "coverage reason")
        _require_int(self.file_count, "coverage file count")
        if self.file_count < 1:
            msg = "coverage notice must describe at least one file"
            raise ValueError(msg)
        _require_instance(self.disposition, CoverageDisposition, "coverage disposition")

    @property
    def blocking(self) -> bool:
        """Return whether this notice means requested analysis failed."""
        return self.disposition is CoverageDisposition.FAILED

    def as_dict(self) -> _CoverageNotice:
        return {
            "source": self.source,
            "reason": self.reason,
            "fileCount": self.file_count,
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True, slots=True)
class Position:
    """A zero-based UTF-16 editor position plus its internal byte offset."""

    line: int
    character: int
    byte_offset: int

    def __post_init__(self) -> None:
        _require_int(self.line, "position line")
        _require_int(self.character, "position character")
        _require_int(self.byte_offset, "position byte offset")
        if min(self.line, self.character, self.byte_offset) < 0:
            msg = "source positions cannot be negative"
            raise ValueError(msg)

    def as_dict(self) -> dict[str, int]:
        """Serialize only the portable LSP-compatible coordinates."""
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True, slots=True)
class Region:
    """An exact half-open source region; absent when an analyzer knows only a point."""

    start: Position
    end: Position

    def __post_init__(self) -> None:
        _require_instance(self.start, Position, "source region start")
        _require_instance(self.end, Position, "source region end")
        if self.end.byte_offset < self.start.byte_offset:
            msg = "source region end precedes its start"
            raise ValueError(msg)
        if (self.end.line, self.end.character) < (self.start.line, self.start.character):
            msg = "source region coordinates run backwards"
            raise ValueError(msg)

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {"start": self.start.as_dict(), "end": self.end.as_dict()}


@dataclass(frozen=True, slots=True)
class Location:
    """Repository-relative path with a truthful point or exact range."""

    path: str
    position: Position | None = None
    region: Region | None = None

    def __post_init__(self) -> None:
        _require_text(self.path, "location path")
        path = Path(self.path)
        windows = PureWindowsPath(self.path)
        if path.is_absolute() or windows.is_absolute() or windows.drive or ".." in path.parts or "\\" in self.path:
            msg = "diagnostic location must be a repository-relative path"
            raise ValueError(msg)
        if self.position is not None and self.region is not None:
            msg = "a diagnostic location cannot carry both a point and a region"
            raise ValueError(msg)
        if self.position is not None:
            _require_instance(self.position, Position, "diagnostic position")
        if self.region is not None:
            _require_instance(self.region, Region, "diagnostic region")

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"path": self.path}
        if self.region is not None:
            result["range"] = self.region.as_dict()
        elif self.position is not None:
            result["position"] = self.position.as_dict()
        return result


@dataclass(frozen=True, slots=True)
class RelatedLocation:
    """A secondary source location that explains a diagnostic."""

    label: str
    location: Location

    def __post_init__(self) -> None:
        _require_text(self.label, "related location label")
        _require_instance(self.location, Location, "related location")

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "location": self.location.as_dict()}


@dataclass(frozen=True, slots=True)
class TextEdit:
    """One exact, repository-contained source replacement."""

    location: Location
    replacement: str
    expected_text_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.location, Location, "text edit location")
        if self.location.region is None:
            msg = "text edit location must contain an exact range"
            raise ValueError(msg)
        _require_text(self.replacement, "text edit replacement", allow_empty=True)
        if self.expected_text_hash is not None:
            _require_text(self.expected_text_hash, "expected text hash")
            if len(self.expected_text_hash) != _SHA256_HEX_LENGTH or any(
                char not in "0123456789abcdef" for char in self.expected_text_hash
            ):
                msg = "expected text hash must be a lowercase SHA-256 digest"
                raise ValueError(msg)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"location": self.location.as_dict(), "replacement": self.replacement}
        if self.expected_text_hash is not None:
            result["expectedTextHash"] = self.expected_text_hash
        return result


@dataclass(frozen=True, slots=True)
class Fix:
    """A bounded set of non-overlapping edits for one remediation."""

    title: str
    safety: FixSafety
    edits: tuple[TextEdit, ...]

    def __post_init__(self) -> None:
        _require_text(self.title, "fix title")
        _require_instance(self.safety, FixSafety, "fix safety")
        _require_tuple_items(self.edits, TextEdit, "fix edits")
        if not self.edits:
            msg = "fix must contain at least one edit"
            raise ValueError(msg)
        ordered = sorted(self.edits, key=_edit_key)
        if tuple(ordered) != self.edits:
            msg = "fix edits must be sorted by path and range"
            raise ValueError(msg)
        for previous, current in zip(self.edits, self.edits[1:], strict=False):
            if previous.location.path != current.location.path:
                continue
            previous_region = previous.location.region
            current_region = current.location.region
            if (
                previous_region is not None
                and current_region is not None
                and (previous_region.end.byte_offset > current_region.start.byte_offset)
            ):
                msg = "fix edits must not overlap"
                raise ValueError(msg)

    def as_dict(self) -> dict[str, object]:
        return {"title": self.title, "safety": self.safety.value, "edits": [edit.as_dict() for edit in self.edits]}


@dataclass(frozen=True, slots=True)
class RuleDescriptor:
    """Stable rule metadata shared by renderers and integrations."""

    key: str
    name: str
    summary: str
    help_url: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.key, "rule key")
        _require_text(self.name, "rule name")
        _require_text(self.summary, "rule summary")
        _require_tuple_text(self.tags, "rule tags")
        _require_unique_text(self.tags, "rule tags")
        _validate_help_url(self.help_url)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"key": self.key, "name": self.name, "summary": self.summary}
        if self.help_url is not None:
            result["helpUrl"] = self.help_url
        if self.tags:
            result["tags"] = list(self.tags)
        return result


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One normalized static-analysis finding."""

    code: str
    message: str
    severity: Severity
    source: str
    location: Location
    rule_id: str | None = None
    help: str | None = None
    help_url: str | None = None
    related: tuple[RelatedLocation, ...] = ()
    notes: tuple[str, ...] = ()
    fixes: tuple[Fix, ...] = ()
    tags: tuple[str, ...] = ()
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.code, "diagnostic code")
        _require_text(self.message, "diagnostic message", allow_empty=True)
        _require_text(self.source, "diagnostic source")
        _require_instance(self.severity, Severity, "diagnostic severity")
        _require_instance(self.location, Location, "diagnostic location")
        if self.rule_id is not None:
            _require_text(self.rule_id, "diagnostic rule id")
        if self.help is not None:
            _require_text(self.help, "diagnostic help", allow_empty=True)
        _validate_help_url(self.help_url)
        _require_tuple_items(self.related, RelatedLocation, "diagnostic related locations")
        _require_tuple_text(self.notes, "diagnostic notes")
        _require_tuple_items(self.fixes, Fix, "diagnostic fixes")
        _require_tuple_text(self.tags, "diagnostic tags")
        _require_unique_text(self.tags, "diagnostic tags")
        if self.fingerprint is not None:
            _require_text(self.fingerprint, "diagnostic fingerprint")

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
            "location": self.location.as_dict(),
        }
        if self.rule_id is not None:
            result["ruleId"] = self.rule_id
        if self.help is not None:
            result["help"] = self.help
        if self.help_url is not None:
            result["helpUrl"] = self.help_url
        result["ruleKey"] = f"{self.source}:{self.rule_id or self.code}"
        if self.related:
            result["relatedLocations"] = [item.as_dict() for item in self.related]
        if self.notes:
            result["notes"] = list(self.notes)
        if self.fixes:
            result["fixes"] = [item.as_dict() for item in self.fixes]
        if self.tags:
            result["tags"] = list(self.tags)
        if self.fingerprint is not None:
            result["fingerprint"] = {"algorithm": FINGERPRINT_VERSION, "value": self.fingerprint}
        return result


@dataclass(frozen=True, slots=True)
class ExecutionIssue:
    """Analyzer/configuration failure, intentionally not disguised as a finding."""

    source: str
    kind: str
    message: str
    exit_code: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.source, "execution issue source")
        _require_text(self.kind, "execution issue kind")
        _require_text(self.message, "execution issue message", allow_empty=True)
        if self.exit_code is not None:
            _require_int(self.exit_code, "execution issue exit code")

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"source": self.source, "kind": self.kind, "message": self.message}
        if self.exit_code is not None:
            result["exitCode"] = self.exit_code
        return result


@dataclass(frozen=True, slots=True)
class ToolReport:
    """Diagnostics and execution state for one analyzer invocation."""

    name: str
    completion: Completion
    diagnostics: tuple[Diagnostic, ...] = ()
    issues: tuple[ExecutionIssue, ...] = ()
    analyzer_id: AnalyzerId | None = None
    invocation_id: InvocationId | None = None
    version: str | None = None
    duration_ms: int | None = None  # sarj-noqa: SARJ014 — protocol durations are integer milliseconds.
    file_count: int | None = None
    cache_status: CacheStatus = CacheStatus.DISABLED

    def __post_init__(self) -> None:
        _require_text(self.name, "tool name")
        _require_instance(self.completion, Completion, "tool completion")
        _require_tuple_items(self.diagnostics, Diagnostic, "tool diagnostics")
        _require_tuple_items(self.issues, ExecutionIssue, "tool issues")
        if self.completion is Completion.COMPLETE and self.issues:
            msg = "a complete tool report cannot contain execution issues"
            raise ValueError(msg)
        if self.completion is not Completion.COMPLETE and not self.issues:
            msg = "an incomplete tool report must explain its execution issue"
            raise ValueError(msg)
        for value, label in (
            (self.analyzer_id, "analyzer id"),
            (self.invocation_id, "invocation id"),
            (self.version, "tool version"),
        ):
            if value is not None:
                _require_text(value, label)
        for value, label in ((self.duration_ms, "duration"), (self.file_count, "file count")):
            if value is not None:
                _require_int(value, label)
                if value < 0:
                    msg = f"{label} cannot be negative"
                    raise ValueError(msg)
        _require_instance(self.cache_status, CacheStatus, "cache status")

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "name": self.name,
            "completion": self.completion.value,
            "diagnosticCount": len(self.diagnostics),
            "issueCount": len(self.issues),
        }
        result["analyzerId"] = self.analyzer_id or self.name
        result["invocationId"] = self.invocation_id or self.name
        result["cache"] = self.cache_status.value
        if self.version is not None:
            result["version"] = self.version
        if self.file_count is not None:
            result["fileCount"] = self.file_count
        return result


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Versioned result for IDEs, CI annotations, and programmatic consumers."""

    root: Path
    completion: Completion
    conclusion: Conclusion
    tools: tuple[ToolReport, ...]
    coverage: tuple[CoverageNotice, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.root, Path, "analysis root")
        _require_instance(self.completion, Completion, "analysis completion")
        _require_instance(self.conclusion, Conclusion, "analysis conclusion")
        _require_tuple_items(self.tools, ToolReport, "analysis tools")
        _require_tuple_items(self.coverage, CoverageNotice, "analysis coverage")
        has_issues = any(tool.issues for tool in self.tools)
        has_findings = any(tool.diagnostics for tool in self.tools)
        is_incomplete = has_issues or any(item.blocking for item in self.coverage)
        expected_completion = (
            Completion.FAILED
            if self.tools and all(tool.completion is Completion.FAILED for tool in self.tools)
            else Completion.COMPLETE
            if not is_incomplete and all(tool.completion is Completion.COMPLETE for tool in self.tools)
            else Completion.PARTIAL
        )
        if self.completion is not expected_completion:
            msg = f"analysis completion must be {expected_completion.value} for its tool and coverage states"
            raise ValueError(msg)
        expected = (
            Conclusion.FINDINGS if has_findings else Conclusion.INCONCLUSIVE if is_incomplete else Conclusion.PASSED
        )
        if self.conclusion is not expected:
            msg = f"analysis conclusion must be {expected.value} for its findings and issues"
            raise ValueError(msg)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic for tool in self.tools for diagnostic in tool.diagnostics)

    @property
    def issues(self) -> tuple[ExecutionIssue, ...]:
        return tuple(issue for tool in self.tools for issue in tool.issues)

    @property
    def exit_code(self) -> int:
        if self.issues or any(item.blocking for item in self.coverage):
            return 2
        return 1 if any(item.severity is Severity.ERROR for item in self.diagnostics) else 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> _AnalysisReport:
        rules: dict[str, RuleDescriptor] = {}
        for item in self.diagnostics:
            key = f"{item.source}:{item.rule_id or item.code}"
            rules.setdefault(
                key,
                RuleDescriptor(
                    key, item.rule_id or item.code, item.help or item.rule_id or item.code, item.help_url, item.tags
                ),
            )
        return {
            "$schema": SCHEMA_URI,
            "schemaVersion": SCHEMA_VERSION,
            "root": ".",
            "completion": self.completion.value,
            "conclusion": self.conclusion.value,
            "exitCode": self.exit_code,
            "rules": [rules[key].as_dict() for key in sorted(rules)],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "issues": [item.as_dict() for item in self.issues],
            "tools": [item.as_dict() for item in self.tools],
            "coverage": [item.as_dict() for item in self.coverage],
        }


def diagnostic_fingerprint(diagnostic: Diagnostic, *, anchor: str) -> str:
    """Create a versioned stable fingerprint from non-message semantic facts."""
    _require_text(anchor, "diagnostic fingerprint anchor")
    identity = "\0".join(
        (
            str(FINGERPRINT_VERSION),
            diagnostic.source,
            diagnostic.rule_id or diagnostic.code,
            diagnostic.location.path,
            anchor,
        )
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def _edit_key(edit: TextEdit) -> tuple[object, ...]:
    region = edit.location.region
    if region is None:
        msg = "text edit location must contain an exact range"
        raise ValueError(msg)
    return (edit.location.path, region.start.byte_offset, region.end.byte_offset)


def _validate_help_url(value: str | None) -> None:
    if value is None:
        return
    _require_text(value, "diagnostic help URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or any(char.isspace() for char in value):
        msg = "diagnostic help URL must be an absolute HTTPS URI"
        raise ValueError(msg)


def _require_tuple_text(value: object, label: str) -> None:
    if not isinstance(value, tuple):
        msg = f"{label} must be a tuple of non-empty strings"
        raise TypeError(msg)
    for item in value:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, str) or not item:
            msg = f"{label} must be a tuple of non-empty strings"
            raise TypeError(msg)


def _require_unique_text(value: tuple[str, ...], label: str) -> None:
    if len(value) != len(set(value)):
        msg = f"{label} must not contain duplicates"
        raise ValueError(msg)


def _require_text(value: object, label: str, *, allow_empty: bool = False) -> None:
    if type(value) is not str or (not allow_empty and not value):
        msg = f"{label} must not be empty"
        raise ValueError(msg)


def _require_int(value: int, label: str) -> None:
    if type(value) is not int:
        msg = f"{label} must be an integer"
        raise TypeError(msg)


def _require_instance(value: object, expected: type[object], label: str) -> None:
    if not isinstance(value, expected):
        msg = f"{label} must be {expected.__name__}"
        raise TypeError(msg)


def _require_tuple_items(value: object, expected: type[object], label: str) -> None:
    if not isinstance(value, tuple):
        invalid = True
    else:
        invalid = type(value) is not tuple or any(  # pyright: ignore[reportUnknownArgumentType] -- validated below.
            not isinstance(item, expected)
            for item in value  # pyright: ignore[reportUnknownVariableType] -- tuple elements are validated here.
        )
    if invalid:
        msg = f"{label} must be a tuple of {expected.__name__} values"
        raise TypeError(msg)
