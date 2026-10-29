from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_recording_store import NoRecordingStore


P = Path("tests/fakes/call_store.py")
_CONTRACT = "class Store:\n    def get(self, key): ...\n    def upsert(self, item): ...\n"
_RECORD = "class Recorder(Store):\n    def __init__(self):\n        self.writes: list[object] = []\n    def upsert(self, item):\n        self.writes.append(item)\n        return item\n"


def test_documented_examples() -> None:
    verify_native_rule(NoRecordingStore, analyze)


def test_records_source_visible_store_mutations() -> None:
    findings = NoRecordingStore().check(P, _CONTRACT + _RECORD)
    assert len(findings) == 1
    assert findings[0].code == "SARJ544"


def test_synthetic_async_mutation_is_also_recording() -> None:
    assert (
        len(
            NoRecordingStore().check(
                P,
                _CONTRACT
                + _RECORD.replace(
                    "def upsert(self, item):\n        self", "async def upsert(self, item):\n        self"
                ),
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "replacement",
    [
        "return super().upsert(item)",
        "return await self.real.upsert(item)",
        "return self.real.upsert(item)",
        "return real.upsert(item)",
        "return self._write(item)",
    ],
)
def test_delegation_to_persistence_is_preserved(replacement: str) -> None:
    assert NoRecordingStore().check(P, _CONTRACT + _RECORD.replace("return item", replacement)) == []


def test_name_alone_cannot_identify_recording() -> None:
    source = (
        _CONTRACT + "class RecordingStore(Store):\n    def upsert(self, item):\n        return self.real.upsert(item)\n"
    )
    assert NoRecordingStore().check(P, source) == []


def test_unrelated_recorder_is_valid() -> None:
    assert NoRecordingStore().check(P, _RECORD.replace("Recorder(Store)", "Recorder")) == []


def test_unknown_external_base_abstains() -> None:
    assert NoRecordingStore().check(P, "from external import Store\n" + _RECORD) == []


def test_non_test_source_is_outside_scope() -> None:
    assert NoRecordingStore().check(Path("app/call_store.py"), _CONTRACT + _RECORD) == []


def test_no_duplicate_per_recorded_method() -> None:
    source = _CONTRACT + _RECORD + "    def get(self, key):\n        self.writes.append(key)\n        return key\n"
    assert len(NoRecordingStore().check(P, source)) == 1


def test_exact_code_suppression() -> None:
    source = _CONTRACT + _RECORD.replace(
        "class Recorder(Store):", "class Recorder(Store):  # sarj-noqa: SARJ544 -- transport-only isolation proof"
    )
    assert NoRecordingStore().check(P, source) == []


def test_malformed_input_abstains() -> None:
    assert NoRecordingStore().check(P, "class Recorder(") == []


def test_unknown_free_function_can_persist_and_must_not_be_called_recording_only() -> None:
    source = _CONTRACT + _RECORD.replace("self.writes.append(item)", "persist(item)\n        self.writes.append(item)")
    assert NoRecordingStore().check(P, source) == []


def test_source_visible_model_constructor_is_a_synthetic_record() -> None:
    source = (
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    id: str\n"
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(id=str(item))")
    )
    assert len(NoRecordingStore().check(P, source)) == 1


def test_source_visible_newtype_and_dataclass_value_construction() -> None:
    source = (
        """from typing import NewType
from dataclasses import dataclass
ItemId = NewType('ItemId', str)
@dataclass(frozen=True)
class Item:
    id: ItemId
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(id=ItemId(str(item)))")
    )
    assert len(NoRecordingStore().check(P, source)) == 1
    assert NoRecordingStore().check(P, source.replace("NewType('ItemId', str)", "custom('ItemId', str)")) == []


def test_imported_newtype_needs_native_provider_proof(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    types = package / "ids.py"
    types.write_text("from typing import NewType\nItemId = NewType('ItemId', str)\n")
    target = package / "test_store.py"
    target.write_text(
        "from app.ids import ItemId\n" + _CONTRACT + _RECORD.replace("return item", "return ItemId(str(item))")
    )
    assert len(analyze([NoRecordingStore.id], [target, types])) == 1
    types.write_text("from other import NewType\nItemId = NewType('ItemId', str)\n")
    assert analyze([NoRecordingStore.id], [target, types]) == []


def test_custom_dataclass_post_init_retains_unknown_effects() -> None:
    source = (
        """from dataclasses import dataclass
@dataclass
class Item:
    id: str
    def __post_init__(self):
        persist(self)
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(id=str(item))")
    )
    assert NoRecordingStore().check(P, source) == []


def test_custom_dataclass_field_factory_retains_unknown_effects() -> None:
    source = (
        """from dataclasses import dataclass, field
@dataclass
class Item:
    id: str
    receipt: str = field(default_factory=persist)
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(id=str(item))")
    )
    assert NoRecordingStore().check(P, source) == []


def test_mutated_native_newtype_provider_keeps_unknown_effects() -> None:
    source = (
        """import typing
typing.NewType = custom
ItemId = typing.NewType('ItemId', str)
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return ItemId(str(item))")
    )
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "self.real.append(item)\n        return item",
        "database[item.id] = item\n        return item",
        "self.saved = persist_result\n        return item",
        "return real.upsert(item)",
    ],
)
def test_possible_persistence_effects_are_preserved(replacement: str) -> None:
    assert NoRecordingStore().check(P, _CONTRACT + _RECORD.replace("return item", replacement)) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "self.writes = []\n        self.writes = real",
        "if flag:\n            self.writes = []",
        "self.writes = []\n        register(self)",
        "return\n        self.writes = []",
    ],
)
def test_constructor_must_prove_a_stable_instance_list(replacement: str) -> None:
    source = _CONTRACT + _RECORD.replace("self.writes: list[object] = []", replacement)
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "self.writes = real\n        self.writes.append(item)",
        "if False:\n            self.writes.append(item)",
        "return item\n        self.writes.append(item)",
        "raise RuntimeError\n        self.writes.append(item)",
        "[self.writes.append(item) for item in ()]",
    ],
)
def test_recording_requires_reachable_straight_line_code(replacement: str) -> None:
    source = _CONTRACT + _RECORD.replace("self.writes.append(item)", replacement)
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "def upsert(other, item):",
        "@staticmethod\n    def upsert(self, item):",
        "@unknown\n    def upsert(self, item):",
    ],
)
def test_recording_requires_an_ordinary_instance_receiver(replacement: str) -> None:
    assert NoRecordingStore().check(P, _CONTRACT + _RECORD.replace("def upsert(self, item):", replacement)) == []


def test_overwritten_recording_override_is_not_the_implementation() -> None:
    source = _CONTRACT + _RECORD + "    def upsert(self, item):\n        return real.upsert(item)\n"
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize("base", ["Store, External", "Store, metaclass=Custom"])
def test_unsupported_class_ownership_abstains(base: str) -> None:
    assert NoRecordingStore().check(P, _CONTRACT + _RECORD.replace("Recorder(Store)", f"Recorder({base})")) == []


@pytest.mark.parametrize(
    ("provider", "name"),
    [
        ("from typing import NewType\nItem = NewType('Item', str)\n", "Item"),
        ("from dataclasses import dataclass\n@dataclass\nclass Item:\n    id: str\n", "Item"),
    ],
)
def test_shadowed_value_constructors_retain_possible_persistence(provider: str, name: str) -> None:
    source = (
        provider
        + _CONTRACT
        + _RECORD.replace("def upsert(self, item):", f"def upsert(self, item, {name}=persist):").replace(
            "return item", f"return {name}(item)"
        )
    )
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize(
    "provider",
    [
        "from typing import NewType\nItem = NewType('Item', str)\n",
        "from dataclasses import dataclass\n@dataclass\nclass Item:\n    id: str\n",
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    id: str\n",
    ],
)
@pytest.mark.parametrize("mutation", ["register(Item)\n", "Alias = Item\nAlias.__new__ = persist\n"])
def test_escaped_value_constructor_providers_abstain(provider: str, mutation: str) -> None:
    source = provider + mutation + _CONTRACT + _RECORD.replace("return item", "return Item(item)")
    assert NoRecordingStore().check(P, source) == []


@pytest.mark.parametrize(
    "body",
    [
        "    def __init__(self, item):\n        persist(item)\n",
        "    def model_post_init(self, context):\n        persist(self)\n",
        "    receipt: str = Field(default_factory=persist)\n",
    ],
)
def test_custom_model_construction_retains_possible_persistence(body: str) -> None:
    source = "from pydantic import BaseModel, Field\nclass Item(BaseModel):\n" + body
    source += _CONTRACT + _RECORD.replace("return item", "return Item(item)")
    assert NoRecordingStore().check(P, source) == []


def test_inherited_model_constructor_retains_possible_persistence() -> None:
    source = (
        """from pydantic import BaseModel
class Parent(BaseModel):
    def __init__(self, item):
        persist(item)
class Item(Parent):
    id: str
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(item)")
    )
    assert NoRecordingStore().check(P, source) == []


def test_plain_inherited_model_value_construction_is_preserved() -> None:
    source = (
        """from pydantic import BaseModel
class Parent(BaseModel):
    id: str
class Item(Parent):
    name: str
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(id=str(item), name=str(item))")
    )
    assert len(NoRecordingStore().check(P, source)) == 1


@pytest.mark.parametrize(
    "provider",
    [
        "import dataclasses\ndataclasses.dataclass = custom\n@dataclasses.dataclass\nclass Item:\n    id: str\n",
        "import pydantic\npydantic.BaseModel = Custom\nclass Item(pydantic.BaseModel):\n    id: str\n",
    ],
)
def test_mutated_native_class_provider_retains_unknown_construction(provider: str) -> None:
    source = provider + _CONTRACT + _RECORD.replace("return item", "return Item(item)")
    assert NoRecordingStore().check(P, source) == []


def test_local_import_cannot_reuse_a_module_value_constructor_proof() -> None:
    source = (
        """from typing import NewType
Item = NewType('Item', str)
"""
        + _CONTRACT
        + _RECORD.replace(
            "self.writes.append(item)", "from external import Item\n        self.writes.append(item)"
        ).replace("return item", "return Item(item)")
    )
    assert NoRecordingStore().check(P, source) == []


def test_value_constructor_escaping_through_a_container_abstains() -> None:
    source = (
        """from dataclasses import dataclass
@dataclass
class Item:
    id: str
providers = [Item]
register(providers)
"""
        + _CONTRACT
        + _RECORD.replace("return item", "return Item(item)")
    )
    assert NoRecordingStore().check(P, source) == []
