"""Every rule must be self-documenting: non-empty id, code, description, and a docstring."""

from __future__ import annotations

import pytest

from sarj_sql_lint.rule_base import Rule
from sarj_sql_lint.rules import REGISTRY


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_self_documenting_meta(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    assert issubclass(cls, Rule)

    assert cls.id == rule_id, f"REGISTRY key {rule_id!r} != cls.id {cls.id!r}"
    assert cls.id
    assert cls.id.replace("-", "").replace("_", "").isalnum()

    assert cls.code, f"{rule_id}: missing code"
    assert cls.code.startswith("SARJ"), f"{rule_id}: code {cls.code!r} must start with SARJ"

    assert cls.description, f"{rule_id}: empty description"
    assert len(cls.description) >= 10

    assert cls.__doc__, f"{rule_id}: missing docstring"


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id
