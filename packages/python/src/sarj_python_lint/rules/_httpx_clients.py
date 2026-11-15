from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


ASYNC_CLIENTS = frozenset({"httpx.AsyncClient", "httpx._client.AsyncClient"})
SYNC_CLIENTS = frozenset({"httpx.Client", "httpx._client.Client"})
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
MAX_ALIAS_DEPTH = 32
_MODULES = frozenset({"httpx", "httpx._client"})


def imports_untouched(context: PythonFileContext, clients: frozenset[str]) -> bool:
    safe: dict[ast.alias | ast.Name, bool] = {}
    for binding in context.nodes(ast.alias):
        expression = ast.Name(id=binding.asname or binding.name, ctx=ast.Load())
        qualified = import_name_for_binding(expression, binding, context.parents.get(binding))
        if (
            qualified is not None
            and qualified in _MODULES | clients
            and not _alias_untouched(context, binding, qualified, clients, safe, remaining=MAX_ALIAS_DEPTH)
        ):
            return False
    return True


def _alias_untouched(
    context: PythonFileContext,
    binding: ast.alias | ast.Name,
    qualified: str,
    clients: frozenset[str],
    safe: dict[ast.alias | ast.Name, bool],
    *,
    remaining: int,
) -> bool:
    if binding in safe:
        return safe[binding]
    safe[binding] = False
    name = binding.id if isinstance(binding, ast.Name) else binding.asname or binding.name.partition(".")[0]
    if remaining == 0 or name in context.binding_inventory.mutated:
        return False
    safe[binding] = all(
        _reference_untouched(context, read, qualified, clients, safe, remaining=remaining)
        for read in context.nodes(ast.Name)
        if isinstance(read.ctx, ast.Load) and read.id == name and stable_binding(context, name, read) is binding
    )
    return safe[binding]


def _reference_untouched(
    context: PythonFileContext,
    expression: ast.expr,
    qualified: str,
    clients: frozenset[str],
    safe: dict[ast.alias | ast.Name, bool],
    *,
    remaining: int,
) -> bool:
    if not runtime_expression(context, expression):
        return True
    while qualified in _MODULES:
        parent = context.parents.get(expression)
        if not isinstance(parent, ast.Attribute) or parent.value is not expression:
            return False
        expression, qualified = parent, f"{qualified}.{parent.attr}"
    if qualified not in clients:
        return True
    parent = context.parents.get(expression)
    if (isinstance(parent, ast.Call) and parent.func is expression) or (
        isinstance(parent, ast.Attribute) and parent.value is expression
    ):
        return True
    target = _alias_target(context, parent, expression)
    return target is not None and _alias_untouched(context, target, qualified, clients, safe, remaining=remaining - 1)


def _alias_target(context: PythonFileContext, statement: ast.AST | None, value: ast.expr) -> ast.Name | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and statement.value is value:
        target = statement.targets[0]
    elif isinstance(statement, ast.AnnAssign) and statement.value is value:
        target = statement.target
    else:
        return None
    if not isinstance(context.parents.get(statement), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    return target if isinstance(target, ast.Name) and stable_binding(context, target.id, target) is target else None


def runtime_expression(context: PythonFileContext, expression: ast.expr) -> bool:
    child: ast.AST = expression
    parent = context.parents.get(child)
    while parent is not None:
        if isinstance(parent, ast.TypeAlias | ast.type_param):
            return False
        if isinstance(parent, ast.AnnAssign | ast.arg) and parent.annotation is child:
            return False
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is child:
            return False
        child, parent = parent, context.parents.get(parent)
    return True


def allocates(
    context: PythonFileContext,
    call: ast.Call,
    *,
    clients: frozenset[str],
    follow_factory: bool,
    factories: dict[ast.FunctionDef | ast.Lambda, bool],
) -> bool:
    target = _target(context, call.func)
    if isinstance(target, str):
        return target in clients
    if not follow_factory or not isinstance(target, ast.FunctionDef | ast.Lambda):
        return False
    if isinstance(target, ast.Lambda):
        arguments = target.args
        if any(
            (
                call.args,
                call.keywords,
                arguments.posonlyargs,
                arguments.args,
                arguments.kwonlyargs,
                arguments.vararg,
                arguments.kwarg,
            )
        ):
            return False
    if target not in factories:
        factories[target] = _factory_allocates(context, target, clients, factories)
    return factories[target]


def _factory_allocates(
    context: PythonFileContext,
    target: ast.FunctionDef | ast.Lambda,
    clients: frozenset[str],
    factories: dict[ast.FunctionDef | ast.Lambda, bool],
) -> bool:
    if has_own_yield(target):
        return False
    if isinstance(target, ast.Lambda):
        return isinstance(target.body, ast.Call) and allocates(
            context, target.body, clients=clients, follow_factory=False, factories=factories
        )
    if target.decorator_list:
        return False
    body = target.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return (
        len(body) == 1
        and isinstance(body[0], ast.Return)
        and isinstance(body[0].value, ast.Call)
        and allocates(context, body[0].value, clients=clients, follow_factory=False, factories=factories)
    )


def _target(context: PythonFileContext, expression: ast.expr) -> str | ast.FunctionDef | ast.Lambda | None:
    for _ in range(MAX_ALIAS_DEPTH):
        if isinstance(expression, ast.Lambda):
            return expression
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id in context.binding_inventory.mutated:
            return None
        binding = stable_binding(context, root.id, expression)
        if isinstance(binding, ast.alias):
            return import_name_for_binding(expression, binding, context.parents.get(binding))
        if not isinstance(expression, ast.Name):
            return None
        if isinstance(binding, ast.FunctionDef):
            return _factory_binding(context, binding, expression)
        if not isinstance(binding, ast.Name):
            return None
        value = context.resource_provenance.assignment_value(binding, expression)
        if value is None:
            return None
        expression = value
    return None


def _factory_binding(context: PythonFileContext, definition: ast.FunctionDef, at: ast.expr) -> ast.FunctionDef | None:
    parent = context.parents.get(definition)
    if parent is context.tree:
        return definition
    if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and definition.lineno < at.lineno:
        return definition
    return None


def stable_binding(context: PythonFileContext, name: str, at: ast.AST) -> ast.AST | None:
    if (binding := context.resource_provenance.runtime_binding(name, at)) is not None:
        return binding
    scope = context.binding_inventory.scope(at)
    lambda_body = False
    while isinstance(scope, (*COMPREHENSIONS, ast.Lambda)):
        lambda_body |= isinstance(scope, ast.Lambda)
        first_iterable = isinstance(scope, COMPREHENSIONS) and context.resource_provenance.contains(
            scope.generators[0].iter, at
        )
        if not first_iterable and name in context.binding_inventory.bindings.get(scope, {}):
            return None
        scope = context.binding_inventory.scope(scope)
    bindings = context.runtime_bindings.lookup(scope, name)
    if bindings is None and lambda_body:
        return _lambda_module_binding(context, scope, name)
    return bindings[0] if bindings is not None and len(bindings) == 1 else None


def _lambda_module_binding(context: PythonFileContext, scope: ast.AST | None, name: str) -> ast.AST | None:
    if name in context.binding_inventory.external_bindings:
        return None
    while scope is not context.tree:
        if scope is None:
            return None
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef) and name in context.binding_inventory.bindings.get(
            scope, {}
        ):
            return None
        scope = context.binding_inventory.scope(scope)
    bindings = context.runtime_bindings.lookup(scope, name)
    return bindings[0] if bindings is not None and len(bindings) == 1 else None
