"""Value objects shared by rule discovery and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, Final, NewType, Self


if TYPE_CHECKING:
    from collections.abc import Iterable


_DEFAULT_CASE_PATH = PurePosixPath("case.txt")
_KEBAB_CASE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SUMMARY_LENGTH: Final = 160
_PUBLIC_PAIR_SIZE: Final = 2

RuleId = NewType("RuleId", str)
MessageId = NewType("MessageId", str)


class Language(StrEnum):
    """Syntax families supported by the standards rule catalog."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    MARKDOWN = "markdown"
    SQL = "sql"
    IAC = "iac"
    CONFIG = "config"


class RuleOrigin(StrEnum):
    """Whether an existing rule is upstream or maintained by Sarj."""

    UPSTREAM = "upstream"
    SARJ = "sarj"


class RuleEngine(StrEnum):
    """Stable engine namespace used by configuration, diagnostics, and URLs."""

    ESLINT = "eslint"
    IAC = "iac"
    PYTHON = "python"
    SQL = "sql"
    TEXT = "text"


@dataclass(frozen=True, slots=True, order=True)
class RuleSelector:
    """Canonical identity for one custom rule across CLI and wire boundaries."""

    engine: RuleEngine
    rule_id: RuleId

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.fullmatch(self.rule_id):
            msg = "rule ID must be non-empty lowercase kebab-case"
            raise ValueError(msg)

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse the strict public ``ENGINE:ID`` representation."""
        engine_text, separator, rule_text = value.partition(":")
        if not separator or ":" in rule_text:
            msg = "rule selector must use canonical ENGINE:ID form"
            raise ValueError(msg)
        try:
            engine = RuleEngine(engine_text)
        except ValueError as exc:
            msg = f"unknown custom-rule engine: {engine_text}"
            raise ValueError(msg) from exc
        return cls(engine, RuleId(rule_text))

    def __str__(self) -> str:
        return f"{self.engine.value}:{self.rule_id}"

    @property
    def native_rule_id(self) -> str:
        """Return the analyzer-native rule ID for diagnostic matching."""
        if self.engine is RuleEngine.ESLINT:
            return f"@sarj/{self.rule_id}"
        return str(self.rule_id)


@dataclass(frozen=True, slots=True)
class RuleSelection:
    """A normalized, duplicate-free selection of custom rules."""

    selectors: frozenset[RuleSelector]

    @classmethod
    def from_values(cls, values: Iterable[str | RuleSelector]) -> Self:
        """Normalize public strings and already-parsed selectors once."""
        if isinstance(values, str):
            msg = "rule selection must be an iterable of selector values, not one string"
            raise TypeError(msg)
        parsed: set[RuleSelector] = set()
        for value in values:
            if isinstance(value, RuleSelector):
                parsed.add(value)
            else:
                parsed.add(RuleSelector.parse(value))
        return cls(frozenset(parsed))

    @property
    def engines(self) -> frozenset[RuleEngine]:
        return frozenset(selector.engine for selector in self.selectors)

    def ids_for(self, engine: RuleEngine) -> frozenset[RuleId]:
        return frozenset(selector.rule_id for selector in self.selectors if selector.engine is engine)

    def native_ids_for(self, engine: RuleEngine) -> frozenset[str]:
        """Return engine-native IDs only at analyzer adapter boundaries."""
        return frozenset(selector.native_rule_id for selector in self.selectors if selector.engine is engine)


class RuleCategory(StrEnum):
    """Small, cross-engine taxonomy used to browse the generated catalog."""

    ARCHITECTURE = "architecture"
    CORRECTNESS = "correctness"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    SECURITY = "security"
    STYLE = "style"
    TESTING = "testing"


class DefaultLevel(StrEnum):
    """Default policy level derived from a shipped Standards profile."""

    ERROR = "error"
    OFF = "off"
    WARNING = "warning"


class RuleStatus(StrEnum):
    """Lifecycle state rendered in the generated rule directory."""

    ACTIVE = "active"
    RENAMED = "renamed"
    RETIRED = "retired"


class AutofixPolicy(StrEnum):
    """The strongest mutation a proposed rule may safely offer."""

    NONE = "none"
    SUGGESTION = "suggestion"
    SAFE = "safe"


class ExpectedOutcome(StrEnum):
    """Expected checker result for one evaluation case."""

    MATCH = "match"
    NO_MATCH = "no-match"


@dataclass(frozen=True, slots=True)
class ExampleFile:
    """One safe virtual file in an executable rule example."""

    path: PurePosixPath
    source: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.name or "\\" in self.path.as_posix():
            msg = "example file paths must be safe relative paths"
            raise ValueError(msg)
        if not self.source:
            msg = "example file source must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RuleExample:
    """A reviewed fixture consumed by both rule tests and generated docs."""

    example_id: str
    outcome: ExpectedOutcome
    files: tuple[ExampleFile, ...]
    focus_path: PurePosixPath
    expected_count: int
    title: str
    public: bool = False
    fixed_files: tuple[ExampleFile, ...] = ()
    scenario: str = "primary"

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.fullmatch(self.example_id):
            msg = "example ID must be non-empty lowercase kebab-case"
            raise ValueError(msg)
        if not _KEBAB_CASE.fullmatch(self.scenario):
            msg = "example scenario must be non-empty lowercase kebab-case"
            raise ValueError(msg)
        if not self.title.strip():
            msg = "example title must not be empty"
            raise ValueError(msg)
        paths = tuple(item.path for item in self.files)
        if not paths or len(paths) != len(set(paths)):
            msg = "example files must have unique paths"
            raise ValueError(msg)
        fixed_paths = tuple(item.path for item in self.fixed_files)
        if len(fixed_paths) != len(set(fixed_paths)):
            msg = "fixed example files must have unique paths"
            raise ValueError(msg)
        if self.focus_path not in paths:
            msg = "example focus path must name one example file"
            raise ValueError(msg)
        if self.expected_count < 0:
            msg = "example expected count must not be negative"
            raise ValueError(msg)
        if self.outcome is ExpectedOutcome.MATCH and self.expected_count < 1:
            msg = "matching examples must expect at least one diagnostic"
            raise ValueError(msg)
        if self.outcome is ExpectedOutcome.NO_MATCH and self.expected_count != 0:
            msg = "non-matching examples must expect zero diagnostics"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Source-owned documentation and compatibility metadata for one live rule."""

    engine: RuleEngine
    rule_id: RuleId
    code: str | None
    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    languages: frozenset[Language]
    autofix: AutofixPolicy = AutofixPolicy.NONE
    aliases: tuple[str, ...] = ()
    examples: tuple[RuleExample, ...] = ()
    limitations: tuple[str, ...] = ()
    file_patterns: tuple[str, ...] = ()
    message_ids: tuple[MessageId, ...] = ()
    options_schema: str | None = None
    references: tuple[str, ...] = ()
    since: str | None = None

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.fullmatch(self.rule_id):
            msg = "rule ID must be non-empty lowercase kebab-case"
            raise ValueError(msg)
        if self.code is not None and not self.code.strip():
            msg = "rule code must be non-empty when present"
            raise ValueError(msg)
        for label, value in (
            ("summary", self.summary),
            ("rationale", self.rationale),
            ("remediation", self.remediation),
        ):
            if not value.strip():
                msg = f"rule {label} must not be empty"
                raise ValueError(msg)
        if len(self.summary) > _MAX_SUMMARY_LENGTH or "\n" in self.summary:
            msg = "rule summary must be one concise line of at most 160 characters"
            raise ValueError(msg)
        if not self.languages:
            msg = "rule must name at least one language"
            raise ValueError(msg)
        if len(self.aliases) != len(set(self.aliases)) or any(
            not _KEBAB_CASE.fullmatch(alias) or alias == self.rule_id for alias in self.aliases
        ):
            msg = "rule aliases must be unique historical lowercase kebab-case IDs"
            raise ValueError(msg)
        example_ids = tuple(example.example_id for example in self.examples)
        if len(example_ids) != len(set(example_ids)):
            msg = "rule example IDs must be unique"
            raise ValueError(msg)
        if self.autofix is AutofixPolicy.NONE and any(example.fixed_files for example in self.examples):
            msg = "rules without autofix must not publish fixed example files"
            raise ValueError(msg)
        if len(self.message_ids) != len(set(self.message_ids)) or any(not value.strip() for value in self.message_ids):
            msg = "rule message IDs must be unique and non-empty"
            raise ValueError(msg)
        if len(self.file_patterns) != len(set(self.file_patterns)) or any(
            not pattern.strip() for pattern in self.file_patterns
        ):
            msg = "rule file patterns must be unique and non-empty"
            raise ValueError(msg)
        if any(not limitation.strip() for limitation in self.limitations):
            msg = "rule limitations must not be empty"
            raise ValueError(msg)
        if any(not reference.startswith("https://") for reference in self.references):
            msg = "rule references must use https"
            raise ValueError(msg)
        if self.since is not None and not self.since.strip():
            msg = "rule since version must not be empty when present"
            raise ValueError(msg)
        if self.options_schema is not None:
            try:
                parsed_schema: object = json.loads(self.options_schema)  # pyright: ignore[reportAny]
            except json.JSONDecodeError as exc:
                msg = "rule options schema must be valid JSON"
                raise ValueError(msg) from exc
            if not isinstance(parsed_schema, dict):
                msg = "rule options schema must be a JSON object"
                raise ValueError(msg)
        public_scenarios = {example.scenario for example in self.examples if example.public}
        for scenario in public_scenarios:
            pair = tuple(example for example in self.examples if example.public and example.scenario == scenario)
            if len(pair) != _PUBLIC_PAIR_SIZE or {example.outcome for example in pair} != {
                ExpectedOutcome.MATCH,
                ExpectedOutcome.NO_MATCH,
            }:
                msg = f"published example scenario {scenario!r} must contain both matching and non-matching cases exactly once"
                raise ValueError(msg)

    @property
    def key(self) -> str:
        """Return the collision-free, engine-qualified rule identity."""
        return f"{self.engine.value}:{self.rule_id}"


@dataclass(frozen=True, slots=True)
class RuleProblem:
    """A falsifiable lint problem, defined before implementation begins."""

    key: str
    summary: str
    harm: str
    languages: frozenset[Language]
    bad_examples: tuple[str, ...]
    good_examples: tuple[str, ...]
    exclusions: tuple[str, ...] = ()
    autofix: AutofixPolicy = AutofixPolicy.NONE

    def __post_init__(self) -> None:
        if not self.key or not self.key.replace("-", "").isalnum() or self.key != self.key.lower():
            msg = "problem key must be non-empty lowercase kebab-case"
            raise ValueError(msg)
        for label, value in (("summary", self.summary), ("harm", self.harm)):
            if not value.strip():
                msg = f"problem {label} must not be empty"
                raise ValueError(msg)
        if not self.languages:
            msg = "problem must name at least one language"
            raise ValueError(msg)
        if not self.bad_examples or not self.good_examples:
            msg = "problem must contain both bad and good examples"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CatalogRule:
    """One existing rule considered before adding custom code."""

    identifier: str
    summary: str
    origin: RuleOrigin
    languages: frozenset[Language]
    configurable: bool = False
    documentation: str | None = None

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.summary.strip():
            msg = "catalog rule identifier and summary must not be empty"
            raise ValueError(msg)
        if not self.languages:
            msg = "catalog rule must name at least one language"
            raise ValueError(msg)
        if self.documentation is not None and not self.documentation.startswith("https://"):
            msg = "catalog documentation must use https"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Finding:
    """A normalized finding returned by any candidate rule implementation."""

    rule_id: str
    line: int
    column: int
    message: str

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.message.strip():
            msg = "finding rule ID and message must not be empty"
            raise ValueError(msg)
        if self.line < 1 or self.column < 1:
            msg = "finding locations are one-based"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """Source used to falsify a candidate rule without leaking it into reports."""

    case_id: str
    language: Language
    source: str = field(repr=False)
    expected: ExpectedOutcome = ExpectedOutcome.NO_MATCH
    path: PurePosixPath = _DEFAULT_CASE_PATH
    private: bool = False

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.source:
            msg = "evaluation case ID and source must not be empty"
            raise ValueError(msg)
        if self.path.is_absolute() or ".." in self.path.parts:
            msg = "evaluation case paths must be safe relative paths"
            raise ValueError(msg)

    @property
    def report_path(self) -> str:
        """Return a stable path that never reveals a private corpus layout."""
        return "<private>" if self.private else self.path.as_posix()

    @property
    def report_id(self) -> str:
        """Redact private case labels before they enter a report."""
        return "<private>" if self.private else self.case_id
