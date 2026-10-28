from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._resource_provenance import builtin_namespace_untouched


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_ALIAS_DEPTH = 8


@dataclass(frozen=True, slots=True)
class LocalAssignment:
    target: ast.Name
    value: ast.expr


def native_builtin(context: PythonFileContext, node: ast.expr, name: str) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == name
        and context.imports.builtin_is_unshadowed(name)
        and builtin_namespace_untouched(context)
    )


def imported_api(context: PythonFileContext, node: ast.expr, qualified: str) -> bool:
    if context.imports.resolved_qualified_name(node) != qualified:
        return False
    provenance = context.static_resource_provenance
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    binding = provenance.binding(root.id, node)
    if not isinstance(binding, ast.alias) or provenance.scope(binding) is not context.tree:
        return False
    if root.id in provenance.mutated:
        return False
    module = qualified.partition(".")[0]
    if not _module_namespace_intact(context, module):
        return False
    for read in provenance.binding_reads(root.id, binding):
        parent = context.parents.get(read)
        if not (isinstance(parent, ast.Attribute) or (isinstance(parent, ast.Call) and parent.func is read)):
            return False
    for reference in context.nodes(ast.Name, ast.Attribute):
        if context.imports.resolved_qualified_name(reference) != qualified:
            continue
        parent = context.parents.get(reference)
        if not isinstance(parent, ast.Call) or parent.func is not reference:
            return False
    return True


def _module_namespace_intact(context: PythonFileContext, module: str) -> bool:
    for member in context.nodes(ast.Attribute):
        target = context.imports.resolved_qualified_name(member)
        if isinstance(member.ctx, ast.Store | ast.Del) and target is not None and target.startswith(module + "."):
            return False
    for statement in context.nodes(ast.Import):
        for alias in statement.names:
            if alias.name != module:
                continue
            if not _namespace_reads_are_members(context, alias):
                return False
    return True


def _namespace_reads_are_members(context: PythonFileContext, alias: ast.alias) -> bool:
    local = alias.asname or alias.name
    for read in context.static_resource_provenance.binding_reads(local, alias):
        parent = context.parents.get(read)
        if not isinstance(parent, ast.Attribute) or parent.value is not read:
            return False
    return True


def local_value(context: PythonFileContext, node: ast.Name) -> ast.expr | None:
    provenance = context.static_resource_provenance
    binding = provenance.binding(node.id, node)
    if not isinstance(binding, ast.Name):
        return None
    return provenance.assignment_value(binding, node)


def value_origin(context: PythonFileContext, expression: ast.expr, *, depth: int = 0) -> str:
    if isinstance(expression, ast.Name):
        value = local_value(context, expression)
        if isinstance(value, ast.Name) and depth < _MAX_ALIAS_DEPTH:
            return value_origin(context, value, depth=depth + 1)
        binding = context.static_resource_provenance.binding(expression.id, expression)
        if isinstance(binding, ast.Name | ast.arg):
            return f"binding:{binding.lineno}:{binding.col_offset}"
    return ast.dump(expression)


def overridden_exit(context: PythonFileContext, node: ast.AST) -> bool:
    parent = context.parents.get(node)
    while parent is not None and not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
        if isinstance(parent, ast.Try | ast.TryStar) and any(
            isinstance(nested, ast.Return | ast.Raise | ast.Break | ast.Continue)
            for statement in parent.finalbody
            for nested in ast.walk(statement)
        ):
            return True
        parent = context.parents.get(parent)
    return False


def local_function(context: PythonFileContext, node: ast.expr) -> ast.FunctionDef | None:
    if not isinstance(node, ast.Name):
        return None
    provenance = context.static_resource_provenance
    binding = provenance.binding(node.id, node)
    if not isinstance(binding, ast.FunctionDef) or binding.decorator_list:
        return None
    if provenance.scope(binding) is not context.tree or node.id in provenance.mutated:
        return None
    for read in provenance.binding_reads(node.id, binding):
        parent = context.parents.get(read)
        if not isinstance(parent, ast.Call) or parent.func is not read:
            return None
    return binding


def function_body(function: ast.FunctionDef) -> list[ast.stmt]:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def assignment(statement: ast.stmt) -> LocalAssignment | None:
    match statement:
        case ast.Assign(targets=[ast.Name() as target], value=value):
            return LocalAssignment(target=target, value=value)
        case ast.AnnAssign(target=ast.Name() as target, value=ast.expr() as value):
            return LocalAssignment(target=target, value=value)
        case _:
            return None


def null_test(expression: ast.expr, name: str) -> bool:
    return (
        isinstance(expression, ast.Compare)
        and isinstance(expression.left, ast.Name)
        and expression.left.id == name
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.Is)
        and len(expression.comparators) == 1
        and isinstance(expression.comparators[0], ast.Constant)
        and expression.comparators[0].value is None
    )


def returns_none(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Return) and (
        statement.value is None or (isinstance(statement.value, ast.Constant) and statement.value.value is None)
    )
