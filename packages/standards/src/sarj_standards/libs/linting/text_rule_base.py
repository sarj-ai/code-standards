from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from sarj_rule_contracts import RuleDocumentation

from sarj_standards.libs.rules import (
    DefaultLevel,
    Language,
    MessageId,
    RuleEngine,
    RuleExample,
    RuleId,
    RuleSpec,
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def render(self) -> str:
        from sarj_standards.libs.linting import textlint  # ruff: ignore[import-outside-top-level] -- rendering consults live severity.

        meta = next(meta for meta in textlint.REGISTRY.values() if meta.code == self.code)
        rollout = " warning:" if not meta.blocking else ""
        return f"{self.path}:{self.line}:1: {self.code}{rollout} {self.message}"


@dataclass(frozen=True, kw_only=True)
class RuleMeta(RuleDocumentation):
    code: str
    languages: frozenset[Language]
    file_patterns: tuple[str, ...]
    message_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    since: str | None = None

    @property
    def blocking(self) -> bool:
        return self.default_level is DefaultLevel.ERROR

    @property
    def description(self) -> str:
        """Preserve the existing analysis adapter while ``summary`` becomes canonical."""
        return self.summary

    @property
    def public_examples(self) -> tuple[RuleExample, ...]:
        """Return only examples explicitly reviewed for public documentation."""
        return tuple(example for example in self.examples if example.public)

    def native_spec(self, rule_id: str) -> RuleSpec:
        return RuleSpec(
            engine=RuleEngine.TEXT,
            rule_id=RuleId(rule_id),
            code=self.code,
            summary=self.summary,
            rationale=self.rationale,
            remediation=self.remediation,
            category=self.category,
            default_level=self.default_level,
            languages=self.languages,
            autofix=self.autofix,
            aliases=self.aliases,
            examples=self.examples,
            limitations=self.limitations,
            file_patterns=self.file_patterns,
            message_ids=tuple(MessageId(message_id) for message_id in self.message_ids),
            references=self.references,
            since=self.since,
        )


class Rule(ABC):
    id: ClassVar[str]
    documentation: ClassVar[RuleMeta]

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Finding]: ...
