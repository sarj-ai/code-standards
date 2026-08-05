"""Deterministic lookup over known upstream and Sarj rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .contracts import CatalogRule, Language, RuleOrigin


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
