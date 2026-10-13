from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex
    from sarj_python_lint.rules._project_index import SourceUnit


_BUILTINS = frozenset({"str", "bytes", "int", "float", "bool", "object", "list", "dict", "tuple", "set", "frozenset"})


def stable_local_class(unit: SourceUnit, name: str) -> bool:
    if unit.tree is None:
        return False
    return sum(
        isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        for node in ast.walk(unit.tree)
    ) == 1 and not any(
        (isinstance(node, ast.Name) and node.id == name and not isinstance(node.ctx, ast.Load))
        or (isinstance(node, ast.arg) and node.arg == name)
        for node in ast.walk(unit.tree)
    )


def resolved_operation_signature(
    method: ast.FunctionDef | ast.AsyncFunctionDef, unit: SourceUnit, imports: ImportIndex
) -> str | None:
    arguments = method.args
    if method.type_params or arguments.vararg is not None or arguments.kwarg is not None or method.returns is None:
        return None
    positional = [*arguments.posonlyargs, *arguments.args]
    if not positional or positional[0].arg != "self" or positional[0].annotation is not None:
        return None
    keys = [_type_key(argument.annotation, unit, imports) for argument in (*positional[1:], *arguments.kwonlyargs)]
    result = _type_key(method.returns, unit, imports)
    defaults = [*arguments.defaults, *(default for default in arguments.kw_defaults if default is not None)]
    if (
        result is None
        or any(key is None for key in keys)
        or any(not isinstance(default, ast.Constant) for default in defaults)
    ):
        return None
    return repr(
        (
            type(method).__name__,
            len(arguments.posonlyargs),
            tuple(argument.arg for argument in (*positional, *arguments.kwonlyargs)),
            keys,
            result,
            tuple(ast.dump(default) for default in arguments.defaults),
            tuple(None if default is None else ast.dump(default) for default in arguments.kw_defaults),
        )
    )


def _type_key(node: ast.expr | None, unit: SourceUnit, imports: ImportIndex) -> str | None:
    if node is None or unit.tree is None:
        return None
    match node:
        case ast.Name():
            return _name_type_key(node, unit, imports)
        case ast.Attribute():
            return imports.resolved_qualified_name(node)
        case ast.Constant(value=str()):
            return None
        case ast.Constant():
            return ast.dump(node)
        case _:
            return _compound_type_key(node, unit, imports)


def _name_type_key(node: ast.Name, unit: SourceUnit, imports: ImportIndex) -> str | None:
    if unit.tree is None:
        return None
    name = node.id
    if name in _BUILTINS and imports.builtin_is_unshadowed(name):
        return f"builtins.{name}"
    imported = imports.resolved_qualified_name(node)
    if imported is not None:
        return imported
    if any(isinstance(child, ast.ClassDef) and child.name == name for child in unit.tree.body) and stable_local_class(
        unit, name
    ):
        return f"{unit.module}.{name}"
    return None


def _compound_type_key(node: ast.expr, unit: SourceUnit, imports: ImportIndex) -> str | None:
    match node:
        case ast.Subscript(value=value, slice=argument):
            kind, parts = "subscript", (value, argument)
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            kind, parts = "union", (left, right)
        case ast.Tuple(elts=elements):
            kind, parts = "tuple", tuple(elements)
        case _:
            return None
    keys = tuple(_type_key(part, unit, imports) for part in parts)
    return repr((kind, keys)) if all(key is not None for key in keys) else None
