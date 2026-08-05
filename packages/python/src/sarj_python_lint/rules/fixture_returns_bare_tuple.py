"""SARJ044 — A fixture returning a bare tuple forces positional unpacking everywhere.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_fixture_returns_bare_tuple.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FIXTURE = "fixture"

_MIN_FIELDS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class FixtureReturnsBareTuple(Rule):
    id: str = "fixture-returns-bare-tuple"
    code: str = "SARJ044"
    description: str = (
        "Fixture returns a bare multi-field tuple — return a NamedTuple so consumers destructure by name."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag pytest fixtures whose own body returns or yields a bare tuple."""
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this fixture hands back a bare {count}-field tuple, so every consumer unpacks it "
                    "positionally and a reorder fails silently. Return a `NamedTuple` (or a frozen "
                    "dataclass) so the fields are named."
                ),
            )
            for node, count in _bare_tuple_results(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _bare_tuple_results(tree: ast.Module) -> list[tuple[ast.expr, int]]:
    hits: list[tuple[ast.expr, int]] = []
    fixture_names = _fixture_decorator_names(tree)
    aliases = _type_aliases(tree)
    for node in nodes(tree, *_FUNC_NODES):
        if not _is_fixture(node, fixture_names):
            continue
        results = _tuple_results_of(node)
        if results:
            hits.extend(results)
            continue
        if (
            node.returns is not None
            and (
                arity := _fixed_tuple_return_arity(
                    node.returns,
                    aliases=aliases,
                    unwrap_yield_wrapper=_has_own_yield(node),
                )
            )
            >= _MIN_FIELDS
        ):
            hits.append((node.returns, arity))
    return hits


def _fixture_decorator_names(tree: ast.Module) -> tuple[frozenset[str], frozenset[str]]:
    names: set[str] = set()
    roots: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in {"pytest", "pytest_asyncio"}:
                    roots.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom) and statement.module in {"pytest", "pytest_asyncio"}:
            for alias in statement.names:
                if alias.name == "fixture":
                    names.add(alias.asname or alias.name)
    return frozenset(names), frozenset(roots)


def _is_fixture(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    fixture_imports: tuple[frozenset[str], frozenset[str]],
) -> bool:
    names, roots = fixture_imports
    return any(_names_fixture(dec, names, roots) for dec in node.decorator_list)


def _names_fixture(dec: ast.expr, fixture_names: frozenset[str], fixture_roots: frozenset[str]) -> bool:
    # `@pytest.fixture`, `@pytest.fixture(scope=...)`, `@fixture`, `@pytest_asyncio.fixture`.
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute):
        return target.attr == _FIXTURE and isinstance(target.value, ast.Name) and target.value.id in fixture_roots
    return isinstance(target, ast.Name) and target.id in fixture_names


def _type_aliases(tree: ast.Module) -> dict[str, ast.expr]:
    aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.TypeAlias):
            aliases[statement.name.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and isinstance(statement.annotation, (ast.Name, ast.Attribute))
            and (statement.annotation.id if isinstance(statement.annotation, ast.Name) else statement.annotation.attr)
            == "TypeAlias"
            and statement.value is not None
        ):
            aliases[statement.target.id] = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Subscript)
        ):
            aliases[statement.targets[0].id] = statement.value
    return aliases


def _fixed_tuple_return_arity(
    annotation: ast.expr,
    *,
    aliases: dict[str, ast.expr],
    unwrap_yield_wrapper: bool,
    resolving: frozenset[str] = frozenset(),
) -> int:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return 0
        return _fixed_tuple_return_arity(
            parsed, aliases=aliases, unwrap_yield_wrapper=unwrap_yield_wrapper, resolving=resolving
        )
    if isinstance(annotation, ast.Name) and annotation.id not in resolving:
        target = aliases.get(annotation.id)
        return (
            0
            if target is None
            else _fixed_tuple_return_arity(
                target,
                aliases=aliases,
                unwrap_yield_wrapper=unwrap_yield_wrapper,
                resolving=resolving | {annotation.id},
            )
        )
    if not isinstance(annotation, ast.Subscript):
        return 0
    name = (
        annotation.value.attr
        if isinstance(annotation.value, ast.Attribute)
        else (annotation.value.id if isinstance(annotation.value, ast.Name) else None)
    )
    if unwrap_yield_wrapper and name in {
        "Generator",
        "Iterator",
        "Iterable",
        "AsyncGenerator",
        "AsyncIterator",
        "AsyncIterable",
    }:
        first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
        return _fixed_tuple_return_arity(first, aliases=aliases, unwrap_yield_wrapper=False, resolving=resolving)
    if name not in {"tuple", "Tuple"} or not isinstance(annotation.slice, ast.Tuple):
        return 0
    elements = annotation.slice.elts
    if any(isinstance(element, ast.Constant) and element.value is Ellipsis for element in elements):
        return 0
    return len(elements)


def _has_own_yield(fixture: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    stack: list[ast.AST] = list(fixture.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (*_FUNC_NODES, ast.Lambda)):
            continue
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        stack.extend(children(node))
    return False


def _tuple_results_of(fixture: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.expr, int]]:
    found: list[tuple[ast.expr, int]] = []
    for stmt in fixture.body:
        found.extend(_scan_for_results(stmt))
    return found


def _scan_for_results(node: ast.AST) -> list[tuple[ast.expr, int]]:
    # Descend through control flow but never into a nested function: a tuple
    # returned by a closure the fixture builds crosses the closure's boundary,
    # not the fixture's, so it is a different (and legitimate) shape.
    if isinstance(node, (*_FUNC_NODES, ast.Lambda)):
        return []
    found: list[tuple[ast.expr, int]] = []
    value = _returned_value(node)
    if value is not None:
        count = _bare_tuple_arity(value)
        if count >= _MIN_FIELDS:
            found.append((value, count))
    for child in children(node):
        found.extend(_scan_for_results(child))
    return found


def _returned_value(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Return):
        return node.value
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Yield):
        return node.value.value
    return None


def _bare_tuple_arity(value: ast.expr) -> int:
    if not isinstance(value, ast.Tuple):
        return 0
    if any(isinstance(elt, ast.Starred) for elt in value.elts):
        return 0
    return len(value.elts)
