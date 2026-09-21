from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_any_mapping_types import NoAnyMappingTypes


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/models.py") -> list[Diagnostic]:
    return NoAnyMappingTypes().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    NoAnyMappingTypes.public_examples(),
    ids=[example.example_id for example in NoAnyMappingTypes.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    "annotation",
    [
        "dict[str, Any]",
        "Mapping[str, Any]",
        "list[dict[str, list[Any]]]",
        "dict[str, Any] | None",
        "'dict[str, Any]'",
    ],
)
def test_flags_any_mappings_in_all_annotation_positions(annotation: str) -> None:
    source = f"from typing import Any, Mapping\nvalue: {annotation}\ndef use(arg: {annotation}) -> {annotation}: ...\n"

    assert len(_check(source, "tests/test_models.py")) == 3


@pytest.mark.parametrize(
    "source",
    [
        "value: JsonValue\n",
        "value: object\n",
        "value: dict[str, object]\n",
        "from collections.abc import Mapping\nvalue: Mapping[str, object]\n",
        "def use(value: Payload) -> Result: ...\n",
        "class object: ...\nvalue: object\n",
        "from vendor import Any\nvalue: dict[str, Any]\n",
    ],
)
def test_allows_named_precise_opaque_or_unproven_types(source: str) -> None:
    assert _check(source) == []


def test_exact_suppression_is_honored() -> None:
    assert _check("from typing import Any\nvalue: dict[str, Any]  # sarj-noqa: SARJ447 — raw boundary\n") == []


@pytest.mark.parametrize("path", ["generated/client.py", "vendor/client.py", "third_party/client.py"])
def test_skips_generated_and_vendor_sources(path: str) -> None:
    assert _check("from typing import Any\nvalue: dict[str, Any]\n", path) == []


def test_flags_explicit_alias_chains_but_not_plain_assignments() -> None:
    source = """
from typing import Any, TypeAlias
Leaf: TypeAlias = list[Any]
Payload: TypeAlias = Leaf | None
value: dict[str, Payload]
Plain = Any
other: dict[str, Plain]
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any, cast\nvalue = cast(dict[str, Any], raw)\n",
        "from typing import Any\nfrom pydantic import TypeAdapter\nadapter = TypeAdapter(dict[str, Any])\n",
        "from typing import Any\nvalue = None  # type: dict[str, Any]\n",
    ],
)
def test_flags_runtime_and_legacy_type_expressions(source: str) -> None:
    assert len(_check(source)) == 1


def test_import_provenance_and_shadowing_avoid_false_positives() -> None:
    source = """
from vendor import Any, Mapping
class dict: ...
a: Mapping[str, Any]
b: dict[str, Any]
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\ndef use():\n    dict = CustomMap\n    value: dict[str, Any]\n",
        ("from typing import Any, cast\ndef use():\n    cast = custom_cast\n    return cast(dict[str, Any], value)\n"),
    ],
)
def test_local_shadowing_makes_type_provenance_ambiguous(source: str) -> None:
    assert _check(source) == []
