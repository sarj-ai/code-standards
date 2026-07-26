"""SARJ044: a fixture returning a bare tuple forces positional unpacking everywhere.

`return org, user` makes every consumer write `org, user = setup_orgs()` and
know the order by heart. Adding a third value silently shifts every call site's
meaning rather than breaking it loudly, and a mis-ordered unpack
(`user, org = ...`) type-checks fine and fails somewhere far away. A `NamedTuple`
or a small frozen dataclass names the fields, so consumers destructure by name,
new fields are additive, and the type checker catches a swap at the call site.

This is the house rule the codebase already applies to production code, applied
to fixtures. `CLAUDE.md` states it directly for ordinary functions — "No bare
multi-field tuples across a boundary... a `NamedTuple`... never a positional
`tuple[A, B]`" — and SARJ026 enforces it there. Fixtures were never covered,
which is exactly why they drifted.

Fires when ALL of these hold:

* the file is a test file, and the function carries a `@pytest.fixture` or
  `@pytest_asyncio.fixture` decorator (in any spelling: bare, called, or
  attribute-qualified),
* and the fixture's own body has a top-level `return`/`yield` of a **tuple
  display** with at least two elements.

The nearest-enclosing-function check (the SARJ031 technique) is what makes this
safe: a factory fixture that returns a closure which itself returns a tuple is
attributed to the closure, not the fixture, and does not fire. That pattern is
common and legitimate — the tuple crosses the closure's boundary, not the
fixture's.

Deliberately NOT flagged:

* a `NamedTuple`, dataclass, or any other constructor call — those are
  `ast.Call` nodes, never `ast.Tuple`, so the correct alternative can never be
  mistaken for the smell,
* a single-element tuple — nothing to mis-order,
* a starred tuple (`return *pair, extra`) — the arity is not statically known,
* a tuple returned from a nested helper or closure inside the fixture,
* **a fixture annotated `-> tuple[A, B, ...]` whose element types are all
  syntactically distinct.** The rule's whole argument is that a reorder fails
  silently — and with distinct static types it does not: swapping the elements
  is a type error the checker reports at the call site, which is the same
  protection a `NamedTuple` would buy. Found in bulbul PR #4111 on
  `python/bulbul/bulbul/tests/fixtures/stores.py:421`, which returns
  `-> tuple[PsqlOrganizationStore, PsqlUserStore]`. A repeated type
  (`tuple[str, str]`) still fires: there the reorder really is silent.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FIXTURE = "fixture"

_MIN_FIELDS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class FixtureReturnsBareTuple(Rule):
    """A fixture returning a bare tuple forces every consumer to unpack by position."""

    id: str = "fixture-returns-bare-tuple"
    code: str = "SARJ044"
    description: str = (
        "Fixture returns a bare multi-field tuple — return a NamedTuple so consumers destructure by name."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag pytest fixtures whose own body returns or yields a bare tuple.

        Returns:
            One diagnostic per bare-tuple return, sorted by position.

        """
        if not is_test_path(path):
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
    for node in ast.walk(tree):
        if not isinstance(node, _FUNC_NODES) or not _is_fixture(node):
            continue
        if _returns_distinctly_typed_tuple(node):
            continue
        hits.extend(_tuple_results_of(node))
    return hits


def _returns_distinctly_typed_tuple(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the fixture is annotated as a tuple of all-distinct types.

    A reorder of `tuple[Store, User]` is a type error the checker catches; a
    reorder of `tuple[str, str]` is silent. Only the latter is what this rule
    exists to prevent, so the former is exempt.

    Returns:
        True when the return annotation is a `tuple[...]` whose element types
        are pairwise distinct.

    """
    returns = node.returns
    if not isinstance(returns, ast.Subscript):
        return False
    base = returns.value
    base_name = base.attr if isinstance(base, ast.Attribute) else base.id if isinstance(base, ast.Name) else None
    if base_name not in {"tuple", "Tuple"}:
        return False
    elts = returns.slice.elts if isinstance(returns.slice, ast.Tuple) else [returns.slice]
    # `tuple[str, ...]` is a homogeneous sequence, not a record — not our shape.
    if any(isinstance(e, ast.Constant) and e.value is Ellipsis for e in elts):
        return False
    rendered = [ast.dump(e) for e in elts]
    return len(rendered) >= _MIN_FIELDS and len(set(rendered)) == len(rendered)


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_names_fixture(dec) for dec in node.decorator_list)


def _names_fixture(dec: ast.expr) -> bool:
    # `@pytest.fixture`, `@pytest.fixture(scope=...)`, `@fixture`, `@pytest_asyncio.fixture`.
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute):
        return target.attr == _FIXTURE
    return isinstance(target, ast.Name) and target.id == _FIXTURE


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
    for child in ast.iter_child_nodes(node):
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
