"""Deterministic lookup over known upstream and Sarj rules."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Self

from .contracts import (
    CatalogRule,
    DefaultLevel,
    ExpectedOutcome,
    Language,
    RuleOrigin,
    RuleSpec,
    RuleStatus,
)


if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class RuleCatalog:
    """An immutable rule catalog with exact, explainable filters."""

    rules: tuple[CatalogRule, ...]

    @classmethod
    def from_rules(cls, rules: Iterable[CatalogRule]) -> Self:
        collected = tuple(rules)
        identifiers = [rule.identifier for rule in collected]
        if len(identifiers) != len(set(identifiers)):
            msg = "catalog rule identifiers must be unique"
            raise ValueError(msg)
        return cls(tuple(sorted(collected, key=lambda rule: rule.identifier)))

    def get(self, identifier: str) -> CatalogRule | None:
        """Return one exact rule without fuzzy or model-dependent matching."""
        return next((rule for rule in self.rules if rule.identifier == identifier), None)

    def filter(
        self,
        *,
        language: Language | None = None,
        origin: RuleOrigin | None = None,
        configurable: bool | None = None,
    ) -> tuple[CatalogRule, ...]:
        """Return rules matching every explicit filter."""
        return tuple(
            rule
            for rule in self.rules
            if (language is None or language in rule.languages)
            and (origin is None or rule.origin is origin)
            and (configurable is None or rule.configurable is configurable)
        )


@dataclass(frozen=True, slots=True)
class DocumentedRule:
    """One live rule plus only the derived state needed by public consumers."""

    spec: RuleSpec
    default_level: DefaultLevel
    source: PurePosixPath
    test: PurePosixPath
    status: RuleStatus = RuleStatus.ACTIVE

    def __post_init__(self) -> None:
        if self.status is not RuleStatus.ACTIVE:
            msg = "documented live rules must have active status; lifecycle tombstones are separate"
            raise ValueError(msg)
        for path in (self.source, self.test):
            if path.is_absolute() or ".." in path.parts or not path.name or "\\" in path.as_posix():
                msg = "catalog source and test paths must be safe repository-relative paths"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RuleCatalogDocument:
    """Versioned, deterministic public catalog generated from native rule specs."""

    rules: tuple[DocumentedRule, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            msg = "unsupported rule catalog schema version"
            raise ValueError(msg)
        keys = tuple(rule.spec.key for rule in self.rules)
        if len(keys) != len(set(keys)):
            msg = "catalog rule keys must be unique"
            raise ValueError(msg)
        aliases = tuple(f"{rule.spec.engine.value}:{alias}" for rule in self.rules for alias in rule.spec.aliases)
        if len(aliases) != len(set(aliases)) or set(aliases) & set(keys):
            msg = "catalog aliases must be unique and must not shadow live rule keys"
            raise ValueError(msg)

    def as_public_dict(self) -> dict[str, object]:
        """Serialize reviewed public data without timestamps or private cases."""
        return {
            "schemaVersion": self.schema_version,
            "rules": [self._rule_dict(rule) for rule in sorted(self.rules, key=lambda item: item.spec.key)],
        }

    @staticmethod
    def _rule_dict(rule: DocumentedRule) -> dict[str, object]:
        spec = rule.spec
        examples = sorted(
            (example for example in spec.examples if example.public),
            key=lambda example: example.example_id,
        )
        return {
            "key": spec.key,
            "engine": spec.engine.value,
            "id": spec.rule_id,
            "code": spec.code,
            "summary": spec.summary,
            "rationale": spec.rationale,
            "remediation": spec.remediation,
            "category": spec.category.value,
            "languages": sorted(language.value for language in spec.languages),
            "defaultLevel": rule.default_level.value,
            "autofix": spec.autofix.value,
            "status": rule.status.value,
            "aliases": sorted(spec.aliases),
            "limitations": list(spec.limitations),
            "filePatterns": list(spec.file_patterns),
            "messageIds": list(spec.message_ids),
            "optionsSchema": json.loads(spec.options_schema) if spec.options_schema is not None else None,
            "references": list(spec.references),
            "since": spec.since,
            "source": rule.source.as_posix(),
            "test": rule.test.as_posix(),
            "examples": [
                {
                    "id": example.example_id,
                    "scenarioId": example.scenario,
                    "title": example.title,
                    "outcome": "reject" if example.outcome is ExpectedOutcome.MATCH else "accept",
                    "focusPath": example.focus_path.as_posix(),
                    "expectedCount": example.expected_count,
                    "files": [
                        {"path": item.path.as_posix(), "source": item.source}
                        for item in sorted(example.files, key=lambda item: item.path)
                    ],
                    "fixedFiles": [
                        {"path": item.path.as_posix(), "source": item.source}
                        for item in sorted(example.fixed_files, key=lambda item: item.path)
                    ],
                }
                for example in examples
            ],
        }
