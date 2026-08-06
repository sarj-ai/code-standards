"""Canonical, tool-neutral diagnostics returned by the Standards facade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final


SCHEMA_VERSION: Final = 1
SCHEMA_URI: Final = "https://standards.sarj.ai/schemas/analysis/v1"
ANALYSIS_SCHEMA: Final = Path(__file__).with_name("analysis-v1.schema.json")


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
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Position:
    """A zero-based UTF-16 editor position plus its internal byte offset."""

    line: int
    character: int
    byte_offset: int

    def __post_init__(self) -> None:
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
        if self.end.byte_offset < self.start.byte_offset:
            msg = "source region end precedes its start"
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
        if self.position is not None and self.region is not None:
            msg = "a diagnostic location cannot carry both a point and a region"
            raise ValueError(msg)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"path": self.path}
        if self.region is not None:
            result["range"] = self.region.as_dict()
        elif self.position is not None:
            result["position"] = self.position.as_dict()
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
        return result


@dataclass(frozen=True, slots=True)
class ExecutionIssue:
    """Analyzer/configuration failure, intentionally not disguised as a finding."""

    source: str
    kind: str
    message: str
    exit_code: int | None = None

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

    def __post_init__(self) -> None:
        if self.completion is Completion.COMPLETE and self.issues:
            msg = "a complete tool report cannot contain execution issues"
            raise ValueError(msg)
        if self.completion is not Completion.COMPLETE and not self.issues:
            msg = "an incomplete tool report must explain its execution issue"
            raise ValueError(msg)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "completion": self.completion.value,
            "diagnosticCount": len(self.diagnostics),
            "issueCount": len(self.issues),
        }


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Versioned result for IDEs, CI annotations, and programmatic consumers."""

    root: Path
    completion: Completion
    conclusion: Conclusion
    tools: tuple[ToolReport, ...]

    def __post_init__(self) -> None:
        has_issues = any(tool.issues for tool in self.tools)
        has_findings = any(tool.diagnostics for tool in self.tools)
        if (self.completion is Completion.COMPLETE) == has_issues:
            msg = "analysis completion contradicts its tool execution issues"
            raise ValueError(msg)
        expected = Conclusion.FAILED if has_issues else Conclusion.FINDINGS if has_findings else Conclusion.PASSED
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
        if self.issues:
            return 2
        return 1 if any(item.severity is Severity.ERROR for item in self.diagnostics) else 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "$schema": SCHEMA_URI,
            "schemaVersion": SCHEMA_VERSION,
            "root": str(self.root),
            "completion": self.completion.value,
            "conclusion": self.conclusion.value,
            "exitCode": self.exit_code,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "issues": [item.as_dict() for item in self.issues],
            "tools": [item.as_dict() for item in self.tools],
        }
