from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeGuard

from sarj_standards.libs.rules.contracts import RuleSelector


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


SCHEMA_VERSION = 1


def load(path: Path) -> tuple[RuleSelector, ...]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot load rule warning lifecycle {path}: {exc}"
        raise ValueError(msg) from exc
    return validate(payload)


def validate(payload: object) -> tuple[RuleSelector, ...]:
    if not _is_object(payload) or set(payload) != {"schemaVersion", "rules"}:
        msg = "rule warning lifecycle must contain exactly schemaVersion and rules"
        raise ValueError(msg)
    raw_rules = payload.get("rules")
    if payload.get("schemaVersion") != SCHEMA_VERSION or not _is_array(raw_rules):
        msg = f"rule warning lifecycle must use schemaVersion {SCHEMA_VERSION} and a rules array"
        raise ValueError(msg)
    if any(not isinstance(value, str) or not value for value in raw_rules):
        msg = "rule warning lifecycle must contain unique non-empty canonical selectors"
        raise ValueError(msg)

    values = tuple(value for value in raw_rules if isinstance(value, str))
    selectors = tuple(RuleSelector.parse(value) for value in values)
    if len(set(selectors)) != len(selectors) or any(
        str(selector) != value for selector, value in zip(selectors, values, strict=True)
    ):
        msg = "rule warning lifecycle must contain unique non-empty canonical selectors"
        raise ValueError(msg)
    return selectors


def render(selectors: Iterable[RuleSelector]) -> str:
    values = tuple(str(selector) for selector in selectors)
    if len(values) != len(set(values)):
        msg = "rule warning lifecycle cannot render duplicate selectors"
        raise ValueError(msg)
    return (
        json.dumps(
            {"schemaVersion": SCHEMA_VERSION, "rules": sorted(values)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
