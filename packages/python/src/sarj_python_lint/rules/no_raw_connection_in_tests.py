from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


_POOL_TYPES = frozenset({"AsyncConnectionPool", "ConnectionPool"})
_SQL_METHODS = frozenset(
    {"execute", "executemany", "executescript", "exec_driver_sql", "fetch", "fetchrow", "fetchval", "query", "command"}
)
_QUERY_KEYWORDS = frozenset({"query", "sql", "statement", "command", "operation"})
_SQL_START = re.compile(
    r"\A\s*(?:SELECT\b|WITH\s+\S+[\s\S]*?\bAS\s*\(|INSERT\s+INTO\b|"
    r"UPDATE\s+\S+[\s\S]*?\bSET\b|DELETE\s+FROM\b|TRUNCATE\b|"
    r"(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX|SCHEMA|VIEW|FUNCTION|TRIGGER)\b|"
    r"LOCK\s+TABLE\b|SET\s+(?:LOCAL|TRANSACTION)\b)",
    re.IGNORECASE,
)


@final
class NoRawConnectionInTests(Rule):
    id = "no-raw-connection-in-tests"
    code = "SARJ429"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not execute raw SQL or acquire raw database connections in tests.",
        rationale=(
            "Tests that reach through a pool couple assertions and setup to persistence internals, bypass the "
            "application boundary, and duplicate transaction ownership."
        ),
        remediation=(
            "Exercise the owning store/service API. Do not move SQL into a test-only probe to hide it. Use an exact "
            "SARJ429 suppression for deliberate database bootstrap, migration or transaction fault testing."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("no-raw-sql-in-tests",),
        limitations=(
            "Raw SQL execution is checked in tests, conftest.py, shared test-support helpers and migration tests; generated code is excluded. Standalone SQL examples and store/service calls are not execution.",
            "Import-proven Psycopg connection/pool flows, including constructor-injected members, aliases and dynamic query arguments, are followed. SQL-shaped literals in execute/query/fetch-like calls are also checked across drivers, including concatenation, f-strings and import-proven SQL/text constructors.",
            "Opaque non-Psycopg builders and interprocedural receiver flows are not inferred. Raw connection acquisition keeps its existing fixture/support exclusions when no SQL execution is found in that scope.",
        ),
        examples=(
            RuleExample(
                example_id="test-probe-executes-sql",
                title="An injected test probe still bypasses the owning store",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fixtures/probe.py",
                        "from psycopg_pool import AsyncConnectionPool\n\nclass Probe:\n    def __init__(self, pool: AsyncConnectionPool):\n        self._pool = pool\n\n    async def seed(self):\n        async with self._pool.connection() as conn:\n            await conn.execute('INSERT INTO jobs (id) VALUES (%s)', (job_id,))\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fixtures/probe.py"),
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated or context.tree is None:
            return []
        sql_calls = _test_sql_calls(context)
        diagnostics = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message="test code executes raw SQL; use the owning store/service API or an exact SARJ429 exception for deliberate database-level testing",
            )
            for node in sql_calls
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]
        excluded_path = any(
            (
                not is_test_path(path),
                path.name == "conftest.py",
                is_test_support_path(path),
                _is_non_collected_test_support(path),
                _is_migration_test(path),
            )
        )
        if excluded_path:
            return sorted(diagnostics, key=lambda item: (item.line, item.col))
        tree = context.tree
        if tree is None:
            return []
        sql_scopes = {_containing_scope(context, node) for node in sql_calls}
        scopes: list[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef] = [
            tree,
            *(node for node in context.nodes(ast.AST) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        ]
        for scope in scopes:
            if scope in sql_scopes:
                continue
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


def _test_sql_calls(context: PythonFileContext) -> list[ast.Call]:
    path = context.path
    if not (is_test_path(path) or is_test_support_path(path) or "test_support" in path.parts):
        return []
    candidates = [
        node
        for node in context.nodes(ast.Call)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _SQL_METHODS
    ]
    if not candidates:
        return []
    calls: list[ast.Call] = []
    for node in candidates:
        value = _execution_sql(node, context)
        if value is not None and _SQL_START.search(strip_sql_noise(value)):
            calls.append(node)
    if any(
        isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany"} and node not in calls
        for node in candidates
    ):
        calls.extend(psycopg_execution_calls(context, include_injected=True, include_probes=True))
    unique = {(call.lineno, call.col_offset): call for call in calls}
    return sorted(unique.values(), key=lambda item: (item.lineno, item.col_offset))


def _execution_sql(call: ast.Call, context: PythonFileContext) -> str | None:
    if call.args:
        return _literal_sql(call.args[0], context)
    for keyword in call.keywords:
        if keyword.arg in _QUERY_KEYWORDS:
            return _literal_sql(keyword.value, context)
    return None


def _literal_sql(node: ast.expr | None, context: PythonFileContext) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return _literal_sql(node.func.value, context)
        if node.args and (
            context.imports.resolves(node.func, sources=frozenset({"psycopg.sql"}), symbol="SQL")
            or context.imports.resolves(node.func, sources=frozenset({"sqlalchemy"}), symbol="text")
        ):
            return sql_string_value(node.args[0])
    return sql_string_value(node)


def _containing_scope(context: PythonFileContext, node: ast.AST) -> ast.AST:
    current = node
    while (parent := context.parents.get(current)) is not None:
        if isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent
        current = parent
    return current


def _is_non_collected_test_support(path: Path) -> bool:
    return "tests" in path.parts and not (path.name.startswith("test_") or path.name.endswith("_test.py"))


def _is_migration_test(path: Path) -> bool:
    parts = path.parts
    return any(
        part == "tests" and index + 1 < len(parts) and parts[index + 1] == "migrations"
        for index, part in enumerate(parts)
    )


def _proven_pool_names(scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _pool_parameter_names(scope, names)
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
        and any(isinstance(value, ast.Name) and value.id == bound_name for value in walk_ast(node.value))
        for node in _scope_nodes(scope)
    )


def _is_pytest_fixture(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _tail(decorator.func if isinstance(decorator, ast.Call) else decorator) == "fixture"
        for decorator in scope.decorator_list
    )


def _pool_parameter_names(scope: ast.FunctionDef | ast.AsyncFunctionDef, names: set[str]) -> None:
    names.update(
        argument.arg
        for argument in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
        if _tail(argument.annotation) in _POOL_TYPES
    )
