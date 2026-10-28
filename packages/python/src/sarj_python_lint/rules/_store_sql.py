from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sqlglot import exp

from sarj_python_lint.rules._sql import sql_string_value
from sarj_python_lint.rules._store_writes import Function, methods
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_HOLE = "__sarj_store_sql_hole__"
_FORMAT_HOLE = re.compile(r"(?<!\{)\{(?:[A-Za-z_]\w*|\d*)\}(?!\})")
_MAX_RECOVERY_DEPTH = 8


@dataclass(frozen=True)
class StoreQuery:
    node: ast.expr
    owner: ast.ClassDef | None
    method: Function | None
    sql: str
    statement: exp.Expr


@dataclass(frozen=True)
class QueryOwner:
    owner: ast.ClassDef | None
    method: Function | None


@dataclass(frozen=True)
class _MethodWrites:
    qualified: frozenset[tuple[str, str]]
    instances: frozenset[tuple[ast.ClassDef, str]]


def store_queries(context: PythonFileContext) -> Iterator[StoreQuery]:
    if context.store_queries is None:
        context.store_queries = tuple(recover_store_queries(context))
    return iter(context.store_queries)


def recover_store_queries(context: PythonFileContext) -> Iterator[StoreQuery]:
    calls = psycopg_execution_calls(context, include_injected=True, include_probes=False)
    wrappers = _query_wrappers(calls, context)
    for call in calls:
        argument = _execution_argument(call)
        if argument is not None:
            yield from _parsed_query(argument, call, context)
    for call in context.nodes(ast.Call):
        yield from _forwarded_query(call, wrappers, context)


def _forwarded_query(
    call: ast.Call, wrappers: dict[tuple[ast.ClassDef, str], tuple[int, str]], context: PythonFileContext
) -> Iterator[StoreQuery]:
    if (
        not isinstance(call.func, ast.Attribute)
        or not isinstance(call.func.value, ast.Name)
        or call.func.value.id != "self"
    ):
        return
    scope = query_owner(call, context)
    wrapper = wrappers.get((scope.owner, call.func.attr)) if scope.owner is not None else None
    if wrapper is None:
        return
    positional, parameter = wrapper
    expression = (
        call.args[positional]
        if positional < len(call.args)
        else next((keyword.value for keyword in call.keywords if keyword.arg == parameter), None)
    )
    if expression is not None:
        yield from _parsed_query(expression, call, context)


def _execution_argument(call: ast.Call) -> ast.expr | None:
    return call.args[0] if call.args else next((item.value for item in call.keywords if item.arg == "query"), None)


def _query_wrappers(
    calls: list[ast.Call], context: PythonFileContext
) -> dict[tuple[ast.ClassDef, str], tuple[int, str]]:
    wrappers: dict[tuple[ast.ClassDef, str], tuple[int, str]] = {}
    if not calls:
        return wrappers
    writes = _method_writes(context)
    owner_methods: dict[ast.ClassDef, dict[str, Function]] = {}
    for call in calls:
        scope = query_owner(call, context)
        owner, method = scope.owner, scope.method
        argument = _execution_argument(call)
        if owner is None or method is None or not isinstance(argument, ast.Name):
            continue
        if owner not in owner_methods:
            owner_methods[owner] = methods(owner)
        if (
            owner_methods[owner].get(method.name) is not method
            or (owner.name, method.name) in writes.qualified
            or (owner, method.name) in writes.instances
        ):
            continue
        parameters = [*method.args.posonlyargs, *method.args.args]
        if not parameters or parameters[0].arg != "self":
            continue
        positions = {value.arg: index for index, value in enumerate(parameters[1:])}
        position = positions.get(argument.id)
        binding = context.static_resource_provenance.runtime_binding(argument.id, argument)
        if position is not None and binding is parameters[position + 1]:
            wrappers[owner, method.name] = (position, argument.id)
    return wrappers


def _method_writes(context: PythonFileContext) -> _MethodWrites:
    qualified: set[tuple[str, str]] = set()
    instances: set[tuple[ast.ClassDef, str]] = set()
    for node in context.nodes(ast.Attribute):
        if not isinstance(node.ctx, ast.Store | ast.Del) or not isinstance(node.value, ast.Name):
            continue
        qualified.add((node.value.id, node.attr))
        if node.value.id == "self":
            owner = query_owner(node, context).owner
            if owner is not None:
                instances.add((owner, node.attr))
    return _MethodWrites(frozenset(qualified), frozenset(instances))


def query_owner(node: ast.AST, context: PythonFileContext) -> QueryOwner:
    current = context.parents.get(node)
    while current is not None and not isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        current = context.parents.get(current)
    if not isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
        return QueryOwner(None, None)
    parent = context.parents.get(current)
    return QueryOwner(parent if isinstance(parent, ast.ClassDef) else None, current)


def _parsed_query(expression: ast.expr, call: ast.Call, context: PythonFileContext) -> Iterator[StoreQuery]:
    text = _query_text(expression, context, seen=frozenset())
    if text is None:
        return
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- malformed input abstains.

    from sarj_python_lint.rules._postgres import parse_postgres  # ruff: ignore[import-outside-top-level] -- avoid private-source unsupported SQL logs.

    try:
        statements = parse_postgres(_FORMAT_HOLE.sub(_HOLE, text))
    except SqlglotError, RecursionError:
        return
    scope = query_owner(call, context)
    for statement in statements:
        if statement is not None:
            yield StoreQuery(_query_origin(expression, context), scope.owner, scope.method, text, statement)


def _query_origin(expression: ast.expr, context: PythonFileContext) -> ast.expr:
    seen: set[int] = set()
    while id(expression) not in seen and len(seen) < _MAX_RECOVERY_DEPTH:
        seen.add(id(expression))
        if isinstance(expression, ast.Name):
            value = _bound_value(expression, context)
            if value is not None:
                expression = value
                continue
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Attribute)
            and expression.func.attr == "format"
        ):
            expression = expression.func.value
            continue
        if (
            isinstance(expression, ast.Call)
            and expression.args
            and context.static_resource_provenance.runtime_import_name(expression.func) == "psycopg.sql.SQL"
        ):
            expression = expression.args[0]
            continue
        break
    return expression


def relation_key(node: exp.Expr | None) -> tuple[str, ...] | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- native table identity for parsed queries.

    if not isinstance(node, exp.Table) or not isinstance(sql_child(node, "this"), exp.Identifier):
        return None
    parts = (sql_child(node, "catalog"), sql_child(node, "db"), sql_child(node, "this"))
    identifiers = [part for part in parts if part is not None]
    if not all(isinstance(part, exp.Identifier) for part in identifiers):
        return None
    if any(not part.args.get("quoted") and not part.name.isascii() for part in identifiers):
        return None
    names = tuple(part.name if part.args.get("quoted") else part.name.lower() for part in identifiers)
    return None if any(_HOLE in name for name in names) else names


def sql_child(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)


def sql_children(node: exp.Expr, key: str) -> tuple[exp.Expr, ...]:
    return tuple(child for child in node.iter_expressions() if child.arg_key == key)


def _query_text(expression: ast.expr, context: PythonFileContext, *, seen: frozenset[int]) -> str | None:
    if id(expression) in seen or len(seen) >= _MAX_RECOVERY_DEPTH:
        return None
    seen |= {id(expression)}
    literal = sql_string_value(expression, interpolation_placeholder=_HOLE)
    if literal is not None:
        return literal
    match expression:
        case ast.Name():
            value = _bound_value(expression, context)
            return _query_text(value, context, seen=seen) if value is not None else None
        case ast.Call(func=ast.Attribute(attr="format", value=value)):
            return _query_text(value, context, seen=seen)
        case ast.Call(func=function, args=[argument], keywords=[]):
            if context.static_resource_provenance.runtime_import_name(function) == "psycopg.sql.SQL":
                return _query_text(argument, context, seen=seen)
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            left_sql = _query_text(left, context, seen=seen)
            right_sql = _query_text(right, context, seen=seen)
            if left_sql is not None or right_sql is not None:
                return (left_sql or _HOLE) + (right_sql or _HOLE)
        case _:
            pass
    return None


def _bound_value(expression: ast.Name, context: PythonFileContext) -> ast.expr | None:
    provenance = context.static_resource_provenance
    binding = provenance.runtime_binding(expression.id, expression)
    return provenance.assignment_value(binding, expression) if isinstance(binding, ast.Name) else None
