from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.store_mutation_command_fanout import StoreMutationCommandFanout


P = Path("app/item_store.py")
BASE = """from psycopg import AsyncCursor
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor
    async def upsert(self, item):
        await self.cursor.execute('INSERT INTO item(id, name) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name', (item.id, item.name))
    async def set_name(self, key, name):
        await self.cursor.execute('UPDATE item SET name=%s WHERE id=%s AND started_at IS NULL', (name,key))
"""


def test_documented_examples() -> None:
    verify_native_rule(StoreMutationCommandFanout, analyze)


def test_guarded_setter_requires_review_without_upsert_replacement() -> None:
    [finding] = StoreMutationCommandFanout().check(P, BASE)
    assert finding.code == "SARJ546"
    assert "concurrency" in finding.message
    assert finding.severity.value == "warning"


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(("UPDATE item", "UPDATE other"), id="different-relation"),
        pytest.param(("async def upsert", "async def create"), id="no-model-command"),
        pytest.param(("async def set_name", "async def transition"), id="explicit-transition"),
        pytest.param(("UPDATE item", "DELETE FROM item"), id="different-operation"),
    ],
)
def test_other_owners_and_operations_are_preserved(change: tuple[str, str]) -> None:
    assert StoreMutationCommandFanout().check(P, BASE.replace(*change)) == []


def test_upsert_can_delegate_to_direct_class_helper() -> None:
    source = BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, item):\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert len(StoreMutationCommandFanout().check(P, source)) == 1


def test_name_upsert_does_not_prove_its_duplicate_policy() -> None:
    source = BASE.replace(" ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name", "")
    assert len(StoreMutationCommandFanout().check(P, source)) == 1


def test_abstract_setter_policy_uses_actual_abstract_decorator() -> None:
    source = """import abc
class ItemStore(abc.ABC):
    @abc.abstractmethod
    def upsert(self, item): pass
    @abc.abstractmethod
    def set_name_before_start(self, key, name): pass
"""
    assert len(StoreMutationCommandFanout().check(P, source)) == 1
    assert StoreMutationCommandFanout().check(P, source.replace("import abc", "import other as abc")) == []


def test_test_and_generated_sources_are_excluded() -> None:
    assert StoreMutationCommandFanout().check(Path("tests/item_store.py"), BASE) == []
    assert StoreMutationCommandFanout().check(P, "# Code generated. DO NOT EDIT.\n" + BASE) == []


def test_repeated_updates_in_one_method_have_one_finding() -> None:
    line = "        await self.cursor.execute('UPDATE item SET name=%s WHERE id=%s AND started_at IS NULL', (name,key))"
    assert len(StoreMutationCommandFanout().check(P, BASE.replace(line, line + "\n" + line))) == 1
