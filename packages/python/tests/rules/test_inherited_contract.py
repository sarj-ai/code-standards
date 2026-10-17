from pathlib import Path

import pytest

from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import PreferNamedtupleOverTupleReturn
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes


@pytest.mark.parametrize("base", ["object", "Root", "External", "Base[int]", "factory()", "Left, Right"])
def test_explicit_inheritance_preserves_method_contracts(base: str) -> None:
    source = (
        "class Root: pass\n"
        f"class Adapter({base}):\n"
        "    source_id: str\n    destination_id: str\n"
        "    def route(self, source_id: str, destination_id: str) -> str: ...\n"
        "    def coordinates(self) -> tuple[int, int]: ...\n"
    )
    path = Path("app/service.py")
    assert PreferNominalIdTypes().check(path, source) == []
    assert PreferNamedtupleOverTupleReturn().check(path, source) == []


def test_plain_owned_class_and_module_functions_remain_eligible() -> None:
    source = (
        "class Owned:\n"
        "    def route(self, source_id: str, destination_id: str) -> str: ...\n"
        "    def coordinates(self) -> tuple[int, int]: ...\n"
        "def route(source_id: str, destination_id: str) -> str: ...\n"
        "def coordinates() -> tuple[int, int]: ...\n"
    )
    path = Path("app/service.py")
    assert len(PreferNominalIdTypes().check(path, source)) == 2
    assert len(PreferNamedtupleOverTupleReturn().check(path, source)) == 2
