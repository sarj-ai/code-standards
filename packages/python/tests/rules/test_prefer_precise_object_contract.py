from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules.prefer_precise_object_contract import PreferPreciseObjectContract


if TYPE_CHECKING:
    import ast


_IMPORTS = "from typing import Annotated, Literal, override\nfrom collections.abc import Callable\n"
_ANNOTATIONS = (
    ("bare", "object", 1),
    ("optional", "object | None", 1),
    ("collection", "list[object]", 1),
    ("mapping", "dict[str, object]", 1),
    ("callable", "Callable[[str], object]", 1),
    ("annotated", "Annotated[object, 'raw']", 1),
    ("metadata", "Annotated[str, object()]", 0),
    ("literal", "Literal['object']", 0),
    ("precise", "str | int", 0),
    ("quoted", "'object'", 1),
)
_OWNERS = (
    ("parameter", "def consume(value: {annotation}): ...\n", 1),
    ("return", "def consume() -> {annotation}: ...\n", 1),
    ("field", "class Contract:\n    value: {annotation}\n", 1),
    ("local", "def consume():\n    value: {annotation} = opaque\n", 0),
    ("override", "class Adapter(Base):\n    @override\n    def consume(self, value: {annotation}): ...\n", 0),
)


@pytest.fixture
def rule() -> PreferPreciseObjectContract:
    return PreferPreciseObjectContract()


def test_documented_examples() -> None:
    verify_native_rule(PreferPreciseObjectContract, analyze)


@pytest.mark.parametrize(("kind", "annotation", "opaque"), _ANNOTATIONS, ids=[case[0] for case in _ANNOTATIONS])
@pytest.mark.parametrize(("owner", "template", "checked"), _OWNERS, ids=[case[0] for case in _OWNERS])
def test_object_contract_boundaries(
    *,
    rule: PreferPreciseObjectContract,
    kind: str,
    annotation: str,
    opaque: int,
    owner: str,
    template: str,
    checked: int,
) -> None:
    assert (
        len(rule.check(Path("app/contract.py"), _IMPORTS + template.format(annotation=annotation))) == opaque * checked
    ), (kind, owner)


@pytest.mark.parametrize(
    "source",
    [
        "sentinel = object()\n",
        "class object: pass\ndef consume(value: object): ...\n",
        "def consume[object](value: object): ...\n",
        "class Container[object]:\n    value: object\n",
        "class Adapter:\n    def __eq__(self, other: object) -> bool: ...\n",
        "from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    @model_validator(mode='before')\n    @classmethod\n    def parse(cls, value: object) -> object:\n        return value\n",
        "from pydantic import BaseModel\nclass Model(BaseModel):\n    value: int\ndef parse(raw: object) -> Model:\n    return Model.model_validate(raw)\n",
    ],
)
def test_retains_opaque_runtime_and_framework_boundaries(rule: PreferPreciseObjectContract, source: str) -> None:
    assert rule.check(Path("app/contract.py"), source) == []


def test_loader_default_does_not_hide_object_contract(rule: PreferPreciseObjectContract) -> None:
    source = "import importlib\nfrom collections.abc import Callable\ndef call(import_module: Callable[[str], object] = importlib.import_module): ...\n"
    assert len(rule.check(Path("app/contract.py"), source)) == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("type Recursive = list[Recursive | object]\ndef parse(value: Recursive): ...\n", 1),
        ("type Recursive = list[Recursive]\ndef parse(value: Recursive): ...\n", 0),
        ("type Alias = object\ndef parse[Alias](value: Alias): ...\n", 0),
        ("type Alias = object\ndef parse(value: Alias): ...\n", 1),
        ("type Alias = object\ndef outer():\n    class Alias: pass\n    def consume(value: Alias): ...\n", 0),
        ("type Alias = object\ndef consume[object](value: Alias): ...\n", 1),
    ],
)
def test_recursive_and_shadowed_aliases(rule: PreferPreciseObjectContract, source: str, expected: int) -> None:
    assert len(rule.check(Path("app/contract.py"), source)) == expected


def test_branching_recursive_alias_does_not_repeat_its_subtree(
    rule: PreferPreciseObjectContract, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original = AnnotationSemantics.parse

    def measured(annotation: ast.expr | None) -> ast.expr | None:
        nonlocal calls
        calls += 1
        assert calls < 128, "Recursive alias traversal exceeds a bounded parse budget"
        return original(annotation)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- interception counts shared parser calls; injection would bypass the traversal under test.
        AnnotationSemantics, "parse", staticmethod(measured)
    )
    source = "sentinel = object()\ntype Node = str | tuple[Node, Node]\ndef consume(value: Node) -> None: ...\n"
    assert rule.check(Path("app/contract.py"), source) == []


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("from typing import final", 0),
        ("from typing_extensions import final", 0),
        ("from custom import final", 1),
    ],
)
def test_final_model_retains_raw_validation_boundary(
    rule: PreferPreciseObjectContract, provider: str, expected: int
) -> None:
    source = f"{provider}\nfrom pydantic import BaseModel\n@final\nclass Payload(BaseModel):\n    value: int\ndef parse(raw: object) -> Payload:\n    return Payload.model_validate(raw)\n"
    assert len(rule.check(Path("app/contract.py"), source)) == expected


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("Payload.model_validate(raw)", 0),
        ("Payload.model_validate(obj=raw)", 0),
        ("Payload.model_validate(obj=raw, strict=True)", 0),
        ("Payload.model_validate_json(raw)", 1),
        ("Payload.model_validate_json(json_data=raw)", 1),
        ("Payload.model_validate(*args, obj=raw)", 1),
        ("Payload.model_validate(obj=raw, **options)", 1),
        ("Payload.model_validate(other, obj=raw)", 1),
    ],
)
def test_raw_validation_requires_a_proven_object_argument(
    rule: PreferPreciseObjectContract, call: str, expected: int
) -> None:
    source = (
        "from pydantic import BaseModel\nclass Payload(BaseModel):\n    id: int\n"
        f"def parse(raw: object, args, options, other) -> Payload:\n    return {call}\n"
    )
    assert len(rule.check(Path("app/contract.py"), source)) == expected


@pytest.mark.parametrize(
    "header",
    ["@override\ndef consume(value: object): ...", "def __eq__(value: object): ..."],
)
def test_module_functions_do_not_inherit_framework_contracts(rule: PreferPreciseObjectContract, header: str) -> None:
    assert len(rule.check(Path("app/contract.py"), _IMPORTS + header)) == 1


def test_unrelated_local_object_name_does_not_hide_a_public_contract(rule: PreferPreciseObjectContract) -> None:
    source = "def unrelated(object): ...\ndef consume(value: object): ...\n"
    assert len(rule.check(Path("app/contract.py"), source)) == 1


def test_unrelated_local_wrapper_name_does_not_change_annotation_metadata(rule: PreferPreciseObjectContract) -> None:
    source = (
        "from typing import Annotated\ndef unrelated(Annotated): ...\ndef consume(value: Annotated[str, object]): ...\n"
    )
    assert rule.check(Path("app/contract.py"), source) == []


def test_acyclic_alias_graph_is_visited_once_per_depth(
    rule: PreferPreciseObjectContract, monkeypatch: pytest.MonkeyPatch
) -> None:
    visits = 0
    original = AnnotationSemantics.parse

    def measured(annotation: ast.expr | None) -> ast.expr | None:
        nonlocal visits
        visits += 1
        assert visits < 128, "Shared alias definitions must not expand exponentially"
        return original(annotation)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count the real shared parser calls to bound alias expansion.
        AnnotationSemantics, "parse", staticmethod(measured)
    )
    source = "sentinel = object()\ntype A0 = str\n"
    source += "".join(f"type A{index} = tuple[A{index - 1}, A{index - 1}]\n" for index in range(1, 13))
    source += "def consume(value: A12): ...\n"
    assert rule.check(Path("app/contract.py"), source) == []
