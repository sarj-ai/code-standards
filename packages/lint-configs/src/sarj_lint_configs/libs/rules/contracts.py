"""Value objects shared by rule discovery and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from pathlib import PurePosixPath


_DEFAULT_CASE_PATH = PurePosixPath("case.txt")


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
        """Pseudonymize private case labels before they enter a report."""
        if not self.private:
            return self.case_id
        fingerprint = hashlib.sha256(self.case_id.encode()).hexdigest()[:12]
        return f"<private:{fingerprint}>"
