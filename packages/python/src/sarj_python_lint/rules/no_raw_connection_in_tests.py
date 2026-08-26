from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_POOL_TYPES = frozenset({"AsyncConnectionPool", "ConnectionPool"})


@final
class NoRawConnectionInTests(Rule):
    id = "no-raw-connection-in-tests"
    code = "SARJ429"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not acquire raw database connections in tests.",
        rationale=(
            "Tests that reach through a pool couple assertions and setup to persistence internals, bypass the "
            "application boundary, and duplicate transaction ownership."
        ),
        remediation=(
            "Exercise the owning store/service API or expose a narrow test-support fixture. Use an exact SARJ429 "
            "suppression for a test whose purpose is explicitly connection or transaction behavior."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test paths outside conftest.py and conventional shared test-support modules are inspected.",
            "A receiver is reported only when a parameter, annotated local, or constructor call proves it is a psycopg ConnectionPool or AsyncConnectionPool.",
            "Pytest fixtures may use a connection internally for setup and cleanup, but fixtures that return or yield the connection remain reportable.",
        ),
        examples=(
            RuleExample(
                example_id="test-acquires-pool-connection",
                title="A test helper reaches directly through its pool",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_orders.py",
                        "async def load_rows(pool: AsyncConnectionPool):\n    async with pool.connection() as conn:\n        return await conn.execute('SELECT 1')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_orders.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="test-uses-store-boundary",
                title="A test reads through the owning store API",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_orders.py",
                        "async def load_rows(store: OrderStore):\n    return await store.list_orders()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_orders.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            not is_test_path(path)
            or path.name == "conftest.py"
            or is_test_support_path(path)
            or is_generated(path, source)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        scopes: list[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef] = [
            tree,
            *(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        ]
        for scope in scopes:
            pool_names = _proven_pool_names(scope)
            diagnostics.extend(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "test acquires a raw database connection; use the owning store/service or an explicit "
                        "test-support boundary"
                    ),
                )
                for node in _scope_nodes(scope)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connection"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in pool_names
                and not _is_internal_fixture_connection(scope, node)
            )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _proven_pool_names(scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names.update(
            argument.arg
            for argument in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
            if _tail(argument.annotation) in _POOL_TYPES
        )
    for node in _scope_nodes(scope):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _tail(node.annotation) in _POOL_TYPES:
                names.add(node.target.id)
        elif (
            isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _tail(node.value.func) in _POOL_TYPES
        ):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return frozenset(names)


def _scope_nodes(scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    pending: list[ast.AST] = list(reversed(scope.body))
    while pending:
        node = pending.pop()
        nodes.append(node)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))
    return nodes


def _tail(node: ast.expr | None) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _tail(value)
        case _:
            return ""


def _is_internal_fixture_connection(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef, connection_call: ast.Call
) -> bool:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_pytest_fixture(scope):
        return False
    context_item = next(
        (
            item
            for node in _scope_nodes(scope)
            if isinstance(node, (ast.With, ast.AsyncWith))
            for item in node.items
            if item.context_expr is connection_call
        ),
        None,
    )
    if context_item is None:
        return False
    if context_item.optional_vars is None:
        return True
    if not isinstance(context_item.optional_vars, ast.Name):
        return False
    bound_name = context_item.optional_vars.id
    return not any(
        isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom))
        and node.value is not None
        and any(isinstance(value, ast.Name) and value.id == bound_name for value in ast.walk(node.value))
        for node in _scope_nodes(scope)
    )


def _is_pytest_fixture(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _tail(decorator.func if isinstance(decorator, ast.Call) else decorator) == "fixture"
        for decorator in scope.decorator_list
    )
