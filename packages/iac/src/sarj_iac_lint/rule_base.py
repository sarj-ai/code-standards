from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, Final, Self


if TYPE_CHECKING:
    from collections.abc import Sequence


_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)


class RuleCategory(StrEnum):
    """Small cross-engine taxonomy used by generated rule directories."""

    ARCHITECTURE = "architecture"
    CORRECTNESS = "correctness"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    SECURITY = "security"
    STYLE = "style"
    TESTING = "testing"


class AutofixPolicy(StrEnum):
    """Strongest source mutation a rule can safely offer."""

    NONE = "none"
    SUGGESTION = "suggestion"
    SAFE = "safe"


class ExampleOutcome(StrEnum):
    """Expected result when a rule checks one documentation example."""

    MATCH = "match"
    NO_MATCH = "no-match"


_KEBAB_CASE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SUMMARY_LENGTH: Final = 160
_PUBLIC_PAIR_SIZE: Final = 2
type ExamplePath = str


@dataclass(frozen=True, slots=True)
class ExampleFile:
    path: PurePosixPath
    source: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.name:
            msg = "example file paths must be safe relative paths"
            raise ValueError(msg)
        if not self.source:
            msg = "example file source must not be empty"
            raise ValueError(msg)

    @classmethod
    def iac(cls, path: ExamplePath, source: str) -> Self:
        return cls(PurePosixPath(path), source)


@dataclass(frozen=True, slots=True)
class RuleExample:
    example_id: str
    outcome: ExampleOutcome
    files: tuple[ExampleFile, ...]
    focus_path: PurePosixPath
    expected_count: int
    title: str
    public: bool = False
    fixed_files: tuple[ExampleFile, ...] = ()
    scenario: str = "primary"

    def __post_init__(self) -> None:
        if not _KEBAB_CASE.fullmatch(self.example_id):
            msg = "example ID must be lowercase kebab-case"
            raise ValueError(msg)
        if not _KEBAB_CASE.fullmatch(self.scenario):
            msg = "example scenario must be lowercase kebab-case"
            raise ValueError(msg)
        if not self.title.strip():
            msg = "example title must not be empty"
            raise ValueError(msg)
        paths = tuple(item.path for item in self.files)
        if not paths or len(paths) != len(set(paths)):
            msg = "example files must have unique paths"
            raise ValueError(msg)
        if self.focus_path not in paths:
            msg = "example focus path must name one example file"
            raise ValueError(msg)
        fixed_paths = tuple(item.path for item in self.fixed_files)
        if len(fixed_paths) != len(set(fixed_paths)):
            msg = "fixed example files must have unique paths"
            raise ValueError(msg)
        if self.expected_count < 0:
            msg = "example expected count must not be negative"
            raise ValueError(msg)
        if self.outcome is ExampleOutcome.MATCH and self.expected_count < 1:
            msg = "matching examples must expect at least one diagnostic"
            raise ValueError(msg)
        if self.outcome is ExampleOutcome.NO_MATCH and self.expected_count != 0:
            msg = "non-matching examples must expect zero diagnostics"
            raise ValueError(msg)

    @property
    def focus_file(self) -> ExampleFile:
        """Return the file a single-file native checker should inspect."""
        return next(item for item in self.files if item.path == self.focus_path)


@dataclass(frozen=True, slots=True)
class RuleDocumentation:
    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    autofix: AutofixPolicy = AutofixPolicy.NONE
    aliases: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    examples: tuple[RuleExample, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("summary", self.summary),
            ("rationale", self.rationale),
            ("remediation", self.remediation),
        ):
            if not value.strip():
                msg = f"rule {label} must not be empty"
                raise ValueError(msg)
        if "\n" in self.summary or len(self.summary) > _MAX_SUMMARY_LENGTH:
            msg = f"rule summary must be one line of at most {_MAX_SUMMARY_LENGTH} characters"
            raise ValueError(msg)
        if len(self.aliases) != len(set(self.aliases)) or any(
            not _KEBAB_CASE.fullmatch(alias) for alias in self.aliases
        ):
            msg = "rule aliases must be unique lowercase kebab-case IDs"
            raise ValueError(msg)
        if any(not limitation.strip() for limitation in self.limitations):
            msg = "rule limitations must not be empty"
            raise ValueError(msg)
        example_ids = tuple(example.example_id for example in self.examples)
        if len(example_ids) != len(set(example_ids)):
            msg = "rule example IDs must be unique"
            raise ValueError(msg)
        public_scenarios = {example.scenario for example in self.examples if example.public}
        for scenario in public_scenarios:
            pair = tuple(example for example in self.examples if example.public and example.scenario == scenario)
            if len(pair) != _PUBLIC_PAIR_SIZE or {example.outcome for example in pair} != {
                ExampleOutcome.MATCH,
                ExampleOutcome.NO_MATCH,
            }:
                msg = f"published example scenario {scenario!r} must contain both matching and non-matching cases exactly once"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NativeRuleSpec:
    engine: str
    rule_id: str
    code: str
    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    autofix: AutofixPolicy
    aliases: tuple[str, ...]
    limitations: tuple[str, ...]
    examples: tuple[RuleExample, ...]

    @property
    def key(self) -> str:
        """Return the collision-free rule identity used by configuration and URLs."""
        return f"{self.engine}:{self.rule_id}"

    @property
    def public_examples(self) -> tuple[RuleExample, ...]:
        """Expose only fixtures explicitly reviewed for publication."""
        return tuple(example for example in self.examples if example.public)


def is_suppressed(source_lines: Sequence[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `# sarj-noqa[: CODE]` comment."""
    if line < 1 or line > len(source_lines):
        return False
    m = _SARJ_NOQA_RE.search(source_lines[line - 1])
    if not m:
        return False
    codes_str = m.group(1)
    if not codes_str:
        return True
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
    return code.upper() in codes


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: Path
    line: int
    col: int
    code: str
    message: str
    suppressible: bool = True
    baselineable: bool = True

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


class Rule(ABC):
    id: str
    code: str
    description: str
    documentation: ClassVar[RuleDocumentation | None] = None

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError

    @classmethod
    def native_spec(cls) -> NativeRuleSpec | None:
        authored = cls.documentation
        if authored is None:
            return None
        if cls.id in authored.aliases:
            msg = f"{cls.id}: a live rule ID cannot also be a historical alias"
            raise ValueError(msg)
        if authored.summary != cls.description:
            msg = f"{cls.id}: description must be the authored documentation summary"
            raise ValueError(msg)
        return NativeRuleSpec(
            engine="iac",
            rule_id=cls.id,
            code=cls.code,
            summary=authored.summary,
            rationale=authored.rationale,
            remediation=authored.remediation,
            category=authored.category,
            autofix=authored.autofix,
            aliases=authored.aliases,
            limitations=authored.limitations,
            examples=authored.examples,
        )

    @classmethod
    def public_examples(cls) -> tuple[RuleExample, ...]:
        spec = cls.native_spec()
        return () if spec is None else spec.public_examples
