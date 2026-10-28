from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

import sarj_python_lint.rules._project_index as project_index
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def _unit(path: str, module: str | None, source: str, imports: Mapping[str, SymbolRef] | None = None) -> SourceUnit:
    return SourceUnit(Path(path), module, source, ast.parse(source), MappingProxyType(dict(imports or {})))


@pytest.fixture
def relationship_units() -> tuple[SourceUnit, ...]:
    aliases = {"Alias": SymbolRef("models", "First"), "mod": SymbolRef("models", "")}
    return (
        _unit("first/models.py", "models", "class First: pass\nclass Second: pass\n"),
        _unit("second/models.py", "models", "class First: pass\nclass Second: pass\n"),
        _unit(
            "first/consumers.py",
            "consumers",
            "from models import First as Alias\n"
            "import models as mod\n"
            "class Direct(Alias, Alias): pass\n"
            "class Other(mod.Second): pass\n"
            "class Generic(Alias[int]): pass\n"
            "class Indirect(Direct): pass\n"
            "class FieldOnly:\n"
            "    value: 'Alias | None'\n"
            "    def use(self, dep: mod.Second, /, *, other: Alias): pass\n"
            "class Constructed:\n"
            "    def __init__(self: mod.Second, dep: 'Alias', /, *, other: mod.Second, **extras: Alias) -> Alias: pass\n"
            "class ClassReceiver:\n"
            "    def __init__(cls: Alias): pass\n"
            "class Ignored:\n"
            "    value: 'not valid syntax!'\n"
            "    nested: \"list['Alias']\"\n"
            "    def use(self: Alias, cls: Alias, *items: Alias, **extras: Alias) -> Alias: pass\n"
            "class FirstInitializer:\n"
            "    def __init__(self, dep: Alias): pass\n"
            "    def __init__(self, dep: mod.Second): pass\n"
            "def outside(dep: Alias):\n"
            "    class Nested(Alias): pass\n",
            aliases,
        ),
        _unit(
            "second/consumers.py",
            "consumers",
            "from models import First as Alias\nclass DuplicateModule(Alias):\n    value: Alias\n",
            {"Alias": SymbolRef("models", "First")},
        ),
        _unit(
            "support/test_standalone.py",
            None,
            "from models import First as Alias\nclass Unpackaged(Alias):\n"
            "    value: Alias\n    def __init__(self, dep: Alias): pass\n",
        ),
        _unit(
            "first/generated/consumer.py",
            "generated.consumer",
            "from models import First as Alias\nclass Generated(Alias):\n    def __init__(self, dep: Alias): pass\n",
            {"Alias": SymbolRef("models", "First")},
        ),
        SourceUnit(Path("first/broken.py"), "broken", "class Broken(:\n", None, MappingProxyType({})),
    )


def test_relationships_preserve_alias_scope_annotations_and_duplicate_modules(
    relationship_units: tuple[SourceUnit, ...],
) -> None:
    indexes = ProjectIndexSet({unit.path: unit for unit in relationship_units}, [Path("first"), Path("second")])
    expected_first_subclasses = frozenset(
        {
            (Path("first/consumers.py"), "Direct"),
            (Path("second/consumers.py"), "DuplicateModule"),
            (Path("support/test_standalone.py"), "Unpackaged"),
            (Path("first/generated/consumer.py"), "Generated"),
        }
    )
    expected_first_constructors = frozenset(
        {
            (Path("first/consumers.py"), "Constructed"),
            (Path("first/consumers.py"), "ClassReceiver"),
            (Path("first/consumers.py"), "FirstInitializer"),
            (Path("first/generated/consumer.py"), "Generated"),
        }
    )
    expected_first_typed = frozenset(
        {
            (Path("first/consumers.py"), "FieldOnly"),
            (Path("first/consumers.py"), "Constructed"),
            (Path("first/consumers.py"), "FirstInitializer"),
            (Path("second/consumers.py"), "DuplicateModule"),
            (Path("first/generated/consumer.py"), "Generated"),
        }
    )
    for project in (indexes, ProjectIndexSet.from_source_snapshot(indexes.source_snapshot())):
        for definition in relationship_units[:2]:
            assert project.direct_subclasses(definition, "First") == expected_first_subclasses
            assert project.constructor_consumers(definition, "First") == expected_first_constructors
            assert project.typed_class_consumers(definition, "First") == expected_first_typed
            assert project.direct_subclasses(definition, "Second") == frozenset({(Path("first/consumers.py"), "Other")})
            assert project.constructor_consumers(definition, "Second") == frozenset(
                {(Path("first/consumers.py"), "Constructed")}
            )
            assert project.typed_class_consumers(definition, "Second") == frozenset(
                {
                    (Path("first/consumers.py"), "FieldOnly"),
                    (Path("first/consumers.py"), "Constructed"),
                    (Path("first/consumers.py"), "FirstInitializer"),
                }
            )
        consumer = relationship_units[2]
        assert project.direct_subclasses(consumer, "Direct") == frozenset({(consumer.path, "Indirect")})
        for lookup in (project.direct_subclasses, project.constructor_consumers, project.typed_class_consumers):
            assert lookup(relationship_units[0], "Missing") == frozenset()
            assert lookup(relationship_units[4], "Unpackaged") == frozenset()


def test_relationship_families_are_built_once_only_when_queried(
    relationship_units: tuple[SourceUnit, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    indexes = ProjectIndexSet({unit.path: unit for unit in relationship_units})
    calls = {"subclasses": 0, "constructors": 0, "typed": 0}
    original_base = project_index._direct_base_symbol  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- count actual extraction while preserving resolution semantics.
    original_constructors = project_index._unit_constructor_consumers  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- count complete construction at its existing helper boundary.
    original_typed = project_index._class_typed_dependencies  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- count independently lazy typed annotation extraction.

    def base_symbol(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
        calls["subclasses"] += 1
        return original_base(unit, expression)

    def constructor_consumers(unit: SourceUnit, tree: ast.Module) -> Iterator[tuple[SymbolRef, str]]:
        calls["constructors"] += 1
        yield from original_constructors(unit, tree)

    def typed_dependencies(unit: SourceUnit, owner: ast.ClassDef) -> Iterator[SymbolRef]:
        calls["typed"] += 1
        yield from original_typed(unit, owner)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count extraction at the cache boundary while retaining actual symbol resolution.
        project_index, "_direct_base_symbol", base_symbol
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count complete constructor inventories rather than timing a tiny fixture.
        project_index, "_unit_constructor_consumers", constructor_consumers
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- prove typed extraction stays independent of constructor extraction.
        project_index, "_class_typed_dependencies", typed_dependencies
    )
    definition = relationship_units[0]
    for lookup in (indexes.direct_subclasses, indexes.constructor_consumers, indexes.typed_class_consumers):
        assert lookup(relationship_units[4], "Unpackaged") == frozenset()
    assert calls == {"subclasses": 0, "constructors": 0, "typed": 0}
    for lookup, family in (
        (indexes.direct_subclasses, "subclasses"),
        (indexes.constructor_consumers, "constructors"),
        (indexes.typed_class_consumers, "typed"),
    ):
        assert calls[family] == 0
        lookup(definition, "First")
        after_first = dict(calls)
        assert after_first[family] > 0
        for name in ("Second", "Missing", "First"):
            lookup(definition, name)
        assert calls == after_first
        if family != "typed":
            assert calls["typed"] == 0


def test_replacing_unit_rebuilds_relationships_without_mutating_original() -> None:
    definition = _unit("app/models.py", "models", "class First: pass\nclass Second: pass\n")
    consumer = _unit(
        "app/consumer.py",
        "consumer",
        "from models import First as Alias\nclass Consumer(Alias):\n    def __init__(self, dep: Alias): pass\n",
        {"Alias": SymbolRef("models", "First")},
    )
    replacement = _unit(
        str(consumer.path),
        consumer.module,
        consumer.source.replace("First as Alias", "Second as Alias"),
        {"Alias": SymbolRef("models", "Second")},
    )
    indexes = ProjectIndexSet({unit.path: unit for unit in (definition, consumer)})
    expected = frozenset({(consumer.path, "Consumer")})
    for lookup in (indexes.direct_subclasses, indexes.constructor_consumers, indexes.typed_class_consumers):
        assert lookup(definition, "First") == expected
        assert lookup(definition, "Second") == frozenset()
    updated = indexes.with_unit(replacement)
    for lookup in (updated.direct_subclasses, updated.constructor_consumers, updated.typed_class_consumers):
        assert lookup(definition, "First") == frozenset()
        assert lookup(definition, "Second") == expected
    for lookup in (indexes.direct_subclasses, indexes.constructor_consumers, indexes.typed_class_consumers):
        assert lookup(definition, "First") == expected


def test_complete_consumer_inventory_keeps_opaque_later_annotations_inert() -> None:
    unit = _unit(
        "app/models.py",
        "models",
        "class Service: pass\n"
        "class Consumer:\n"
        "    dependency: Service\n"
        "    opaque: '\\ud800'\n"
        "    def __init__(self, dependency: Service, opaque: '\\udfff'): pass\n",
    )
    indexes = ProjectIndexSet({unit.path: unit})
    expected = frozenset({(unit.path, "Consumer")})
    assert indexes.typed_class_consumers(unit, "Service") == expected
    assert indexes.constructor_consumers(unit, "Service") == expected


def test_complete_consumer_inventory_keeps_long_later_annotations_inert() -> None:
    annotation = "+".join(["Service"] * 4_000)
    assert len(annotation) < 32_000
    # The parser's recursion threshold varies by Python version. Either parsing
    # this later string or conservatively abstaining must retain the full map.
    unit = _unit(
        "app/models.py",
        "models",
        "class Service: pass\n"
        "class Consumer:\n"
        "    dependency: Service\n"
        f"    opaque: {annotation!r}\n"
        f"    def __init__(self, dependency: Service, opaque: {annotation!r}): pass\n",
    )
    assert len(unit.source) < 65_000
    indexes = ProjectIndexSet({unit.path: unit})
    expected = frozenset({(unit.path, "Consumer")})
    assert indexes.typed_class_consumers(unit, "Service") == expected
    assert indexes.constructor_consumers(unit, "Service") == expected
