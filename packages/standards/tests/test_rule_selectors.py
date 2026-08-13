"""Typed rule selectors reject malformed identities at the public boundary."""

from __future__ import annotations

import pytest

from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelection, RuleSelector


@pytest.mark.parametrize("engine", RuleEngine)
def test_rule_selector_round_trips_every_engine(engine: RuleEngine) -> None:
    selector = RuleSelector(engine, RuleId("no-ambiguous-rule"))

    assert RuleSelector.parse(str(selector)) == selector


@pytest.mark.parametrize(
    "value",
    [
        "",
        "python",
        "python:",
        ":no-rule",
        "python:no_rule",
        "python:NoRule",
        "python:no/rule",
        "python:no-rule:extra",
        "ruff:no-rule",
    ],
)
def test_rule_selector_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match=r"rule selector|rule ID|unknown"):
        RuleSelector.parse(value)


def test_rule_selection_normalizes_strings_and_selectors_without_duplicates() -> None:
    python_rule = RuleSelector(RuleEngine.PYTHON, RuleId("no-rule"))

    selection = RuleSelection.from_values((python_rule, "eslint:no-alert", "python:no-rule"))

    assert selection.selectors == frozenset(
        {
            python_rule,
            RuleSelector(RuleEngine.ESLINT, RuleId("no-alert")),
        }
    )
    assert selection.engines == frozenset({RuleEngine.PYTHON, RuleEngine.ESLINT})
    assert selection.ids_for(RuleEngine.PYTHON) == frozenset({RuleId("no-rule")})
    assert selection.native_ids_for(RuleEngine.ESLINT) == frozenset({"@sarj/no-alert"})


def test_rule_selection_rejects_one_bare_string() -> None:
    with pytest.raises(TypeError, match="not one string"):
        RuleSelection.from_values("python:no-rule")
