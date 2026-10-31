from pathlib import Path

import pytest

from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import PreferNamedtupleOverTupleReturn
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes


@pytest.mark.parametrize(
    ("base", "nominal_lines"),
    [("object", [3, 5]), ("Root", []), ("External", []), ("Base[int]", []), ("factory()", []), ("Left, Right", [])],
)
def test_explicit_bases_preserve_each_rules_inheritance_policy(base: str, nominal_lines: list[int]) -> None:
    source = (
        "class Root: pass\n"
        f"class Adapter({base}):\n"
        "    source_id: str\n    destination_id: str\n"
        "    def route(self, source_id: str, destination_id: str) -> str: ...\n"
        "    def coordinates(self) -> tuple[int, int]: ...\n"
    )
    path = Path("app/service.py")
    assert [finding.line for finding in PreferNominalIdTypes().check(path, source)] == nominal_lines
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
