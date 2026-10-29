from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING
import weakref

import pytest

from sarj_python_lint.rules._project_index import ImportNamespaceMutations, ProjectIndexSet, SourceUnit


if TYPE_CHECKING:
    from collections.abc import Mapping


def _units(sources: Mapping[str, str]) -> dict[Path, SourceUnit]:
    return {
        Path(name.replace(".", "/") + ".py"): SourceUnit(
            Path(name.replace(".", "/") + ".py"), name, source, ast.parse(source), MappingProxyType({})
        )
        for name, source in sources.items()
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "driver.Connection = FakeConnection",
        "del driver.Connection",
        "setattr(driver, 'Connection', FakeConnection)",
        "delattr(driver, 'Connection')",
    ],
)
def test_imported_namespace_mutations_follow_reachable_modules_only(mutation: str) -> None:
    units = _units(
        {
            "app.focus": "import app.patch\n",
            "app.other": "import psycopg\n",
            "app.patch": f"import psycopg as driver\n{mutation}\n",
        }
    )
    indexes = ProjectIndexSet(units, sealed=True)
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/focus.py")]) == frozenset(
        {"psycopg", "app.patch"}
    )
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/other.py")]) == frozenset()


def test_namespace_mutations_follow_relative_cycles_and_imported_class_aliases() -> None:
    units = _units(
        {
            "app.focus": "from . import patch\n",
            "app.patch": "from . import focus\nfrom app.driver import Native\nNative.__new__ = make_fake\n",
            "app.driver": "from psycopg import Connection as Native\n",
        }
    )
    indexes = ProjectIndexSet(units, sealed=True)
    mutations = indexes.import_namespace_mutations.for_unit(units[Path("app/focus.py")])
    assert mutations is not None
    assert "psycopg" in mutations


def test_namespace_mutations_include_package_initialization() -> None:
    units = _units({"app.focus": "pass\n", "app": "import psycopg\npsycopg.Connection = Fake\n"})
    package = units.pop(Path("app.py"))
    package = SourceUnit(Path("app/__init__.py"), package.module, package.source, package.tree, package.imports)
    units[package.path] = package
    indexes = ProjectIndexSet(units, sealed=True)
    mutations = indexes.import_namespace_mutations.for_unit(units[Path("app/focus.py")])
    assert mutations is not None
    assert "psycopg" in mutations


def test_namespace_mutations_preserve_old_and_replaced_snapshots() -> None:
    units = _units(
        {
            "app.focus": "import app.patch\n",
            "app.other": "import app.patch\n",
            "app.patch": "import psycopg\npsycopg.Connection = Fake\n",
        }
    )
    indexes = ProjectIndexSet(units, sealed=True)
    focus = units[Path("app/focus.py")]
    original_mutations = indexes.import_namespace_mutations.for_unit(focus)
    assert original_mutations is not None
    assert "psycopg" in original_mutations
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/other.py")]) == original_mutations
    patch = units[Path("app/patch.py")]
    replacement = SourceUnit(patch.path, patch.module, "pass\n", ast.parse("pass\n"), MappingProxyType({}))
    updated = indexes.with_unit(replacement)
    assert updated.import_namespace_mutations.for_unit(focus) == frozenset()
    assert updated.import_namespace_mutations.for_unit(units[Path("app/other.py")]) == frozenset()
    assert indexes.import_namespace_mutations.for_unit(focus) == original_mutations
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/other.py")]) == original_mutations


def test_ambiguous_import_lattice_abstains_without_tainting_unrelated_focus() -> None:
    sources = {
        "app.focus": "import app.patch\n",
        "app.other": "import psycopg\n",
        "app.patch": "from app.layer_0_left import Native\nNative.__new__ = make_fake\n",
    }
    for depth in range(14):
        following = (
            f"if choice:\n    from app.layer_{depth + 1}_left import Native\n"
            f"else:\n    from app.layer_{depth + 1}_right import Native\n"
        )
        for side in ("left", "right"):
            sources[f"app.layer_{depth}_{side}"] = following
    sources["app.layer_14_left"] = "from psycopg import Connection as Native\n"
    sources["app.layer_14_right"] = "from vendor import Connection as Native\n"
    units = _units(sources)
    indexes = ProjectIndexSet(units, sealed=True)
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/focus.py")]) is None
    assert indexes.import_namespace_mutations.for_unit(units[Path("app/other.py")]) == frozenset()


@dataclass(frozen=True)
class _EscapedNamespaceView:
    view: ImportNamespaceMutations
    owner: weakref.ReferenceType[ProjectIndexSet]
    focus: SourceUnit
    other: SourceUnit


def _escaped_namespace_view(*, loaded: bool) -> _EscapedNamespaceView:
    units = _units(
        {
            "app.focus": "import app.patch\n",
            "app.other": "import app.patch\n",
            "app.patch": "import psycopg\npsycopg.Connection = Fake\n",
        }
    )
    indexes = ProjectIndexSet(units, sealed=True)
    focus = units[Path("app/focus.py")]
    view = indexes.import_namespace_mutations
    if loaded:
        mutations = view.for_unit(focus)
        assert mutations is not None
        assert "psycopg" in mutations
    return _EscapedNamespaceView(view, weakref.ref(indexes), focus, units[Path("app/other.py")])


def test_unloaded_namespace_view_does_not_retain_its_index() -> None:
    escaped = _escaped_namespace_view(loaded=False)
    assert escaped.owner() is None
    assert escaped.view.for_unit(escaped.focus) is None


def test_loaded_namespace_view_preserves_frozen_facts_after_index_release() -> None:
    escaped = _escaped_namespace_view(loaded=True)
    assert escaped.owner() is None
    mutations = escaped.view.for_unit(escaped.focus)
    assert mutations is not None
    assert "psycopg" in mutations
    assert escaped.view.for_unit(escaped.other) == mutations
