from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._pydantic_field_contract import (
    inert_annotation,
    inert_class_value,
    inert_signature,
    literal_value,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_DYNAMIC_NAMES = frozenset(
    {"globals", "locals", "vars", "eval", "exec", "getattr", "setattr", "delattr", "__import__", "__all__"}
)


def dynamic_namespace(context: PythonFileContext) -> bool:
    return (
        context.dynamic_namespace
        or any(node.id in _DYNAMIC_NAMES for node in context.nodes(ast.Name))
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
    if has_member_import(context.tree, function.name, node_index=context.node_index):
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


def has_member_import(tree: ast.Module | None, name: str, *, node_index: NodeIndex | None = None) -> bool:
    return tree is None or any(
        alias.name == name for node in nodes(tree, ast.ImportFrom, index=node_index) for alias in node.names
    )


def direct_call(reference: ast.Name, context: PythonFileContext) -> ast.Call | None:
    parent = context.parents.get(reference)
    if not isinstance(parent, ast.Call) or parent.func is not reference:
        return None
    if any(isinstance(argument, ast.Starred) for argument in parent.args) or any(
        keyword.arg is None for keyword in parent.keywords
    ):
        return None
    return parent


def call_matches(function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call) -> bool:
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
    return provenance.bindings.get(context.tree, {}).get(declaration.name) == (declaration,)


def plain_class_members(
    context: PythonFileContext,
    declaration: ast.ClassDef,
    provenance: ResourceProvenance,
    *,
    pydantic_fields: bool = False,
) -> bool:
    return all(
        _plain_class_member(context, member, provenance, pydantic_fields=pydantic_fields) for member in declaration.body
    )


def _plain_class_member(
    context: PythonFileContext, member: ast.stmt, provenance: ResourceProvenance, *, pydantic_fields: bool
) -> bool:
    match member:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            if member.name.startswith("__"):
                return False
            return inert_signature(member, context) and all(
                _plain_decorator(context, decorator, provenance, pydantic_fields=pydantic_fields)
                for decorator in member.decorator_list
            )
        case ast.AnnAssign(target=ast.Name(), annotation=annotation, value=value):
            return inert_annotation(annotation, context) and (
                value is None or inert_class_value(context, value, provenance, pydantic_fields=pydantic_fields)
            )
        case ast.Assign(targets=targets, value=value):
            return all(isinstance(target, ast.Name) for target in targets) and inert_class_value(
                context, value, provenance, pydantic_fields=pydantic_fields
            )
        case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
            return True
        case _:
            return False


def _plain_decorator(
    context: PythonFileContext, decorator: ast.expr, provenance: ResourceProvenance, *, pydantic_fields: bool
) -> bool:
    if isinstance(decorator, ast.Name) and decorator.id in {"classmethod", "staticmethod", "property"}:
        return context.imports.builtin_is_unshadowed(decorator.id) and provenance.builtin_namespace_untouched
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    qualified = context.module_imports.resolved_qualified_name(target)
    if qualified in {"typing.final", "typing_extensions.final"} and not isinstance(decorator, ast.Call):
        return provenance.imported(target, qualified)
    if (
        not pydantic_fields
        or not isinstance(decorator, ast.Call)
        or qualified
        not in {
            "pydantic.model_validator",
            "pydantic.field_validator",
            "pydantic.functional_validators.model_validator",
            "pydantic.functional_validators.field_validator",
        }
        or not provenance.imported(target, qualified)
    ):
        return False
    return all(literal_value(argument) for argument in decorator.args) and all(
        keyword.arg is not None
        and literal_value(keyword.value)
        and not (keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "wrap")
        for keyword in decorator.keywords
    )


def closed_owner(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    if not isinstance(function, ast.FunctionDef) or not function.name.startswith("_"):
        return False
    references = closed_references(context, function, context.resource_provenance)
    return bool(references) and all(
        (call := direct_call(reference, context)) is not None and call_matches(function, call)
        for reference in references
    )
