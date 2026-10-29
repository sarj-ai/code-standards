from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard
from sarj_python_lint.rules.no_shallow_record_type_guard import NoShallowRecordTypeGuard
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


_ITERABLE_MODEL = (
    "from collections.abc import Iterable\nfrom pydantic import BaseModel\nclass Entry(BaseModel):\n    kid: str\n"
)
_ITERATED_VALIDATION = "def parse(values: Iterable[object]) -> None:\n    for item in values:\n        Entry.model_validate(item, from_attributes=True)\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(_ITERABLE_MODEL + _ITERATED_VALIDATION, 0, id="validated-elements"),
        pytest.param(
            _ITERABLE_MODEL.replace("from collections.abc import Iterable", "from typing import Iterable as Items")
            + _ITERATED_VALIDATION.replace("Iterable[object]", "Items[object]"),
            0,
            id="typing-import-alias",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + "type Items = Iterable[object]\n"
            + _ITERATED_VALIDATION.replace("Iterable[object]", "Items"),
            0,
            id="source-type-alias",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION.replace("model_validate(item,", "model_validate(obj=item,"),
            0,
            id="keyword-raw-input",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + "from pydantic import ValidationError\n"
            + "def parse(values: Iterable[object]) -> tuple[Entry, ...]:\n    entries: list[Entry] = []\n    for item in values:\n        try:\n            entry = Entry.model_validate(item, from_attributes=True)\n        except ValidationError:\n            continue\n        entries.append(entry)\n    return tuple(entries)\n",
            0,
            id="skip-malformed-attribute-backed-elements",
        ),
        pytest.param(
            _ITERABLE_MODEL + "def parse(values: Iterable[object]) -> None:\n    return\n",
            1,
            id="unused-input-is-not-validation",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + _ITERATED_VALIDATION.replace("        Entry", "        item.domain_only()\n        Entry"),
            1,
            id="unvalidated-domain-read-before-validation",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "        item.domain_only()\n",
            1,
            id="raw-element-still-not-a-domain-model",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + "def parse(values: Iterable[object]) -> object:\n    for item in values:\n        return item\n    return None\n",
            2,
            id="unvalidated-element-escapes",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION.replace("Entry.model_validate", "Unknown.model_validate"),
            1,
            id="unknown-model-provider",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + _ITERATED_VALIDATION.replace("        Entry", "        item = replacement\n        Entry"),
            1,
            id="rebound-element-does-not-validate-input",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + "def parse(values: Iterable[object]) -> None:\n    for item in values:\n        callbacks.append(lambda: Entry.model_validate(item))\n",
            1,
            id="deferred-element-escape",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "        callbacks.append(lambda: item.domain_only())\n",
            1,
            id="validated-element-also-escapes-through-lambda",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "    callbacks.append(lambda: values)\n",
            1,
            id="validated-iterator-also-escapes-through-lambda",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "        streams.append(item for _ in range(1))\n",
            1,
            id="validated-element-also-escapes-through-generator",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "    streams.append(values for _ in range(1))\n",
            1,
            id="validated-iterator-also-escapes-through-generator",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "    consume(item)\n",
            1,
            id="last-raw-element-escapes-after-loop",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "    values.domain_only()\n",
            1,
            id="unrelated-iterator-use",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + "def parse(values: Iterable[object]) -> None:\n    def later():\n        for item in values:\n            Entry.model_validate(item)\n    callbacks.append(later)\n",
            1,
            id="deferred-iterator-escape",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION.replace("        Entry", "        if False:\n            Entry"),
            1,
            id="unreachable-validation",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + _ITERATED_VALIDATION.replace("values: Iterable[object]", "values: Iterable[object], other: object"),
            1,
            id="unrelated-object-contract-remains",
        ),
        pytest.param(
            _ITERABLE_MODEL + _ITERATED_VALIDATION + "    for item in values:\n        consume(item)\n",
            1,
            id="every-input-use-needs-validation",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + _ITERATED_VALIDATION.replace("model_validate(item, from_attributes=True)", "model_validate_json(item)"),
            1,
            id="json-parser-needs-text-input",
        ),
        pytest.param(
            _ITERABLE_MODEL
            + _ITERATED_VALIDATION.replace(
                "model_validate(item, from_attributes=True)", "model_validate(*items, obj=item)"
            ),
            1,
            id="ambiguous-validation-arguments",
        ),
        pytest.param(
            _ITERABLE_MODEL.replace("import Iterable", "import Sequence")
            + _ITERATED_VALIDATION.replace("Iterable[object]", "Sequence[object]"),
            1,
            id="no-general-collection-exception",
        ),
        pytest.param(
            _ITERABLE_MODEL + "class Iterable[T]: pass\n" + _ITERATED_VALIDATION,
            1,
            id="shadowed-iterable-provider",
        ),
    ],
)
def test_source_proven_iterable_model_validation(rule: PreferPreciseObjectContract, source: str, expected: int) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        pytest.param(
            "from typing import NoReturn\ndef halt(message: str) -> NoReturn:\n    raise SystemExit(message)\n",
            0,
            id="real-nonreturning-helper",
        ),
        pytest.param("def halt(message):\n    raise ValueError(message)\n", 0, id="body-proof-without-annotation"),
        pytest.param(
            "from typing import NoReturn\ndef halt(message: str) -> NoReturn:\n    return None\n",
            1,
            id="annotation-does-not-prove-rejection",
        ),
        pytest.param(
            "def halt(message):\n    if message:\n        return None\n    raise ValueError(message)\n",
            1,
            id="early-return-path",
        ),
        pytest.param("async def halt(message):\n    raise ValueError(message)\n", 1, id="unawaited-async-helper"),
        pytest.param("@decorate\ndef halt(message):\n    raise ValueError(message)\n", 1, id="decorated-helper"),
        pytest.param(
            "def halt(message):\n    yield message\n    raise ValueError(message)\n", 1, id="generator-is-not-rejection"
        ),
        pytest.param(
            "def halt(message):\n    raise ValueError(message)\nhalt = replacement\n", 1, id="provider-rebound"
        ),
        pytest.param(
            "def halt(message):\n    try:\n        raise ValueError(message)\n    finally:\n        return None\n",
            1,
            id="finally-suppresses-raise",
        ),
        pytest.param(
            "def halt(message):\n    def local():\n        return message\n    raise ValueError(message)\n",
            0,
            id="nested-return-is-not-helper-return",
        ),
    ],
)
def test_rejecting_helper_requires_stable_source_and_no_return_path(
    tmp_path: Path, rule: PreferPreciseObjectContract, provider: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.14'\n")
    (tmp_path / "support.py").write_text(provider)
    source = "from support import halt\ndef parse(value: object) -> str:\n    if not isinstance(value, str):\n        halt('not text')\n    return value\n"
    path = tmp_path / "app.py"
    path.write_text(source)
    assert len(rule.check(path, source)) == expected


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


def test_object_contract_blocks_until_fixed_or_exactly_suppressed(tmp_path: Path) -> None:
    path = tmp_path / "contracts.py"
    source = "def consume(value: object) -> None:\n    ...\n"
    path.write_text(source)
    findings = PreferPreciseObjectContract().check(path, source)
    assert [finding.severity for finding in findings] == [Severity.ERROR]
    assert main(["check", "--rule", PreferPreciseObjectContract.id, str(path)]) == 1
    path.write_text(source.replace("value: object", "value: str"))
    assert main(["check", "--rule", PreferPreciseObjectContract.id, str(path)]) == 0
    path.write_text(source.replace(" -> None:", " -> None:  # sarj-noqa: SARJ528 -- opaque extension protocol"))
    assert main(["check", "--rule", PreferPreciseObjectContract.id, str(path)]) == 0


@pytest.mark.parametrize("guard", ["TypeGuard", "TypeIs"])
@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
@pytest.mark.parametrize(
    ("imports", "target", "checked"),
    [
        ("", "dict[object, object]", "dict"),
        ("", "list[object]", "list"),
        ("", "set[object]", "set"),
        ("", "frozenset[object]", "frozenset"),
        ("", "tuple[object, ...]", "tuple"),
        ("from collections.abc import Mapping\n", "Mapping[object, object]", "Mapping"),
        ("", "dict['object', 'object']", "dict"),
    ],
)
def test_shallow_refinement_contracts_agree_with_container_and_record_rules(
    guard: str, module: str, imports: str, target: str, checked: str
) -> None:
    source = (
        f"from {module} import {guard}\n{imports}"
        f"def identifies(value: object) -> {guard}[{target}]:\n"
        f"    return isinstance(value, {checked})\n"
    )

    assert (
        check_source(
            [NoShallowContainerTypeGuard(), NoShallowRecordTypeGuard(), PreferPreciseObjectContract()],
            Path("app/guards.py"),
            source,
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TypeGuard\ndef identifies(value: object, context: object) -> TypeGuard[str]:\n    return isinstance(value, str)\n",
        "from typing import TypeIs\ndef identifies(value: object, *, context: object) -> TypeIs[str]:\n    return isinstance(value, str)\n",
        "from typing import TypeGuard\nclass Guard:\n    def identifies(self, value: object, context: object) -> TypeGuard[str]:\n        return isinstance(value, str)\n",
        "from typing import TypeIs\nclass Guard:\n    @staticmethod\n    def identifies(value: object, context: object) -> TypeIs[str]:\n        return isinstance(value, str)\n",
        "from typing import TypeGuard\nclass Guard:\n    @classmethod\n    def identifies(cls, value: object, context: object) -> TypeGuard[str]:\n        return isinstance(value, str)\n",
    ],
)
def test_only_guarded_object_input_is_exempt(rule: PreferPreciseObjectContract, source: str) -> None:
    [finding] = rule.check(Path("app/guards.py"), source)
    line = source.splitlines()[finding.line - 1]
    assert line[finding.col - 1 :].startswith("object)") or line[finding.col - 1 :].startswith("object,")
    assert "context: " in line[: finding.col - 1]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("from typing import TypeGuard", "from custom import TypeGuard", 1),
        ("value: object", "value: list[object]", 0),
        ("dict[object, object]", "dict[str, object]", 0),
        ("isinstance(value, dict)", "isinstance(other, dict)", 0),
        ("isinstance(value, dict)", "isinstance(value, list)", 0),
        ("isinstance(value, dict)", "bool(value)", 0),
        ("isinstance(value, dict)", "isinstance(value, dict) and bool(value)", 0),
        ("dict[object, object]", "tuple[object]", 0),
        ("    return", "    value = other\n    return", 0),
        ("def identifies", "@unknown\ndef identifies", 0),
        ("def identifies", "def identifies", 0),
    ],
)
def test_refinement_slots_defer_guard_soundness_without_exempting_unknown_guard_symbols(
    rule: PreferPreciseObjectContract, old: str, new: str, expected: int
) -> None:
    source = "from typing import TypeGuard\ndef identifies(value: object) -> TypeGuard[dict[object, object]]:\n    return isinstance(value, dict)\n"
    assert len(rule.check(Path("app/guards.py"), source.replace(old, new))) == expected


@pytest.mark.parametrize(
    "header",
    [
        "from pydantic import RootModel",
        "from pydantic.root_model import RootModel",
        "from pydantic import RootModel as Root",
        "import pydantic",
    ],
)
@pytest.mark.parametrize("argument", ["raw", "obj=raw"])
def test_root_model_validation_retains_raw_input(rule: PreferPreciseObjectContract, header: str, argument: str) -> None:
    base = "Root" if " as Root" in header else "pydantic.RootModel" if header == "import pydantic" else "RootModel"
    source = (
        f"{header}\nfrom pydantic import JsonValue\n"
        f"class Payload({base}[JsonValue]):\n    pass\n"
        f"def parse(raw: object) -> JsonValue:\n    return Payload.model_validate({argument}).root\n"
    )
    assert rule.check(Path("app/parse.py"), source) == []


def test_unproven_root_model_keeps_object_diagnostic(rule: PreferPreciseObjectContract) -> None:
    source = (
        "from custom import RootModel\n"
        "class Payload(RootModel[str]):\n    pass\n"
        "def parse(raw: object) -> str:\n    return Payload.model_validate(raw).root\n"
    )
    assert len(rule.check(Path("app/parse.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def choose(kind: type[object]) -> None: ...\n",
        "from typing import Type\nclass Contract:\n    kind: Type[object]\n",
        "import builtins as b\ndef choose(kind: b.type[b.object]) -> None: ...\n",
        "def __getattr__(name: str) -> object:\n    raise AttributeError(name)\n",
        "from typing import TypeIs\ndef values(value: object) -> TypeIs[list[object] | tuple[object, ...]]:\n    return isinstance(value, list | tuple)\n",
    ],
)
def test_universal_runtime_and_refinement_contracts_keep_honest_unknown_values(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def choose(kind: type[object], payload: object) -> object: ...\n", 2),
        ("def choose(kind: type[list[object]]) -> None: ...\n", 1),
        ("from custom import type\ndef choose(kind: type[object]) -> None: ...\n", 1),
        ("class Proxy:\n    def __getattr__(self, name: str) -> object: ...\n", 1),
        ("def outer():\n    def __getattr__(name: str) -> object: ...\n", 1),
        ("def __getattr__(name: object) -> object: ...\n", 1),
        ("def __getattr__(name: str, *, context: object) -> object: ...\n", 2),
    ],
)
def test_runtime_contract_exemptions_do_not_cover_other_object_contracts(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


_GUARD = (
    "from typing import TypeGuard\n"
    "def is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n"
    "    return isinstance(value, dict) and all(isinstance(key, str) for key in value)\n"
)


@pytest.mark.parametrize(
    "source",
    [
        _GUARD
        + "def require(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\n",
        _GUARD
        + "def pick(value: object) -> object:\n    if not is_mapping(value):\n        return None\n    return value.get('item')\n",
        "def require(value: object) -> list[object]:\n    if not isinstance(value, list):\n        raise ValueError\n    return value\n",
        "def require(value: object) -> list[object]:\n    if not isinstance(value, list) or not value:\n        return []\n    return value\n",
        _GUARD
        + "def keys(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        return {}\n    return {key: item for key, item in value.items()}\n",
        _GUARD
        + "def keys(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    result: dict[str, object] = {}\n    for key, item in value.items():\n        result[key] = item\n    return result\n",
        "def text(value: object) -> bool:\n    return isinstance(value, str) and bool(value)\n",
        "def render(value: object) -> str:\n    return repr(value)\n",
        "def number(value: object) -> float | None:\n    match value:\n        case int() | float():\n            return float(value)\n        case _:\n            return None\n",
    ],
)
def test_source_proven_raw_validation_and_opaque_interop_boundaries(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            _GUARD
            + "def require(value: object, context: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\n",
            1,
        ),
        (
            _GUARD
            + "def require(value: object) -> object:\n    if not is_mapping(value):\n        raise ValueError\n    return factory()\n",
            1,
        ),
        (
            _GUARD
            + "def require(value: object) -> object:\n    if not is_mapping(value):\n        raise ValueError\n    return value\n",
            1,
        ),
        ("def factory(value: object) -> object:\n    return value\n", 2),
        ("def factory(value: object) -> object:\n    check(value)\n    return factory_result()\n", 2),
        (
            "def false_guard(value: object) -> bool:\n    return True\ndef require(value: object) -> dict[str, object]:\n    if not false_guard(value):\n        raise ValueError\n    return value\n",
            3,
        ),
    ],
)
def test_raw_boundary_proof_does_not_hide_independent_domain_erasure(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    "source",
    [
        "import json\ndef parse(text: str) -> object:\n    return json.loads(text)\n",
        "from json import loads as decode\ndef parse(text: str) -> object:\n    return decode(text)\n",
        "import tomllib\ndef parse(text: str) -> object:\n    return tomllib.loads(text)\n",
        "import json\ndef parse(text: str) -> object:\n    result: object = json.loads(text)\n    return result\n",
        "import json\ndef parse(decoder: json.JSONDecoder, text: str) -> object:\n    result: tuple[object, int] = decoder.raw_decode(text)\n    return result[0]\n",
        "import json\n_DECODER = json.JSONDecoder()\ndef parse(text: str) -> object:\n    result: tuple[object, int] = _DECODER.raw_decode(text)\n    return result[0]\n",
        "import ast\n_MISSING = object()\ndef parse(node: ast.expr) -> object:\n    try:\n        return ast.literal_eval(node)\n    except ValueError:\n        return _MISSING\n",
    ],
)
def test_import_proven_parser_and_decoder_outputs_keep_raw_runtime_contracts(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from custom import loads\ndef parse(text: str) -> object:\n    return loads(text)\n",
        "import json\njson = custom\ndef parse(text: str) -> object:\n    return json.loads(text)\n",
        "from custom import JSONDecoder\ndef parse(decoder: JSONDecoder, text: str) -> object:\n    return decoder.raw_decode(text)[0]\n",
        "import json\ndef parse(text: str) -> object:\n    payload = json.loads(text)\n    return Payload(payload)\n",
    ],
)
def test_unproven_parsers_and_domain_constructors_still_need_precise_outputs(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    ("guard_source", "expected"),
    [
        (_GUARD, 0),
        (_GUARD + "is_mapping = replacement\n", 2),
        (_GUARD + "def is_mapping(value):\n    return True\n", 2),
        (_GUARD.replace("from typing import TypeGuard", "from custom import TypeGuard"), 2),
        (
            _GUARD.replace("from typing import TypeGuard", "import typing\ntyping.TypeGuard = replacement").replace(
                " -> TypeGuard[", " -> typing.TypeGuard["
            ),
            2,
        ),
        (_GUARD.replace("def is_mapping", "def is_mapping[TypeGuard]"), 2),
        (_GUARD + "def unrelated(is_mapping):\n    return is_mapping\n", 0),
    ],
)
def test_imported_raw_guard_requires_its_actual_unrebound_typing_contract(
    tmp_path: Path, rule: PreferPreciseObjectContract, guard_source: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.14'\n")
    (tmp_path / "guards.py").write_text(guard_source)
    source = (
        "from guards import is_mapping as accepts\n"
        "def require(value: object) -> dict[str, object]:\n"
        "    if not accepts(value):\n        raise ValueError\n    return value\n"
    )
    path = tmp_path / "app.py"
    path.write_text(source)
    assert len(rule.check(path, source)) == expected


@pytest.mark.parametrize(
    "condition", ["type(value) is not str", "type(value) != str", "str is not type(value)", "not (type(value) is str)"]
)
def test_exact_builtin_type_rejection_is_a_raw_validation_boundary(
    rule: PreferPreciseObjectContract, condition: str
) -> None:
    source = f"def require(value: object) -> str:\n    if {condition}:\n        raise ValueError\n    return value\n"
    assert rule.check(Path("app/contracts.py"), source) == []


def test_imported_builtin_type_and_target_aliases_preserve_rejection_proof(rule: PreferPreciseObjectContract) -> None:
    source = "from builtins import type as runtime_type, str as Text\ndef require(value: object) -> str:\n    if runtime_type(value) is not Text:\n        raise ValueError\n    return value\n"
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from custom import type\ndef require(value: object) -> str:\n    if type(value) is not str:\n        raise ValueError\n    return value\n",
            1,
        ),
        ("def render(value: object) -> str:\n    value.domain_only()\n    return repr(value)\n", 1),
        ("def render(value: object) -> str:\n    arbitrary(value)\n    return repr(value)\n", 1),
        (
            "def require(value: object) -> list[object]:\n    value.domain_only()\n    if not isinstance(value, list):\n        raise ValueError\n    return value\n",
            2,
        ),
        (
            "def require(value: object, enabled: bool) -> list[object]:\n    if enabled:\n        if not isinstance(value, list):\n            raise ValueError\n    return value\n",
            2,
        ),
    ],
)
def test_raw_boundary_proof_cannot_be_borrowed_from_unrelated_or_late_operations(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    "source",
    [
        _GUARD
        + "def require(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    result = DomainFactory()\n    result['item'] = value.get('item')\n    return result\n",
        _GUARD
        + "def require(value: object) -> object:\n    if not is_mapping(value):\n        raise ValueError\n    result = DomainFactory()\n    result['item'] = value.get('item')\n    return result\n",
        _GUARD
        + "def require(value: object) -> object:\n    if not is_mapping(value):\n        raise ValueError\n    result = {}\n    result['item'] = value.get('item')\n    return result\n",
        _GUARD
        + "def require(value: object) -> object:\n    if not is_mapping(value):\n        raise ValueError\n    return {key: item for key, item in value.items()}\n",
        "def require(value: object) -> object:\n    if not isinstance(value, str):\n        raise ValueError\n    return value[0]\n",
        "from typing import TypeGuard\ndef texts(value: object) -> TypeGuard[dict[str, str]]:\n    return isinstance(value, dict) and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())\ndef require(value: object) -> object:\n    if not texts(value):\n        raise ValueError\n    return value.get('item')\n",
        "from typing import TypeGuard\ndef numbers(value: object) -> TypeGuard[list[int]]:\n    return isinstance(value, list) and all(isinstance(item, int) for item in value)\ndef require(value: object) -> object:\n    if not numbers(value):\n        raise ValueError\n    return value[0]\n",
        "from typing import TypeIs\ndef numbers(value: object) -> TypeIs[dict[object, int]]:\n    return isinstance(value, dict) and all(isinstance(item, int) for item in value.values())\ndef require(value: object) -> object:\n    if not numbers(value):\n        raise ValueError\n    return value.get('item')\n",
    ],
)
def test_raw_provenance_cannot_erase_known_domain_factories_or_precise_children(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    [finding] = rule.check(Path("app/contracts.py"), source)
    assert finding.severity is Severity.ERROR


@pytest.mark.parametrize("initializer", ["{}", "dict()"])
def test_only_a_proven_raw_container_can_carry_unknown_projected_values(
    rule: PreferPreciseObjectContract, initializer: str
) -> None:
    source = (
        _GUARD
        + f"def require(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    result = {initializer}\n    result['item'] = value.get('item')\n    return result\n"
    )
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from collections.abc import Mapping\ndef text(table: Mapping[str, object]) -> str:\n    value = table.get('name')\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n",
        "from collections.abc import Mapping\ndef text(table: Mapping[str, object]) -> str | None:\n    value = table.get('name')\n    return value if isinstance(value, str) else None\n",
        "from collections.abc import Mapping\ndef items(table: Mapping[str, object]) -> list[object]:\n    value = table['items']\n    if not isinstance(value, list):\n        raise ValueError\n    return value\n",
        _GUARD
        + "def table(raw: dict[str, object]) -> dict[str, object]:\n    value = raw.get('table')\n    if not is_mapping(value):\n        return {}\n    return value\n",
        _GUARD
        + "def table(value: object) -> dict[str, object] | bool:\n    if isinstance(value, bool):\n        return value\n    if is_mapping(value) and all(isinstance(key, str) for key in value):\n        return {key: item for key, item in value.items()}\n    raise ValueError\n",
        _GUARD
        + "def render(value: object) -> str:\n    return str(value.get('name')) if is_mapping(value) else 'missing'\n",
        _GUARD
        + "def table(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\ndef wrapper(value: object) -> dict[str, object]:\n    result = table(value)\n    return result\n",
        _GUARD
        + "def table(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\ndef wrapper(value: object) -> object:\n    return table(value).get('item')\n",
        _GUARD
        + "def table(label: str, value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError(label)\n    return value\ndef wrapper(value: object) -> dict[str, object]:\n    result = table('raw', value=value)\n    return result\n",
        "from pydantic import RootModel\nclass Model(RootModel[list[str]]): pass\ndef parse(value: object) -> list[str]:\n    return Model.model_validate(value).root\ndef wrapper(value: object) -> list[str]:\n    result = parse(value)\n    return result\n",
    ],
)
def test_raw_projection_acceptance_and_source_validator_delegation(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from collections.abc import Mapping\ndef text(table: Mapping[str, object], other: object) -> str:\n    value = table.get('name')\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n",
            1,
        ),
        (
            "def factory(table: dict[str, object]) -> object:\n    return Domain(table.get('name'))\n",
            2,
        ),
        (
            "def text(table: dict[str, object]) -> object:\n    value = table.get('name')\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n",
            1,
        ),
        (
            "def text(table: dict[str, object]) -> object:\n    value = table.get('name')\n    return value if isinstance(value, str) else None\n",
            1,
        ),
        (
            "def flag(table: dict[str, object]) -> object:\n    value = table.get('flag')\n    return value if isinstance(value, bool) else None\n",
            1,
        ),
        (
            "def text(table: dict[str, str]) -> object:\n    value = table.get('name')\n    return value if isinstance(value, str) else None\n",
            1,
        ),
        (
            "def number(values: list[int]) -> object:\n    value = values[0]\n    if not isinstance(value, int):\n        raise ValueError\n    return value\n",
            1,
        ),
        (
            "def pretend(value: object) -> bool:\n    return True\ndef wrapper(value: object) -> str:\n    pretend(value)\n    return 'constant'\n",
            2,
        ),
        (
            "def accepts_text(value: str) -> bool:\n    return isinstance(value, str)\ndef wrapper(value: object) -> bool:\n    return accepts_text(value)\n",
            1,
        ),
        (
            "def first(value: object) -> object:\n    return second(value)\ndef second(value: object) -> object:\n    return first(value)\n",
            4,
        ),
        (
            "def require(value: object) -> str:\n    alias = value\n    alias.domain_only()\n    if not isinstance(alias, str):\n        raise ValueError\n    return alias\n",
            1,
        ),
        (
            _GUARD
            + "def table(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\ndef wrapper(value: object) -> object:\n    return table(value)\n",
            1,
        ),
    ],
)
def test_raw_projection_and_delegation_do_not_erase_known_or_unrelated_domains(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (
            _GUARD
            + "def require(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\n",
            0,
        ),
        (
            _GUARD
            + "def require(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\nrequire = replacement\n",
            2,
        ),
        ("def require(value: object) -> dict[str, object]:\n    return Domain(value)\n", 2),
        ("def require(value: object) -> dict[str, object]:\n    return require(value)\n", 2),
    ],
)
def test_imported_validator_delegation_requires_stable_actual_source(
    tmp_path: Path, rule: PreferPreciseObjectContract, provider: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.14'\n")
    (tmp_path / "validators.py").write_text(provider)
    source = "from validators import require\ndef wrapper(value: object) -> dict[str, object]:\n    result = require(value)\n    return result\n"
    path = tmp_path / "app.py"
    path.write_text(source)
    assert len(rule.check(path, source)) == expected


@pytest.mark.parametrize(
    "expression",
    ["table(known())", "table(known()).get('name')", "table(DomainFactory()).get('name')"],
)
def test_delegated_result_requires_raw_actual_inputs(rule: PreferPreciseObjectContract, expression: str) -> None:
    source = (
        _GUARD
        + "def table(value: object) -> dict[str, object]:\n    if not is_mapping(value):\n        raise ValueError\n    return value\n"
        + "def known() -> dict[str, str]:\n    return {'name': 'known'}\n"
        + f"def erased() -> object:\n    return {expression}\n"
    )
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    ("arguments", "returned"), [("raw, {'known': 'text'}", "second"), ("{'known': 'text'}, raw", "first")]
)
def test_independent_raw_argument_cannot_lend_another_argument_opaque_provenance(
    rule: PreferPreciseObjectContract, arguments: str, returned: str
) -> None:
    source = f"def pick(first: object, second: object) -> dict[str, object]:\n    if not isinstance(first, dict):\n        raise ValueError\n    if not isinstance(second, dict):\n        raise ValueError\n    return {returned}\ndef erased(raw: object) -> dict[str, object]:\n    return pick({arguments})\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


def test_independent_native_parser_output_can_delegate_without_raw_input(rule: PreferPreciseObjectContract) -> None:
    source = "import json\ndef parse(text: str) -> object:\n    return json.loads(text)\ndef wrapper(text: str) -> object:\n    return parse(text)\n"
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("iterator", "target", "returned", "expected"),
    [
        ("values", "name", "name", 1),
        ("values.keys()", "name", "name", 1),
        ("values.items()", "name, value", "name", 1),
        ("values.items()", "name, value", "value", 0),
        ("values.values()", "value", "value", 0),
        ("values.items()", "pair", "pair[0]", 1),
        ("values.items()", "pair", "pair[1]", 0),
    ],
)
def test_mapping_iteration_preserves_known_keys_and_unknown_values(
    rule: PreferPreciseObjectContract, iterator: str, target: str, returned: str, expected: int
) -> None:
    source = f"def pick(values: dict[str, object]) -> object:\n    if not isinstance(values, dict):\n        raise ValueError\n    for {target} in {iterator}:\n        return {returned}\n    return None\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    ("iterator", "target", "returned"),
    [("values", "name", "name"), ("values.keys()", "name", "name"), ("values.items()", "name, item", "name")],
)
def test_refined_mapping_keys_keep_their_precise_guard_contract(
    rule: PreferPreciseObjectContract, iterator: str, target: str, returned: str
) -> None:
    source = (
        _GUARD
        + f"def pick(values: object) -> object:\n    if not is_mapping(values):\n        raise ValueError\n    for {target} in {iterator}:\n        return {returned}\n    return None\n"
    )
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize("call", ["str(value, 'utf8')", "type(value, (), {})"])
def test_builtin_decode_and_class_factory_inputs_are_not_universal(
    rule: PreferPreciseObjectContract, call: str
) -> None:
    source = f"def consume(value: object):\n    return {call}\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "require.__code__ = replacement.__code__\n",
        "globals()['require'] = replacement\n",
        "def install():\n    global require\n    require = replacement\ninstall()\n",
    ],
)
def test_mutated_local_validator_cannot_lend_its_previous_contract(
    rule: PreferPreciseObjectContract, mutation: str
) -> None:
    source = (
        "def require(value: object) -> str:\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
        + mutation
        + "def wrapper(value: object) -> str:\n    return require(value)\n"
    )
    assert any(finding.line == len(source.splitlines()) - 1 for finding in rule.check(Path("app/contracts.py"), source))


@pytest.mark.parametrize(
    "mutation",
    [
        "require.__code__ = replacement.__code__\n",
        "globals()['require'] = replacement\n",
        "def install():\n    global require\n    require = replacement\ninstall()\n",
        "from replacement import *\n",
    ],
)
def test_mutated_imported_validator_cannot_lend_its_previous_contract(
    tmp_path: Path, rule: PreferPreciseObjectContract, mutation: str
) -> None:
    provider = (
        "def require(value: object) -> str:\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
        + mutation
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.14'\n")
    (tmp_path / "validators.py").write_text(provider)
    source = "from validators import require\ndef wrapper(value: object) -> str:\n    return require(value)\n"
    path = tmp_path / "app.py"
    path.write_text(source)
    assert len(rule.check(path, source)) == 1


def test_long_acyclic_validator_chain_abstains_with_bounded_depth(rule: PreferPreciseObjectContract) -> None:
    count = 1_100
    source = (
        "".join(
            f"def helper_{index}(value: object) -> str:\n    return helper_{index + 1}(value)\n"
            for index in range(count)
        )
        + f"def helper_{count}(value: object) -> str:\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
    )
    assert rule.check(Path("app/contracts.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        "import ast\ndef raw(node: ast.Constant) -> object:\n    return node.value\n",
        "import ast\ndef raw(node: ast.expr) -> object:\n    if isinstance(node, ast.Constant):\n        return node.value\n    return None\n",
        "from ast import Constant\ndef raw(node: Constant) -> object:\n    return node.value\n",
        "import ast\ndef raw(node: ast.expr) -> object:\n    match node:\n        case ast.Constant(value=value):\n            return value\n        case _:\n            return None\n",
        "from typing import Protocol, runtime_checkable\n@runtime_checkable\nclass Probe(Protocol):\n    @property\n    def value(self) -> object: ...\n",
        "from typing import Protocol, runtime_checkable\nfrom collections.abc import Iterable\n@runtime_checkable\nclass Probe(Protocol):\n    @property\n    def values(self) -> Iterable[object]: ...\n",
        "from types import FunctionType\ndef invoke(function: FunctionType) -> object:\n    return function()\n",
        "from types import FunctionType\ndef invoke(function: FunctionType, value: object) -> object:\n    return function(value)\n",
        "from types import FunctionType\ndef invoke(function: FunctionType, value: object) -> object:\n    return function(payload=value)\n",
        "def same(left: object, right: object) -> bool:\n    return left is right\n",
        "import sys\ndef references(value: object) -> int:\n    return sys.getrefcount(value)\n",
        "def execute(source: str, value: object) -> object:\n    namespace = {'value': value}\n    exec(source, namespace)\n    return namespace['result']\n",
        "from collections.abc import Mapping\ndef execute(source: str, namespace: Mapping[str, object] | None) -> object:\n    scope = {} if namespace is None else dict(namespace)\n    exec(source, scope)\n    return scope['result']\n",
        "def evaluate(source: str, value: object) -> object:\n    namespace = {'value': value}\n    return eval(source, namespace)\n",
        "def execute(source: str, value: object) -> object:\n    namespace = {}\n    namespace['value'] = value\n    exec(source, globals=namespace)\n    return namespace['result']\n",
        "from collections.abc import Callable\ndef execute(source: str, callback: Callable[..., object]) -> object:\n    namespace = dict(callback=callback)\n    exec(source, namespace)\n    return namespace['result']\n",
        "def execute(source: str, value: object) -> object:\n    alias = value\n    namespace = {'value': alias}\n    exec(source, namespace)\n    return namespace['result']\n",
    ],
)
def test_source_proven_native_opaque_boundaries(rule: PreferPreciseObjectContract, source: str) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from custom import Constant\ndef raw(node: Constant) -> object:\n    return node.value\n", 1),
        ("import ast\nast.Constant = replacement\ndef raw(node: ast.Constant) -> object:\n    return node.value\n", 1),
        (
            "import ast\ndef raw(node: ast.expr) -> object:\n    match node:\n        case ast.Constant(value=str() as value):\n            return value\n        case _:\n            return None\n",
            1,
        ),
        ("from typing import Protocol\nclass Probe(Protocol):\n    @property\n    def value(self) -> object: ...\n", 1),
        (
            "from typing import Protocol, runtime_checkable\n@runtime_checkable\nclass Probe(Protocol):\n    def value(self) -> object: ...\n",
            1,
        ),
        ("class Model:\n    @property\n    def value(self) -> object: ...\n", 1),
        (
            "from typing import Protocol, runtime_checkable\n@runtime_checkable\nclass Probe(Protocol):\n    @property\n    def value(self) -> object:\n        return Domain()\n",
            1,
        ),
        ("from custom import FunctionType\ndef invoke(function: FunctionType) -> object:\n    return function()\n", 1),
        (
            "from collections.abc import Callable\ndef invoke(function: Callable[[], object]) -> object:\n    return function()\n",
            2,
        ),
        (
            "from custom import exec\ndef execute(source: str, value: object) -> object:\n    namespace = {'value': value}\n    exec(source, namespace)\n    return namespace['result']\n",
            2,
        ),
        (
            "def execute(source: str, value: object) -> object:\n    namespace = Domain(value)\n    exec(source, namespace)\n    return namespace['result']\n",
            2,
        ),
        (
            "def execute(source: str, value: object) -> object:\n    namespace = dict(value)\n    exec(source, namespace)\n    return namespace['result']\n",
            1,
        ),
        (
            "def execute(source: str, value: object) -> object:\n    alias = value\n    alias.domain_only()\n    namespace = {'value': alias}\n    exec(source, namespace)\n    return namespace['result']\n",
            1,
        ),
        (
            "def execute(source: str, value: object) -> object:\n    unrelated = {'value': value}\n    exec(source, {})\n    return unrelated['result']\n",
            2,
        ),
        (
            "globals()['exec'] = replacement\ndef execute(source: str, value: object) -> object:\n    namespace = {'value': value}\n    exec(source, namespace)\n    return namespace['result']\n",
            2,
        ),
        ("def consume(value: object) -> None:\n    pass\n", 1),
    ],
)
def test_native_opaque_proof_preserves_unrelated_or_erased_domain_contracts(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    "body",
    [
        "    if isinstance(node.value, str):\n        return node.value\n    return None\n",
        "    if not isinstance(node.value, str):\n        return None\n    return node.value\n",
    ],
)
def test_native_ast_values_do_not_erase_dominating_precise_narrowing(
    rule: PreferPreciseObjectContract, body: str
) -> None:
    source = "import ast\ndef raw(node: ast.Constant) -> object:\n" + body
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "    namespace = {'result': 'known'}\n    result = namespace['result']\n    exec(source, namespace)\n    return result\n",
        "    namespace = {}\n    exec(source, namespace)\n    namespace['result'] = Domain()\n    return namespace['result']\n",
        "    namespace = {}\n    exec(source, namespace)\n    namespace['result'] = 'known'\n    return namespace['result']\n",
        "    namespace = {}\n    exec(source, namespace); namespace['result'] = 'known'\n    return namespace['result']\n",
        "    namespace = {}\n    exec(source, namespace)\n    alias = namespace\n    alias['result'] = 'known'\n    return alias['result']\n",
        "    namespace = {}\n    exec(source, namespace)\n    namespace.update(result='known')\n    return namespace.get('result')\n",
        "    namespace = {'result': 'known'}\n    if enabled:\n        exec(source, namespace)\n    return namespace['result']\n",
    ],
)
def test_native_namespace_values_require_dominating_execution_without_authored_overwrite(
    rule: PreferPreciseObjectContract, body: str
) -> None:
    source = "def raw(source: str, enabled: bool = True) -> object:\n" + body
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "prefix",
    [
        "globals().update(exec=replacement)\n",
        "scope = globals()\nscope.update({'exec': replacement})\n",
        "globals().clear()\n",
    ],
)
def test_native_namespace_method_mutations_invalidate_builtin_ownership(
    rule: PreferPreciseObjectContract, prefix: str
) -> None:
    source = (
        prefix
        + "def execute(source: str, value: object) -> object:\n    namespace = {'value': value}\n    exec(source, namespace)\n    return namespace['result']\n"
    )
    assert len(rule.check(Path("app/contracts.py"), source)) == 2


def test_native_builtin_import_alias_cannot_survive_dynamic_rebinding(rule: PreferPreciseObjectContract) -> None:
    source = "from builtins import exec as execute\nglobals()['execute'] = replacement\ndef raw(source: str, value: object) -> object:\n    namespace = {'value': value}\n    execute(source, namespace)\n    return namespace['result']\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 2


def test_domain_equality_is_not_a_universal_identity_boundary(rule: PreferPreciseObjectContract) -> None:
    source = "def status(value: object) -> bool:\n    return value == State.READY\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "prefix",
    [
        "    if 'name' not in table:\n        return None\n",
        "    if set(table).difference({'name'}):\n        raise ValueError\n",
        "    if set(table.keys()).difference({'name'}):\n        raise ValueError\n",
    ],
)
def test_declared_raw_mapping_key_inspection_can_precede_value_validation(
    rule: PreferPreciseObjectContract, prefix: str
) -> None:
    source = (
        "from collections.abc import Mapping\ndef text(table: Mapping[str, object]) -> str | None:\n"
        + prefix
        + "    value = table['name']\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
    )
    assert rule.check(Path("app/contracts.py"), source) == []


def test_arbitrary_object_cannot_borrow_mapping_key_inspection(rule: PreferPreciseObjectContract) -> None:
    source = "def text(table: object) -> str | None:\n    if 'name' not in table:\n        return None\n    value = table['name']\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


def test_benign_builtins_import_cannot_hide_builtin_object_contract(rule: PreferPreciseObjectContract) -> None:
    source = "from builtins import sum\ndef erased() -> object:\n    return Domain()\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "prefix",
    [
        "import builtins\nbuiltins.object = Custom\n",
        "import builtins\nsetattr(builtins, 'object', Custom)\n",
        "globals()['object'] = Custom\n",
        "globals().update(object=Custom)\n",
    ],
)
def test_source_visible_builtin_object_mutation_preserves_custom_contract(
    rule: PreferPreciseObjectContract, prefix: str
) -> None:
    assert rule.check(Path("app/contracts.py"), prefix + "def keep(value: object): ...\n") == []


def test_native_namespace_alias_input_keeps_its_actual_execution_owner(rule: PreferPreciseObjectContract) -> None:
    source = "def execute(source: str, value: object) -> object:\n    namespace = {}\n    alias = namespace\n    alias['value'] = value\n    exec(source, namespace)\n    return alias['result']\n"
    assert rule.check(Path("app/contracts.py"), source) == []


def test_namespace_domain_escape_before_execution_cannot_lend_input_ownership(
    rule: PreferPreciseObjectContract,
) -> None:
    source = "def execute(source: str, value: object) -> object:\n    namespace = {'value': value}\n    domain(namespace)\n    exec(source, namespace)\n    return namespace['result']\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize("annotation", ["Mapping[str, object] | None", "Mapping[str, object] | bool"])
def test_raw_container_annotation_branch_retains_projected_input_contract(
    rule: PreferPreciseObjectContract, annotation: str
) -> None:
    source = f"from collections.abc import Mapping\ndef text(table: {annotation}) -> str | None:\n    if table is None or isinstance(table, bool):\n        return None\n    if set(table).difference({{'name'}}):\n        raise ValueError\n    value = table.get('name')\n    return value if isinstance(value, str) else None\n"
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("annotation", "body"),
    [
        ("dict[str, object] | str", "    if isinstance(value, str):\n        return value[0]\n    return None\n"),
        ("dict[str, object] | bool", "    if isinstance(value, bool):\n        return value\n    return None\n"),
        (
            "dict[str, object] | None",
            "    if value is None:\n        return None\n    for key in value:\n        return key\n    return None\n",
        ),
    ],
)
def test_raw_union_branch_does_not_launder_precise_scalar_or_mapping_key_outputs(
    rule: PreferPreciseObjectContract, annotation: str, body: str
) -> None:
    source = f"def pick(value: {annotation}) -> object:\n" + body
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


def test_mapping_key_only_consumer_keeps_uninspected_values_opaque(rule: PreferPreciseObjectContract) -> None:
    source = "from collections.abc import Mapping\ndef names(table: Mapping[str, object]) -> set[str]:\n    return set(table).difference({'internal'})\n"
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize("expression", ["table", "Domain(table)"])
def test_mapping_value_escape_cannot_borrow_key_only_input_ownership(
    rule: PreferPreciseObjectContract, expression: str
) -> None:
    source = f"from collections.abc import Mapping\ndef erase(table: Mapping[str, object]) -> object:\n    keys = set(table)\n    return {expression}\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 2


def test_projected_loop_value_is_checked_before_typed_consumption(rule: PreferPreciseObjectContract) -> None:
    source = "def texts(table: dict[str, object]) -> tuple[str, ...]:\n    result: list[str] = []\n    for key in ('first', 'second'):\n        if key not in table:\n            continue\n        value = table[key]\n        if not isinstance(value, str):\n            raise ValueError\n        result.append(value)\n    return tuple(result)\n"
    assert rule.check(Path("app/contracts.py"), source) == []


def test_conditional_projection_assignment_cannot_prove_an_outer_value_read(rule: PreferPreciseObjectContract) -> None:
    source = "def text(table: dict[str, object], enabled: bool) -> str:\n    if enabled:\n        value = table['name']\n    if not isinstance(value, str):\n        raise ValueError\n    return value\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


def test_identity_witness_cannot_lend_ownership_to_domain_equality(rule: PreferPreciseObjectContract) -> None:
    source = "def status(value: object) -> bool:\n    if value is None:\n        return False\n    return value == State.READY\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize("condition", ["is_list(value)", "isinstance(value, list)"])
def test_conditional_raw_list_projection_retains_empty_fallback(
    rule: PreferPreciseObjectContract, condition: str
) -> None:
    source = (
        "from typing import TypeIs\ndef is_list(value: object) -> TypeIs[list[object]]:\n    return isinstance(value, list)\n"
        f"def items(table: dict[str, object]) -> list[object]:\n    value = table.get('items')\n    return value if {condition} else []\n"
    )
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("result", "otherwise"),
    [("object", "[]"), ("list[object]", "Domain()"), ("list[object]", "known()")],
)
def test_conditional_raw_origin_does_not_erase_known_containers_or_domain_branch(
    rule: PreferPreciseObjectContract, result: str, otherwise: str
) -> None:
    source = (
        "class Domain: pass\ndef known() -> Domain:\n    return Domain()\n"
        f"def items(table: dict[str, object]) -> {result}:\n    value = table.get('items')\n    return value if isinstance(value, list) else {otherwise}\n"
    )
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    "wrapper",
    [
        "    try:\n{body}\n    except ValueError:\n        return None\n",
        "    try:\n        operation()\n    except ValueError:\n{body}\n    return None\n",
        "    try:\n        operation()\n    except ValueError:\n        return None\n    else:\n{body}\n",
        "    try:\n        operation()\n    finally:\n{body}\n",
        "    match enabled:\n        case True:\n{body}\n    return None\n",
    ],
)
def test_projected_alias_validation_preserves_exception_and_match_statement_suites(
    rule: PreferPreciseObjectContract, wrapper: str
) -> None:
    body = "        value = table.get('name')\n        if not isinstance(value, str):\n            return None\n        return value"
    if wrapper.startswith("    match"):
        body = "\n".join("    " + line for line in body.splitlines())
    source = "def text(table: dict[str, object], enabled: bool) -> str | None:\n" + wrapper.format(body=body)
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        _GUARD + "def require(value: object) -> dict[str, object]:\n    assert is_mapping(value)\n    return value\n",
        "def require(value: object) -> list[object]:\n    assert isinstance(value, list)\n    return value\n",
        "def require(value: object) -> list[object]:\n    assert isinstance(value, list)\n    return [item for item in value]\n",
        _GUARD + "def pick(value: object) -> object:\n    assert is_mapping(value)\n    return value.get('item')\n",
        "def text(value: object) -> str:\n    assert isinstance(value, str)\n    return value\n",
        _GUARD
        + "def require(value: object) -> dict[str, object]:\n    assert is_mapping(value)\n    return value\ndef wrapper(value: object) -> dict[str, object]:\n    return require(value)\n",
    ],
)
def test_canonical_assertion_retains_only_its_actual_raw_boundary(
    rule: PreferPreciseObjectContract, source: str
) -> None:
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            _GUARD
            + "def require(value: object, other: object) -> dict[str, object]:\n    assert is_mapping(value)\n    return value\n",
            1,
        ),
        ("def require(value: object) -> object:\n    assert isinstance(value, list)\n    return value\n", 1),
        ("def require(value: object) -> object:\n    assert isinstance(value, str)\n    return value\n", 1),
        ("def require(value: object) -> list[object]:\n    assert True\n    return value\n", 2),
        (
            "def accepts(value):\n    return True\ndef require(value: object) -> list[object]:\n    assert accepts(value)\n    return value\n",
            2,
        ),
        (
            "def require(value: object, enabled: bool) -> list[object]:\n    if enabled:\n        assert isinstance(value, list)\n    return value\n",
            2,
        ),
        (
            "def require(value: object) -> list[object]:\n    if False:\n        assert isinstance(value, list)\n    return value\n",
            2,
        ),
        (
            "def require(value: object) -> list[object]:\n    value.domain_only()\n    assert isinstance(value, list)\n    return value\n",
            2,
        ),
    ],
)
def test_assertion_ownership_does_not_erase_precise_or_unrelated_contracts(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


def test_assertion_validator_delegation_keeps_all_raw_formals_correlated(rule: PreferPreciseObjectContract) -> None:
    source = "def pick(first: object, second: object) -> dict[str, object]:\n    assert isinstance(first, dict)\n    assert isinstance(second, dict)\n    return second\ndef erased(raw: object) -> dict[str, object]:\n    return pick(raw, {'known': 'text'})\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(value: object) -> str:\n    return 'known'\n    assert isinstance(value, list)\n", 1),
        (
            "def f(value: object) -> str:\n    if False:\n        assert isinstance(value, list)\n    return 'known'\n",
            1,
        ),
        (
            "def f(value: object) -> str:\n    while False:\n        assert isinstance(value, list)\n    return 'known'\n",
            1,
        ),
        (
            "def f(value: object) -> str:\n    assert False\n    assert isinstance(value, list)\n    return 'known'\n",
            1,
        ),
        (
            "def f(value: object) -> list[object]:\n    assert isinstance(value, list) or True\n    return value\n",
            2,
        ),
        (
            "def f(value: object) -> list[object]:\n    assert True or isinstance(value, list)\n    return value\n",
            2,
        ),
        (
            "def f(value: object) -> list[object]:\n    assert enabled or isinstance(value, list)\n    return value\n",
            2,
        ),
        (
            "def f(value: object) -> list[object]:\n    assert not isinstance(value, list)\n    return value\n",
            2,
        ),
        (
            "def f(value: object) -> list[object]:\n    value.domain_only(); assert isinstance(value, list)\n    return value\n",
            2,
        ),
    ],
)
def test_unreachable_or_optional_assertion_cannot_own_raw_contracts(
    rule: PreferPreciseObjectContract, source: str, expected: int
) -> None:
    assert len(rule.check(Path("app/contracts.py"), source)) == expected


@pytest.mark.parametrize(
    "condition",
    [
        "isinstance(value, list)",
        "isinstance(value, list) or False",
        "False or isinstance(value, list)",
        "isinstance(value, list) and enabled",
        "enabled and isinstance(value, list)",
        "not not isinstance(value, list)",
    ],
)
def test_assertion_ownership_requires_a_guard_on_every_successful_path(
    rule: PreferPreciseObjectContract, condition: str
) -> None:
    source = f"def f(value: object) -> list[object]:\n    assert {condition}\n    return value\n"
    assert rule.check(Path("app/contracts.py"), source) == []


@pytest.mark.parametrize(
    "condition",
    ["isinstance(value, list) and precise(value)", "precise(value) and isinstance(value, list)"],
)
def test_assertion_conjunction_keeps_precise_refinement_stronger_than_shallow_guard(
    rule: PreferPreciseObjectContract, condition: str
) -> None:
    source = (
        "from typing import TypeGuard\ndef precise(value: object) -> TypeGuard[list[int]]:\n    return True\n"
        f"def f(value: object) -> object:\n    assert {condition}\n    return value[0]\n"
    )
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


def test_asserted_optional_scalar_guard_keeps_native_result_precise(rule: PreferPreciseObjectContract) -> None:
    source = "import json\ndef f(source: str) -> object:\n    value = json.loads(source)\n    assert isinstance(value, str) or False\n    return value\n"
    assert len(rule.check(Path("app/contracts.py"), source)) == 1


@pytest.mark.parametrize("call", ["bool(value)", "repr(value)", "json.dumps(value)"])
def test_assertion_keeps_independent_universal_input_boundaries(rule: PreferPreciseObjectContract, call: str) -> None:
    source = f"import json\ndef f(value: object) -> None:\n    assert {call}\n"
    assert rule.check(Path("app/contracts.py"), source) == []
