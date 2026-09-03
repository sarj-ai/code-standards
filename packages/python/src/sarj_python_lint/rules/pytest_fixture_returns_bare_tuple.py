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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children
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
    fixture_name: str
    field_counts: tuple[int, ...]


class PytestFixtureReturnsBareTuple(Rule):
    id: str = "pytest-fixture-returns-bare-tuple"
    code: str = "SARJ044"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Pytest fixture exposes a fixed positional record as an unnamed tuple.",
        rationale=(
            "Tuple-shaped fixture APIs encode each value's role in its position, so call sites are opaque and "
            "a reordered result can silently bind the wrong test dependency."
        ),
        remediation=(
            "Return a `NamedTuple`, frozen dataclass, or another result object and access its named fields; "
            "split independent values into separate fixtures when they do not form one record. Keep the tuple and use "
            "an exact SARJ044 suppression when tuple identity or ordering is itself the tested domain contract."
        ),
        category=RuleCategory.TESTING,
        limitations=(
            "Only pytest and pytest-asyncio fixtures in test paths are analyzed.",
            "Factory closures, single-field tuples, starred tuple literals, and variadic tuple annotations are allowed.",
            "Homogeneous variadic tuple annotations are treated as sequences and excluded; fixed domain tuple protocols require an exact suppression.",
        ),
        aliases=("fixture-returns-bare-tuple",),
        examples=(
            RuleExample(
                example_id="fixture-returns-tuple",
                title="Fixture consumers must remember field positions",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\n\n@pytest.fixture\ndef stores():\n    return org_store, user_store\n",
                    ),
                    ExampleFile.python(
                        "tests/test_users.py",
                        "def test_user_lookup(stores):\n    org_store, user_store = stores\n    assert user_store.get('u1')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixture-returns-named-value",
                title="Fixture consumers use named fields",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/support/stores.py",
                        "from dataclasses import dataclass\n\n@dataclass(frozen=True)\n"
                        "class Stores:\n    org: object\n    user: object\n",
                    ),
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\n\nfrom tests.support.stores import Stores\n\n"
                        "@pytest.fixture\ndef stores() -> Stores:\n"
                        "    return Stores(org=org_store, user=user_store)\n",
                    ),
                    ExampleFile.python(
                        "tests/test_users.py",
                        "from tests.support.stores import Stores\n\n"
                        "def test_user_lookup(stores: Stores):\n    assert stores.user.get('u1')\n",
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
                line=result.expression.lineno,
                col=result.expression.col_offset + 1,
                code=self.code,
                message=(
                    f"fixture `{result.fixture_name}` exposes an unnamed {arities}-value record. Return a named "
                    "result object and access fields by name; split independent values into fixtures, or use an "
                    "exact SARJ044 suppression when tuple order is the tested domain contract."
                ),
                severity=Severity.WARNING,
            )
            for result in _bare_tuple_results(tree)
            for arities in (" or ".join(map(str, result.field_counts)),)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _bare_tuple_results(tree: ast.Module) -> list[_TupleResult]:
    hits: list[_TupleResult] = []
    for node in _discoverable_functions(tree):
        fixture_names = _fixture_decorator_names(tree, before_line=node.lineno)
        if not _is_fixture(node, fixture_names):
            continue
        aliases = _type_aliases(tree, before_line=node.lineno)
        has_yield = _has_own_yield(node)
        if node.returns is not None and _homogeneous_tuple_annotation(
            node.returns,
            aliases=aliases,
            unwrap_yield_wrapper=has_yield,
        ):
            continue
        results = _tuple_results_of(node, has_yield=has_yield)
        if results:
            first = min(results, key=lambda result: (result.expression.lineno, result.expression.col_offset))
            hits.append(
                _TupleResult(
                    first.expression,
                    node.name,
                    tuple(sorted({result.field_counts[0] for result in results})),
                )
            )
            continue
        if (
            node.returns is not None
            and (
                arity := _fixed_tuple_return_arity(
                    node.returns,
                    aliases=aliases,
                    unwrap_yield_wrapper=has_yield,
                )
            )
            >= _MIN_FIELDS
        ):
            hits.append(_TupleResult(node.returns, node.name, (arity,)))
    return hits


def _discoverable_functions(tree: ast.Module) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for statement in tree.body:
        if isinstance(statement, _FUNC_NODES):
            functions.append(statement)
        elif isinstance(statement, ast.ClassDef):
            functions.extend(member for member in statement.body if isinstance(member, _FUNC_NODES))
    return tuple(functions)


def _fixture_decorator_names(tree: ast.Module, *, before_line: int) -> _FixtureDecorators:
    names: set[str] = set()
    roots: set[str] = set()
    for statement in tree.body:
        if statement.lineno >= before_line:
            break
        rebound = _bound_names(statement)
        names.difference_update(rebound)
        roots.difference_update(rebound)
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in {"pytest", "pytest_asyncio"}:
                    roots.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom) and statement.module in {"pytest", "pytest_asyncio"}:
            for alias in statement.names:
                if alias.name == "fixture":
                    names.add(alias.asname or alias.name)
    return _FixtureDecorators(frozenset(names), frozenset(roots))


def _bound_names(statement: ast.stmt) -> set[str]:
    match statement:
        case ast.Import() | ast.ImportFrom():
            return {alias.asname or alias.name.split(".")[0] for alias in statement.names}
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return {statement.name}
        case ast.Delete(targets=targets):
            return {node.id for target in targets for node in ast.walk(target) if isinstance(node, ast.Name)}
        case _:
            return {
                node.id
                for node in ast.walk(statement)
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
            }


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


def _type_aliases(tree: ast.Module, *, before_line: int) -> dict[str, ast.expr]:
    aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        if statement.lineno >= before_line:
            break
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
    match annotation:
        case ast.Constant(value=str() as value):
            try:
                parsed = ast.parse(value, mode="eval").body
            except SyntaxError:
                return 0
            return _fixed_tuple_return_arity(
                parsed, aliases=aliases, unwrap_yield_wrapper=unwrap_yield_wrapper, resolving=resolving
            )
        case ast.Name(id=name) if name not in resolving:
            target = aliases.get(name)
            return (
                0
                if target is None
                else _fixed_tuple_return_arity(
                    target,
                    aliases=aliases,
                    unwrap_yield_wrapper=unwrap_yield_wrapper,
                    resolving=resolving | {name},
                )
            )
        case ast.Subscript(value=value, slice=annotation_slice) if _dotted_tail(value) == "Annotated":
            first = annotation_slice.elts[0] if isinstance(annotation_slice, ast.Tuple) else annotation_slice
            return _fixed_tuple_return_arity(
                first,
                aliases=aliases,
                unwrap_yield_wrapper=unwrap_yield_wrapper,
                resolving=resolving,
            )
        case _:
            pass
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
    if any(_is_variadic_tuple_member(element) for element in elements):
        return 0
    return len(elements)


def _is_variadic_tuple_member(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Starred)
        or (isinstance(node, ast.Constant) and node.value is Ellipsis)
        or (isinstance(node, ast.Subscript) and _dotted_tail(node.value) == "Unpack")
    )


def _homogeneous_tuple_annotation(
    annotation: ast.expr,
    *,
    aliases: dict[str, ast.expr],
    unwrap_yield_wrapper: bool,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    if isinstance(annotation, ast.Name) and annotation.id not in resolving:
        target = aliases.get(annotation.id)
        return target is not None and _homogeneous_tuple_annotation(
            target,
            aliases=aliases,
            unwrap_yield_wrapper=unwrap_yield_wrapper,
            resolving=resolving | {annotation.id},
        )
    optional_member = _optional_member(annotation)
    if optional_member is not None:
        return _homogeneous_tuple_annotation(
            optional_member,
            aliases=aliases,
            unwrap_yield_wrapper=unwrap_yield_wrapper,
            resolving=resolving,
        )
    if not isinstance(annotation, ast.Subscript):
        return False
    name = _dotted_tail(annotation.value)
    elements = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else (annotation.slice,)
    if name == "Annotated" and elements:
        return _homogeneous_tuple_annotation(
            elements[0],
            aliases=aliases,
            unwrap_yield_wrapper=unwrap_yield_wrapper,
            resolving=resolving,
        )
    if unwrap_yield_wrapper and name in {
        "Generator",
        "Iterator",
        "Iterable",
        "AsyncGenerator",
        "AsyncIterator",
        "AsyncIterable",
    }:
        return _homogeneous_tuple_annotation(
            elements[0],
            aliases=aliases,
            unwrap_yield_wrapper=False,
            resolving=resolving,
        )
    return name in {"tuple", "Tuple"} and (
        (len(elements) == _MIN_FIELDS and _is_ellipsis(elements[1]))
        or any(_is_variadic_tuple_member(element) for element in elements)
    )


def _is_ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


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


def _tuple_results_of(fixture: ast.FunctionDef | ast.AsyncFunctionDef, *, has_yield: bool) -> list[_TupleResult]:
    found: list[_TupleResult] = []
    for stmt in fixture.body:
        found.extend(_scan_for_results(stmt, has_yield=has_yield))
    return found


def _scan_for_results(node: ast.AST, *, has_yield: bool) -> list[_TupleResult]:
    # Descend through control flow but never into a nested function: a tuple
    # returned by a closure the fixture builds crosses the closure's boundary,
    # not the fixture's, so it is a different (and legitimate) shape.
    if isinstance(node, (*_FUNC_NODES, ast.Lambda)):
        return []
    found: list[_TupleResult] = []
    value = node.value if isinstance(node, ast.Yield) and has_yield else None
    if isinstance(node, ast.Return) and not has_yield:
        value = node.value
    if value is not None:
        count = _bare_tuple_arity(value)
        if count >= _MIN_FIELDS:
            found.append(_TupleResult(value, "", (count,)))
    for child in children(node):
        found.extend(_scan_for_results(child, has_yield=has_yield))
    return found


def _bare_tuple_arity(value: ast.expr) -> int:
    if not isinstance(value, ast.Tuple):
        return 0
    if any(isinstance(elt, ast.Starred) for elt in value.elts):
        return 0
    return len(value.elts)
