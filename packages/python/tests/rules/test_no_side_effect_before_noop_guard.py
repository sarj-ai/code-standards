from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import Severity
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_side_effect_before_noop_guard import NoSideEffectBeforeNoopGuard


def test_documented_examples() -> None:
    verify_native_rule(NoSideEffectBeforeNoopGuard, analyze)


def _function(body: str) -> str:
    return "async def switch(self, target: str, items: list[str]) -> str | None:\n" + "".join(
        f"    {line}\n" for line in body.splitlines()
    )


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ("self.history.insert(make_call(target))\nif target == self.current:\n    return 'same'\nreturn target", 3),
        ("self.history.append(target)\ntry:\n    if target in self.seen:\n        return None\nfinally:\n    pass", 4),
        ("await self.events.publish(target)\nif target is None:\n    return None", 3),
        ("self.metrics.record_switch()\nx = 1\nif target not in items:\n    return None", 4),
    ],
)
def test_side_effect_before_guard(body: str, line: int) -> None:
    findings = NoSideEffectBeforeNoopGuard().check(Path("app/agent.py"), _function(body))
    assert [finding.line for finding in findings] == [line]
    assert findings[0].severity is Severity.WARNING
    assert "before the side effect" in findings[0].message


@pytest.mark.parametrize(
    "body",
    [
        "if target == self.current:\n    return 'same'\nself.history.insert(make_call(target))",
        "self.history.insert(target)\nif (latest := self.store.get(target)) is None:\n    return None",
        "self.history.insert(target)\nif self.lookup(target) == self.current:\n    return None",
        "self.history.insert(target)\nif self.current == 'en':\n    return None",
        "self.history.insert(target)\nif target == self.current:\n    return None\nelse:\n    pass",
        "self.history.insert(target)\nif target == self.current:\n    self.flush()",
        "self.history.insert(target)\nif target != self.current:\n    return None",
        "self.history.insert(target)\nif target == self.current or target is None:\n    return None",
        "logger.info(target)\nif target == self.current:\n    return None",
        "self.logger.warning(target)\nif target == self.current:\n    return None",
        "value = self.store.get(target)\nif target == self.current:\n    return None",
        "def helper():\n    self.history.insert(target)\nif target == self.current:\n    return None",
        "items.append(target)\nif target in items:\n    return None",
    ],
)
def test_guard_first_or_out_of_scope(body: str) -> None:
    assert NoSideEffectBeforeNoopGuard().check(Path("app/agent.py"), _function(body)) == []


def test_tests_are_skipped() -> None:
    source = _function("self.history.insert(target)\nif target == self.current:\n    return None")
    assert NoSideEffectBeforeNoopGuard().check(Path("tests/test_agent.py"), source) == []
