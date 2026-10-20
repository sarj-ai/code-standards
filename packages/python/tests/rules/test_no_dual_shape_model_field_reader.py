from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_dual_shape_model_field_reader import NoDualShapeModelFieldReader


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_MODEL = "from pydantic import BaseModel\nclass Route(BaseModel):\n    destination: str\n    is_default: bool = False\n"
_READER = """
def _field(route: object, name: str) -> object:
    if isinstance(route, Route):
        return getattr(route, name)
    if isinstance(route, dict):
        return route.get(name)
    return None
"""
_CALL = "\ndef use(raw: object):\n    return _field(raw, 'destination')\n"


def _check(source: str, path: str = "app/routes.py"):
    return NoDualShapeModelFieldReader().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    NoDualShapeModelFieldReader.public_examples(),
    ids=[example.example_id for example in NoDualShapeModelFieldReader.public_examples()],
)
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source)) == example.expected_count


def test_reports_model_mapping_reader_once_for_multiple_fixed_fields() -> None:
    source = _MODEL + _READER + _CALL + "\nvalue = _field({}, 'is_default')\n"

    findings = _check(source)

    assert len(findings) == 1
    assert findings[0].code == "SARJ522"
    assert findings[0].severity is Severity.WARNING
    assert "Route" in findings[0].message
    assert "model_validate" in findings[0].message


def test_casts_do_not_hide_the_reader() -> None:
    reader = _READER.replace("getattr(route, name)", 'cast("object", getattr(route, name))').replace(
        "route.get(name)", 'cast("dict[str, object]", route).get(name)'
    )
    source = "from typing import cast  # ruff: ignore[banned-api]\n" + _MODEL + reader + _CALL

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "reader",
    [
        _READER.replace("if isinstance(route, dict)", "elif isinstance(route, dict)"),
        _READER.replace("return route.get(name)", "return route[name]"),
        _READER.replace("getattr(route, name)", "getattr(route, name, None)"),
        _READER.replace("-> object", "-> 'object'"),
    ],
    ids=["elif-branches", "subscript-lookup", "optional-getattr", "quoted-return"],
)
def test_recognizes_equivalent_readers(reader: str) -> None:
    assert len(_check(_MODEL + reader + _CALL)) == 1


def test_model_import_alias_and_keyword_call_are_resolved() -> None:
    model = _MODEL.replace("from pydantic import BaseModel", "import pydantic as schema").replace(
        "Route(BaseModel)", "Route(schema.BaseModel)"
    )
    call = "\ndef use(raw: object):\n    return _field(name='destination', route=raw)\n"

    assert len(_check(model + _READER + call)) == 1


@pytest.mark.parametrize("annotation", ["ClassVar[str]", "'ClassVar[str]'", "Annotated[ClassVar[str], 'metadata']"])
def test_class_metadata_is_not_a_pydantic_input_field(annotation: str) -> None:
    model = "from typing import Annotated, ClassVar\n" + _MODEL.replace(
        "    destination: str", f"    destination: {annotation} = 'stable'"
    )

    assert _check(model + _READER + _CALL) == []


@pytest.mark.parametrize(
    "source",
    [
        _MODEL + _READER,
        _MODEL + _READER + "\ndef use(raw, name):\n    return _field(raw, name)\n",
        _MODEL + _READER + "\nread = _field\n" + _CALL,
        _MODEL + _READER.replace("-> object", "-> str | None") + _CALL,
        _MODEL + _READER.replace("return getattr(route, name)", "return route.destination") + _CALL,
        _MODEL + _READER.replace("if isinstance(route, dict):\n        return route.get(name)\n", "") + _CALL,
        "from vendor import Route\n" + _READER + _CALL,
        "class Route:\n    destination: str\n" + _READER + _CALL,
        _MODEL
        + _READER.replace("def _field(route: object, name: str)", "def _field(route: object, name: str, getattr)")
        + _CALL,
        _MODEL
        + _READER.replace("def _field(route: object, name: str)", "def _field(route: object, name: str, isinstance)")
        + _CALL,
        _MODEL
        + _READER.replace("    if isinstance(route, Route):", "    route = other\n    if isinstance(route, Route):")
        + _CALL,
        _MODEL + _READER + "\nRoute = other\n" + _CALL,
        _MODEL + _READER + "\n_field = other\n" + _CALL,
        _MODEL + _READER + "\ndef use(_field):\n    return _field({}, 'destination')\n",
        _MODEL + _READER + "\nvalue = _field({}, 'metadata')\n",
        "class object: pass\n" + _MODEL + _READER.replace("-> object", "-> 'object'") + _CALL,
        _MODEL.replace(
            "    destination: str", "    def __getattr__(self, key):\n        return key\n    destination: str"
        )
        + _READER
        + _CALL,
        _MODEL + _READER + _CALL + "\ndef dynamic(raw, key):\n    return _field(raw, key)\n",
        _MODEL + "\ndef normalize(raw: object) -> Route:\n    return Route.model_validate(raw)\n",
        "def opaque(value: object) -> object:\n    return value\n",
        "def lookup(values: dict[str, object], key: str) -> object:\n    return values.get(key)\n",
        "def reflect(value: object, name: str) -> object:\n    return getattr(value, name)\n",
        "broken !!!",
    ],
)
def test_preserves_raw_boundaries_generic_reflection_and_ambiguous_bindings(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["app/generated/routes.py", "vendor/routes.py"])
def test_generated_and_vendor_code_is_excluded(path: str) -> None:
    assert _check(_MODEL + _READER + _CALL, path) == []


def test_exact_local_warning_suppression_is_honored() -> None:
    reader = _READER.replace(
        "-> object:", "-> object:  # sarj-noqa: SARJ522 -- raw validation semantics are required here"
    )

    assert _check(_MODEL + reader + _CALL) == []


@pytest.mark.parametrize(
    ("parameters", "call"),
    [
        ("name: str, route: object", "_field('destination', raw)"),
        ("route: object, *, name: str", "_field(raw, name='destination')"),
        ("*, name: str, route: object", "_field(name='destination', route=raw)"),
        ("name: str, /, route: object", "_field('destination', route=raw)"),
    ],
)
def test_parameter_order_and_keyword_only_spelling_preserve_contract(parameters: str, call: str) -> None:
    reader = _READER.replace("route: object, name: str", parameters)
    caller = _CALL.replace("_field(raw, 'destination')", call)

    assert len(_check(_MODEL + reader + caller)) == 1


@pytest.mark.parametrize(
    "import_statement",
    [
        "from collections.abc import Mapping",
        "from collections.abc import MutableMapping as Mapping",
        "from typing import Mapping",
        "from typing import MutableMapping as Mapping",
    ],
)
def test_import_proven_standard_mapping_is_the_same_dual_shape_reader(import_statement: str) -> None:
    reader = _READER.replace("route, dict", "route, Mapping")

    assert len(_check(import_statement + "\n" + _MODEL + reader + _CALL)) == 1


@pytest.mark.parametrize(
    "caller",
    [
        "KEY = 'destination'\ndef use(raw):\n    return _field(raw, KEY)\n",
        "from typing import Final\nKEY: Final = 'destination'\ndef use(raw):\n    return _field(raw, KEY)\n",
        "def use(raw):\n    key = 'destination'\n    return _field(raw, key)\n",
        "KEY = 'destination'\ndef use(raw):\n    key = KEY\n    field = key\n    return _field(raw, field)\n",
    ],
)
def test_stable_literal_selector_aliases_remain_closed_fields(caller: str) -> None:
    assert len(_check(_MODEL + _READER + caller)) == 1


@pytest.mark.parametrize(
    "caller",
    [
        "KEY = 'destination'\nKEY = dynamic()\ndef use(raw):\n    return _field(raw, KEY)\n",
        "def use(raw, condition):\n    if condition:\n        key = 'destination'\n    return _field(raw, key)\n",
        "def use(raw):\n    result = _field(raw, key)\n    key = 'destination'\n    return result\n",
        "def use(raw):\n    key = key\n    return _field(raw, key)\n",
        "def use(raw, key):\n    return _field(raw, key)\n",
        "def use(raw):\n    return _field(raw, 'destination', name='destination')\n",
        "def use(raw):\n    return _field(raw, 'destination', unexpected=True)\n",
    ],
)
def test_selector_alias_proof_rejects_rebinding_nondominance_and_invalid_calls(caller: str) -> None:
    assert _check(_MODEL + _READER + caller) == []


def test_custom_mapping_guard_is_not_assumed_to_be_a_standard_mapping() -> None:
    source = "from vendor import Mapping\n" + _MODEL + _READER.replace("route, dict", "route, Mapping") + _CALL

    assert _check(source) == []
