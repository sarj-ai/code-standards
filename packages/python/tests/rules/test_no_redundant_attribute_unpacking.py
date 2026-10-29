from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_redundant_attribute_unpacking import NoRedundantAttributeUnpacking


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


@pytest.fixture
def rule() -> Rule:
    return NoRedundantAttributeUnpacking()


def test_documented_examples() -> None:
    verify_native_rule(NoRedundantAttributeUnpacking, analyze)


@pytest.mark.parametrize(
    "source",
    [
        "def test_save(seed):\n    scenario, current = seed.scenario, seed.current\n",
        "async def test_save(seed):\n    [scenario, current] = [seed.scenario, seed.current]\n",
    ],
)
def test_reports_repeated_attribute_names(rule: Rule, source: str) -> None:
    [finding] = rule.check(Path("tests/test_save.py"), source)
    assert finding.code == "SARJ554"


@pytest.mark.parametrize(
    "source",
    [
        "def test_save(seed):\n    assert seed.scenario.id == seed.current.id\n",
        "def test_save(seed):\n    original, version = seed.scenario, seed.current\n",
        "def test_save(seed, other):\n    scenario, current = seed.scenario, other.current\n",
        "def test_save(seed):\n    seed, current = seed.seed, seed.current\n",
        "scenario, current = seed.scenario, seed.current\n",
        "def test_save(seed):\n    scenario, current = seed.scenario, seed.current  # sarj-noqa: SARJ554 -- Retain the values before the next publication changes seed.\n",
    ],
)
def test_preserves_distinct_contracts(rule: Rule, source: str) -> None:
    assert rule.check(Path("tests/test_save.py"), source) == []


def test_nested_function_report_is_not_duplicated(rule: Rule) -> None:
    source = "def setup(seed):\n    def extract():\n        scenario, current = seed.scenario, seed.current\n"
    assert len(rule.check(Path("tests/test_save.py"), source)) == 1


def test_branch_normalization_keeps_common_retry_bindings(rule: Rule) -> None:
    source = "def retry(conflict, state, loaded):\n    if conflict:\n        updated_at, latest_version_id = state.updated_at, state.latest_version_id\n    else:\n        updated_at, latest_version_id = loaded.updated_at, loaded.applied_version_id\n    return send(updated_at, latest_version_id)\n"
    assert rule.check(Path("app/retry.py"), source) == []
