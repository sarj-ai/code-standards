from __future__ import annotations

import json
from pathlib import Path
from typing import TypeGuard

import pytest

from sarj_standards.libs.repository import third_party_catalog_artifact


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = REPO_ROOT / "apps/docs/src/generated/third-party-rules.v1.json"


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)  # pyright: ignore[reportUnknownVariableType]
    return value  # pyright: ignore[reportUnknownVariableType]


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _array(value: object) -> list[object]:
    assert _is_array(value)
    return value


def test_parse_enabled_ruff_rules_reads_the_resolved_settings_block() -> None:
    settings = """
linter.rules.enabled = [
    unused-import (F401),
    prefer-isinstance-type-compare (FURB189),
]
linter.rules.should_fix = [
]
"""

    assert third_party_catalog_artifact.parse_enabled_ruff_rules(settings) == {"F401", "FURB189"}


def test_parse_enabled_ruff_rules_rejects_missing_block() -> None:
    with pytest.raises(ValueError, match=r"omitted linter\.rules\.enabled"):
        third_party_catalog_artifact.parse_enabled_ruff_rules("linter.preview = true\n")


def test_committed_third_party_catalog_has_a_closed_effective_inventory() -> None:
    payload = _object(json.loads(ARTIFACT.read_text(encoding="utf-8")))  # pyright: ignore[reportAny]
    assert set(payload) == {"profiles", "providers", "rules", "schemaVersion"}
    assert payload["schemaVersion"] == 1
    assert payload["profiles"] == ["application", "standard"]

    providers = [_object(value) for value in _array(payload["providers"])]
    rules = [_object(value) for value in _array(payload["rules"])]
    provider_ids = {value["id"] for value in providers}
    assert provider_ids == {value["provider"] for value in rules}
    assert {value["engine"] for value in providers} == {"eslint", "ruff"}
    assert "@sarj" not in provider_ids
    assert {"eslint", "ruff", "typescript-eslint", "unicorn"} <= provider_ids
    assert len({value["key"] for value in rules}) == len(rules)

    for rule in rules:
        assert set(rule) == {
            "autofix",
            "displayId",
            "docsUrl",
            "family",
            "hasSuggestions",
            "id",
            "key",
            "profiles",
            "provider",
            "summary",
        }
        assert str(rule["docsUrl"]).startswith("https://")
        assert rule["key"] == f"{rule['provider']}:{rule['id']}"
        assert rule["autofix"] in {"always", "available", "none", "sometimes"}
        assert _array(rule["profiles"])
