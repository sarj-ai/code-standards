from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FIXTURE = "fixture"

_MIN_FIELDS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class _FixtureDecorators(NamedTuple):
    names: frozenset[str]
    roots: frozenset[str]


class _TupleResult(NamedTuple):
    expression: ast.expr
    field_count: int


class FixtureReturnsBareTuple(Rule):
    id: str = "fixture-returns-bare-tuple"
    code: str = "SARJ044"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Fixture returns a bare multi-field tuple — return a NamedTuple so consumers destructure by name.",
        rationale="Positional fixture results make call sites opaque and allow reordered fields to bind incorrectly.",
        remediation="Return a `NamedTuple`, frozen dataclass, or another value whose fields have stable names.",
        category=RuleCategory.TESTING,
        limitations=(
            "Only pytest and pytest-asyncio fixtures in test paths are analyzed.",
            "Factory closures and single-field tuples are allowed.",
        ),
        examples=(
            RuleExample(
                example_id="fixture-returns-tuple",
                title="Fixture fields are positional",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\n\n@pytest.fixture\ndef stores():\n    return org_store, user_store\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixture-returns-named-value",
                title="Fixture fields are named",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\n\n@pytest.fixture\ndef stores():\n    return Stores(org=org_store, user=user_store)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
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


def _bare_tuple_results(tree: ast.Module) -> list[_TupleResult]:
    hits: list[_TupleResult] = []
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
            hits.append(_TupleResult(node.returns, arity))
    return hits


def _fixture_decorator_names(tree: ast.Module) -> _FixtureDecorators:
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
    return _FixtureDecorators(frozenset(names), frozenset(roots))


def _is_fixture(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    fixture_imports: _FixtureDecorators,
) -> bool:
    return any(_names_fixture(dec, fixture_imports.names, fixture_imports.roots) for dec in node.decorator_list)


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
    optional_member = _optional_member(annotation)
    if optional_member is not None:
        return _fixed_tuple_return_arity(
            optional_member,
            aliases=aliases,
            unwrap_yield_wrapper=unwrap_yield_wrapper,
            resolving=resolving,
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


def _optional_member(annotation: ast.expr) -> ast.expr | None:
    if isinstance(annotation, ast.Subscript):
        name = _dotted_tail(annotation.value)
        if name == "Optional":
            return annotation.slice
        if name == "Union" and isinstance(annotation.slice, ast.Tuple):
            return _only_non_none(annotation.slice.elts)
        return None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        members = _union_members(annotation)
        return _only_non_none(members)
    return None


def _union_members(annotation: ast.expr) -> list[ast.expr]:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return [*_union_members(annotation.left), *_union_members(annotation.right)]
    return [annotation]


def _only_non_none(members: list[ast.expr]) -> ast.expr | None:
    concrete = [member for member in members if not (isinstance(member, ast.Constant) and member.value is None)]
    return concrete[0] if len(concrete) == 1 and len(concrete) < len(members) else None


def _dotted_tail(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


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


def _tuple_results_of(fixture: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_TupleResult]:
    found: list[_TupleResult] = []
    for stmt in fixture.body:
        found.extend(_scan_for_results(stmt))
    return found


def _scan_for_results(node: ast.AST) -> list[_TupleResult]:
    # Descend through control flow but never into a nested function: a tuple
    # returned by a closure the fixture builds crosses the closure's boundary,
    # not the fixture's, so it is a different (and legitimate) shape.
    if isinstance(node, (*_FUNC_NODES, ast.Lambda)):
        return []
    found: list[_TupleResult] = []
    value = _returned_value(node)
    if value is not None:
        count = _bare_tuple_arity(value)
        if count >= _MIN_FIELDS:
            found.append(_TupleResult(value, count))
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
