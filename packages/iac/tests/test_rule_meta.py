"""Every rule must be self-documenting: non-empty id, code, description, docstring."""

from __future__ import annotations

import pytest

from sarj_iac_lint.rule_base import Rule
from sarj_iac_lint.rules import REGISTRY


MIN_DESCRIPTION_LEN = 10


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_self_documenting_meta(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    assert issubclass(cls, Rule)
    assert cls.id == rule_id, f"REGISTRY key {rule_id!r} != cls.id {cls.id!r}"
    assert cls.id
    assert cls.id.replace("-", "").replace("_", "").isalnum()
    assert cls.code, f"{rule_id}: missing code"
    assert cls.code.startswith("SARJ"), f"{rule_id}: code must start with SARJ"
    assert cls.description
    assert len(cls.description) >= MIN_DESCRIPTION_LEN
    assert cls.__doc__, f"{rule_id}: missing docstring"


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id


def test_codes_unique() -> None:
    codes = [cls.code for cls in REGISTRY.values()]
    assert len(codes) == len(set(codes)), "duplicate SARJ codes"
