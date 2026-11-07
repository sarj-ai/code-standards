from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelection, RuleSelector, oxlint_ids


if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


@pytest.mark.parametrize("engine", RuleEngine)
def test_rule_selector_round_trips_every_engine(engine: RuleEngine) -> None:
    rule_id = "CKV_GCP_41" if engine is RuleEngine.CHECKOV else "no-ambiguous-rule"
    selector = RuleSelector(engine, RuleId(rule_id))

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

    selection = RuleSelection.from_values((python_rule, "oxlint:no-alert", "eslint:no-alert", "python:no-rule"))

    assert selection.selectors == frozenset(
        {
            python_rule,
            RuleSelector(RuleEngine.OXLINT, RuleId("no-alert")),
        }
    )
    assert selection.engines == frozenset({RuleEngine.PYTHON, RuleEngine.OXLINT})
    assert selection.ids_for(RuleEngine.PYTHON) == frozenset({RuleId("no-rule")})
    assert selection.native_ids_for(RuleEngine.OXLINT) == frozenset({"@sarj/no-alert"})


def test_rule_selection_rejects_one_bare_string() -> None:
    with pytest.raises(TypeError, match="not one string"):
        RuleSelection.from_values("python:no-rule")


@pytest.mark.parametrize(
    ("legacy", "current"),
    [
        ("eslint:@sarj/no-alert", "oxlint:@sarj/no-alert"),
        ("eslint:no-alert", "oxlint:no-alert"),
        ("eslint:*", "oxlint:*"),
    ],
)
def test_eslint_selectors_round_trip_to_their_oxlint_spelling(legacy: str, current: str) -> None:
    assert oxlint_ids.canonical_selectors(legacy) == (current,)
    assert oxlint_ids.canonical_selectors(current) == (current,)
    assert legacy in oxlint_ids.legacy_selectors(current)


def test_eslint_selectors_follow_the_oxlint_rule_map(tmp_path: Path) -> None:
    path = tmp_path / "oxlint.rule-map.json"
    path.write_text(
        json.dumps(
            {
                "@typescript-eslint/no-explicit-any": {"kind": "native", "oxlintId": "typescript/no-explicit-any"},
                "regexp/no-missing-g-flag": {
                    "kind": "replaced",
                    "oxlintId": ["oxc/bad-replace-all-arg", "oxc/bad-match-all-arg"],
                },
                "no-sync": {"kind": "dropped", "oxlintId": None},
                "eqeqeq": {"kind": "native", "oxlintId": "eqeqeq"},
            }
        ),
        encoding="utf-8",
    )
    rule_map = oxlint_ids.OxlintRuleMap.load(path)

    assert oxlint_ids.canonical_selectors("eslint:@typescript-eslint/no-explicit-any", rule_map) == (
        "oxlint:typescript/no-explicit-any",
    )
    assert oxlint_ids.canonical_selectors("eslint:regexp/no-missing-g-flag", rule_map) == (
        "oxlint:oxc/bad-replace-all-arg",
        "oxlint:oxc/bad-match-all-arg",
    )
    assert oxlint_ids.canonical_selectors("eslint:no-sync", rule_map) == ()
    assert oxlint_ids.canonical_selectors("eslint:no-alert", rule_map) == ("oxlint:no-alert",)
    assert oxlint_ids.canonical_selectors("sarj-python-lint:no-print", rule_map) == ("sarj-python-lint:no-print",)
    assert oxlint_ids.legacy_selectors("oxlint:typescript/no-explicit-any", rule_map) == (
        "eslint:@typescript-eslint/no-explicit-any",
    )
    assert oxlint_ids.legacy_selectors("oxlint:oxc/bad-match-all-arg", rule_map) == ("eslint:regexp/no-missing-g-flag",)
    assert oxlint_ids.legacy_selectors("oxlint:eqeqeq", rule_map) == ("eslint:eqeqeq",)
    assert oxlint_ids.legacy_selectors("python:no-print", rule_map) == ()


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"kind": "native"}, id="missing"),
        pytest.param({"oxlintId": ""}, id="empty-name"),
        pytest.param({"oxlintId": []}, id="empty-list"),
        pytest.param({"oxlintId": [1]}, id="non-string"),
        pytest.param("native", id="not-an-object"),
    ],
)
def test_oxlint_rule_map_rejects_entries_without_an_oxlint_id(tmp_path: Path, entry: JsonValue) -> None:
    path = tmp_path / "oxlint.rule-map.json"
    path.write_text(json.dumps({"no-alert": entry}), encoding="utf-8")

    with pytest.raises(ValueError, match="needs an oxlintId"):
        oxlint_ids.OxlintRuleMap.load(path)


def test_bundled_rule_map_keeps_sarj_rule_names() -> None:
    rule_map = oxlint_ids.bundled()

    assert all(
        targets == (eslint_id,) for eslint_id, targets in rule_map.oxlint_ids.items() if eslint_id.startswith("@sarj/")
    )
