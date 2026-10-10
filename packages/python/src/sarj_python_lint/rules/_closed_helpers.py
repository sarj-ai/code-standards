from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_DYNAMIC_NAMES = frozenset(
    {"globals", "locals", "vars", "eval", "exec", "getattr", "setattr", "delattr", "__import__", "__all__"}
)


def dynamic_namespace(context: PythonFileContext) -> bool:
    return (
        any(node.id in _DYNAMIC_NAMES for node in context.nodes(ast.Name))
        or any(node.attr in _DYNAMIC_NAMES | {"__dict__"} for node in context.nodes(ast.Attribute))
        or any(node.name == "*" for node in context.nodes(ast.alias))
    )


def executable_body(function: ast.FunctionDef) -> list[ast.stmt]:
    body = function.body
    return (
        body[1:]
        if body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
        else body
    )


def closed_references(
    context: PythonFileContext, function: ast.FunctionDef, provenance: ResourceProvenance
) -> list[ast.Name] | None:
    if (
        context.parents.get(function) is not context.tree
        or not function.name.startswith("_")
        or function.name.startswith("__")
        or function.decorator_list
        or function.type_params
    ):
        return None
    if (
        function.args.vararg is not None
        or function.args.kwarg is not None
        or dynamic_namespace(context)
        or any(node.attr == function.name for node in context.nodes(ast.Attribute))
        or any(
            isinstance(node.value, str) and function.name in node.value.split(".")
            for node in context.nodes(ast.Constant)
        )
    ):
        return None
    references = [node for node in context.nodes(ast.Name) if node.id == function.name]
    if not references or any(
        not isinstance(node.ctx, ast.Load) or provenance.binding(node.id, node) is not function for node in references
    ):
        return None
    return references


def direct_call(reference: ast.Name, context: PythonFileContext) -> ast.Call | None:
    parent = context.parents.get(reference)
    if not isinstance(parent, ast.Call) or parent.func is not reference:
        return None
    if any(isinstance(argument, ast.Starred) for argument in parent.args) or any(
        keyword.arg is None for keyword in parent.keywords
    ):
        return None
    return parent


def call_matches(function: ast.FunctionDef, call: ast.Call) -> bool:
    positional = [*function.args.posonlyargs, *function.args.args]
    keywords = {arg.arg for arg in (*function.args.args, *function.args.kwonlyargs)}
    required = {arg.arg for arg in positional[: len(positional) - len(function.args.defaults)]}
    required.update(
        arg.arg
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
        if default is None
    )
    supplied = {arg.arg for arg in positional[: len(call.args)]}
    if len(call.args) > len(positional):
        return False
    for keyword in call.keywords:
        if keyword.arg not in keywords or keyword.arg in supplied:
            return False
        supplied.add(keyword.arg)
    return required <= supplied


def stable_class(context: PythonFileContext, declaration: ast.ClassDef, provenance: ResourceProvenance) -> bool:
    if declaration.decorator_list or declaration.keywords or context.parents.get(declaration) is not context.tree:
        return False
    return provenance.bindings.get(context.tree, {}).get(declaration.name) == [declaration]
