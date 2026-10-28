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
