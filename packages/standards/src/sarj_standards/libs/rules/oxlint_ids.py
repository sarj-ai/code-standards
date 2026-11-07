from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self

from sarj_standards._meta import OXLINT_RULE_MAP
from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


LEGACY_SOURCE: Final = "eslint"
SOURCE: Final = "oxlint"
_EVERY_RULE: Final = "*"


@dataclass(frozen=True, slots=True)
class OxlintRuleMap:
    # ESLint rule ID -> the Oxlint rule IDs that report its findings now; empty when Oxlint dropped it.
    oxlint_ids: Mapping[str, tuple[str, ...]]

    @classmethod
    def load(cls, path: Path) -> Self:
        document = parse_json(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            msg = f"{path.name} must map ESLint rule IDs to entries"
            raise TypeError(msg)
        return cls(
            MappingProxyType({eslint_id: _oxlint_ids(path, eslint_id, entry) for eslint_id, entry in document.items()})
        )

    def rule_ids(self, eslint_id: str) -> tuple[str, ...]:
        # An ID outside the table (a catalog key, an unmanaged rule) keeps its name.
        return self.oxlint_ids.get(eslint_id, (eslint_id,))

    def eslint_ids(self, oxlint_id: str) -> tuple[str, ...]:
        renamed = tuple(sorted(eslint_id for eslint_id, targets in self.oxlint_ids.items() if oxlint_id in targets))
        return renamed if renamed or oxlint_id in self.oxlint_ids else (oxlint_id,)


def _oxlint_ids(path: Path, eslint_id: str, entry: JsonValue) -> tuple[str, ...]:
    value = entry.get("oxlintId", "") if isinstance(entry, dict) else ""
    if value is None:
        return ()
    targets = value if isinstance(value, list) else [value]
    if not targets or any(not isinstance(target, str) or not target for target in targets):
        msg = f"{path.name} entry {eslint_id!r} needs an oxlintId string, non-empty string list or null"
        raise ValueError(msg)
    return tuple(target for target in targets if isinstance(target, str))


@cache
def bundled() -> OxlintRuleMap:
    return OxlintRuleMap.load(OXLINT_RULE_MAP)


def canonical_selectors(selector: str, rule_map: OxlintRuleMap | None = None) -> tuple[str, ...]:
    # `eslint:` stays accepted forever: registries, manifests and baselines written for ESLint keep
    # selecting the same findings. Empty when the selector named a rule Oxlint does not run.
    source, separator, rule_id = selector.partition(":")
    if not separator or source != LEGACY_SOURCE:
        return (selector,)
    if rule_id == _EVERY_RULE:
        return (f"{SOURCE}:{rule_id}",)
    return tuple(f"{SOURCE}:{target}" for target in (rule_map or bundled()).rule_ids(rule_id))


def legacy_selectors(selector: str, rule_map: OxlintRuleMap | None = None) -> tuple[str, ...]:
    # Baselines recorded before Oxlint name the same findings with these spellings.
    source, separator, rule_id = selector.partition(":")
    if not separator or source != SOURCE:
        return ()
    if rule_id == _EVERY_RULE:
        return (f"{LEGACY_SOURCE}:{rule_id}",)
    return tuple(f"{LEGACY_SOURCE}:{eslint_id}" for eslint_id in (rule_map or bundled()).eslint_ids(rule_id))
