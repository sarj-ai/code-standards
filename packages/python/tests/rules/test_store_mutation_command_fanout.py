from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.store_field_update_reuses_upsert import StoreFieldUpdateReusesUpsert
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


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("    set_name = other\n", id="class-shadow"),
        pytest.param("    async def set_name(self, key, name):\n        pass\n", id="duplicate-definition"),
        pytest.param("ItemStore.set_name = other\n", id="class-replacement"),
        pytest.param("del ItemStore.set_name\n", id="class-deletion"),
        pytest.param("ItemStore.upsert = other\n", id="command-replacement"),
    ],
)
def test_only_effective_declared_methods_are_reviewed(suffix: str) -> None:
    assert StoreMutationCommandFanout().check(P, BASE + suffix) == []


def test_instance_replacement_is_not_a_declared_setter() -> None:
    source = BASE.replace("        self.cursor = cursor", "        self.cursor = cursor\n        self.set_name = other")
    assert StoreMutationCommandFanout().check(P, source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("        self = other\n        return await self._insert(item)", id="rebound-self"),
        pytest.param("        async def unused():\n            return await self._insert(item)", id="nested-call"),
    ],
)
def test_helper_delegation_requires_the_method_receiver(replacement: str) -> None:
    source = BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, item):\n" + replacement + "\n    async def _insert(self, item):",
    )
    assert StoreMutationCommandFanout().check(P, source) == []


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param("    @staticmethod\n    async def upsert(self, item):", id="static-self-name"),
        pytest.param("    async def upsert(other, item):", id="nonreceiver-self-name"),
        pytest.param("    @other\n    async def upsert(self, item):", id="unknown-decorator"),
    ],
)
def test_helper_command_requires_an_instance_method(definition: str) -> None:
    source = BASE.replace(
        "    async def upsert(self, item):",
        definition + "\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert StoreMutationCommandFanout().check(P, source) == []


def test_positional_only_receiver_can_delegate() -> None:
    source = BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, /, item):\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert len(StoreMutationCommandFanout().check(P, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "import abc\nclass ItemStore:\n    abc = other\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="class-shadows-module",
        ),
        pytest.param(
            "from abc import abstractmethod as abstract\nclass ItemStore:\n    abstract = other\n    @abstract\n    def upsert(self, item): pass\n    @abstract\n    def set_name(self, key, name): pass\n",
            id="class-shadows-alias",
        ),
        pytest.param(
            "import abc\nabc.abstractmethod = other\nclass ItemStore:\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="mutated-decorator",
        ),
        pytest.param(
            "import abc\nclass ItemStore:\n    @other\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="unknown-outer-wrapper",
        ),
    ],
)
def test_abstract_policy_requires_the_runtime_decorator_binding(source: str) -> None:
    assert StoreMutationCommandFanout().check(P, source) == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        pytest.param("    import abc\n", "abc.abstractmethod", id="class-module-import"),
        pytest.param("    from abc import abstractmethod as abstract\n", "abstract", id="class-symbol-alias"),
    ],
)
def test_class_local_abstract_imports_are_recognized(imports: str, decorator: str) -> None:
    source = (
        "class ItemStore:\n"
        + imports
        + f"    @{decorator}\n    def upsert(self, item): pass\n"
        + f"    @{decorator}\n    def set_name(self, key, name): pass\n"
    )
    assert len(StoreMutationCommandFanout().check(P, source)) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("@other\nclass ItemStore:", id="class-decorator"),
        pytest.param("class ItemStore(metaclass=Other):", id="metaclass"),
    ],
)
def test_unknown_class_transformations_abstain(replacement: str) -> None:
    assert StoreMutationCommandFanout().check(P, BASE.replace("class ItemStore:", replacement)) == []


def test_known_final_class_decorator_preserves_direct_command() -> None:
    source = "from typing import final\n" + BASE.replace("class ItemStore:", "@final\nclass ItemStore:")
    assert len(StoreMutationCommandFanout().check(P, source)) == 1


def test_precise_ordinary_field_owner_takes_precedence() -> None:
    source = (
        BASE.replace("class ItemStore:", "class ItemInput:\n    id: str\n    name: str\nclass ItemStore:")
        .replace("upsert(self, item):", "upsert(self, item: ItemInput) -> Item:")
        .replace("set_name(self, key, name):", "set_name(self, key, name) -> Item:")
        .replace(" AND started_at IS NULL", "")
    )
    assert len(StoreFieldUpdateReusesUpsert().check(P, source)) == 1
    assert StoreMutationCommandFanout().check(P, source) == []
