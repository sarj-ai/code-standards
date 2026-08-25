from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


_ROOT = Path(__file__).parents[3]
_CONFIGS = _ROOT / "packages/standards/src/sarj_standards/configs"
_INVENTORY = _CONFIGS / "rule-inventory.v1.json"
_CAMPAIGN = _CONFIGS / "rule-calibration-campaign.v1.json"


class _RuleEntry(TypedDict):
    family: str
    id: str


class _Inventory(TypedDict):
    rules: list[_RuleEntry]


class _TaskEntry(TypedDict):
    task: str
    family: str
    ruleId: str
    state: str


class _Campaign(TypedDict):
    tasks: list[_TaskEntry]


def _object_table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)  # pyright: ignore[reportUnknownVariableType]
    return value  # pyright: ignore[reportUnknownVariableType]


def _object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value  # pyright: ignore[reportUnknownVariableType]


def _read_json(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    return _object_table(value)


def _load_inventory() -> _Inventory:
    raw_rules = _object_list(_read_json(_INVENTORY)["rules"])
    rules: list[_RuleEntry] = []
    for item in raw_rules:
        table = _object_table(item)
        family, rule_id = table["family"], table["id"]
        assert isinstance(family, str)
        assert isinstance(rule_id, str)
        rules.append({"family": family, "id": rule_id})
    return {"rules": rules}


def _load_campaign() -> _Campaign:
    raw_tasks = _object_list(_read_json(_CAMPAIGN)["tasks"])
    tasks: list[_TaskEntry] = []
    for item in raw_tasks:
        table = _object_table(item)
        name, family = table["task"], table["family"]
        rule_id, state = table["ruleId"], table["state"]
        assert isinstance(name, str)
        assert isinstance(family, str)
        assert isinstance(rule_id, str)
        assert isinstance(state, str)
        tasks.append({"task": name, "family": family, "ruleId": rule_id, "state": state})
    return {"tasks": tasks}


def test_every_live_rule_has_exactly_one_calibration_task() -> None:
    inventory = _load_inventory()
    campaign = _load_campaign()
    live = {(rule["family"], rule["id"]) for rule in inventory["rules"]}
    tasked = {(task["family"], task["ruleId"]) for task in campaign["tasks"]}

    assert len(campaign["tasks"]) == len(tasked)
    assert tasked == live


def test_calibration_tasks_have_stable_names_and_valid_states() -> None:
    campaign = _load_campaign()
    names = [task["task"] for task in campaign["tasks"]]
    assert len(names) == len(set(names))
    assert all(name.startswith("rule-audit/") for name in names)
    assert {task["state"] for task in campaign["tasks"]} <= {"pending", "complete"}
