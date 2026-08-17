"""SARJ415 keeps DB execution inside constructor-injected pool owners.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_sql_requires_injected_pool_owner.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_POOL_TYPES = frozenset({"AsyncConnectionPool", "ConnectionPool"})
_CONNECTION_TYPES = frozenset({"AsyncConnection", "Connection"})
_EXECUTE_METHODS = frozenset({"execute", "executemany", "executescript"})


@dataclass(frozen=True, slots=True)
class DatabaseBindings:
    database: frozenset[str]
    allowed: frozenset[str]


@final
class SqlRequiresInjectedPoolOwner(Rule):
    id = "sql-requires-injected-pool-owner"
    code = "SARJ415"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Execute database statements only inside a constructor-injected pool owner.",
        rationale="SQL in fixtures and free helpers duplicates persistence contracts outside their owning boundary.",
        remediation="Move the operation behind the store/service that receives and owns the connection pool.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Database receivers must be proven from pool or connection annotations and local with bindings.",
            "Migrations are excluded; deliberate schema/corruption helpers require an exact suppression.",
        ),
        examples=(
            RuleExample(
                example_id="fixture-pool-sql",
                title="A free fixture helper executes through a pool",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fixtures/retry_rows.py",
                        "async def seed(pool: AsyncConnectionPool):\n    async with pool.connection() as conn:\n        await conn.execute('UPDATE call SET retry = true')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fixtures/retry_rows.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="injected-store-sql",
                title="A store executes through its injected pool",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "class Store:\n    def __init__(self, pool: AsyncConnectionPool):\n        self.pool = pool\n    async def save(self):\n        async with self.pool.connection() as conn:\n            await conn.execute('UPDATE call SET retry = true')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or "migrations" in {part.lower() for part in path.parts}:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        owner_attributes = {
            node: _injected_pool_attributes(node) for node in tree.body if isinstance(node, ast.ClassDef)
        }
        method_owners = {
            method: cls
            for cls in owner_attributes
            for method in cls.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        diagnostics: list[Diagnostic] = []
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            owner = method_owners.get(function)
            allowed_attributes: frozenset[str] = (
                owner_attributes.get(owner, frozenset()) if owner is not None else frozenset()
            )
            bindings = _database_names(function, allowed_attributes)
            for call in ast.walk(function):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in _EXECUTE_METHODS
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in bindings.database
                    and call.func.value.id not in bindings.allowed
                ):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message="database execution is outside a constructor-injected pool owner; route it through the owning store/service API",
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _injected_pool_attributes(cls: ast.ClassDef) -> frozenset[str]:
    constructor = next(
        (
            item
            for item in cls.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
        ),
        None,
    )
    if constructor is None:
        return frozenset()
    pools = {argument.arg for argument in constructor.args.args if _tail(argument.annotation) in _POOL_TYPES}
    return frozenset(
        assignment.targets[0].attr
        for assignment in ast.walk(constructor)
        if isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Attribute)
        and isinstance(assignment.targets[0].value, ast.Name)
        and assignment.targets[0].value.id == "self"
        and isinstance(assignment.value, ast.Name)
        and assignment.value.id in pools
    )


def _database_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    allowed_attributes: frozenset[str],
) -> DatabaseBindings:
    database = {
        argument.arg
        for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        if _tail(argument.annotation) in _POOL_TYPES | _CONNECTION_TYPES
    }
    allowed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                if not isinstance(item.optional_vars, ast.Name) or not isinstance(item.context_expr, ast.Call):
                    continue
                receiver = item.context_expr.func
                if not isinstance(receiver, ast.Attribute) or receiver.attr not in {"connection", "cursor"}:
                    continue
                source = receiver.value
                source_allowed = (
                    isinstance(source, ast.Attribute)
                    and isinstance(source.value, ast.Name)
                    and source.value.id == "self"
                    and source.attr in allowed_attributes
                ) or (isinstance(source, ast.Name) and source.id in allowed)
                source_database = source_allowed or (isinstance(source, ast.Name) and source.id in database)
                if source_database and item.optional_vars.id not in database:
                    database.add(item.optional_vars.id)
                    changed = True
                if source_allowed and item.optional_vars.id not in allowed:
                    allowed.add(item.optional_vars.id)
                    changed = True
    return DatabaseBindings(frozenset(database), frozenset(allowed))


def _tail(node: ast.expr | None) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _tail(value)
        case _:
            return ""
