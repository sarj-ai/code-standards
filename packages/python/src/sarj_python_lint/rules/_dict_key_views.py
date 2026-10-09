from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import walk


if TYPE_CHECKING:
    from collections.abc import Mapping


_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_NESTED = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def proven_dict_key_views(tree: ast.Module, shadowed: frozenset[str]) -> set[ast.Call]:
    parents = {child: parent for parent in walk(tree) for child in ast.iter_child_nodes(parent)}
    result: set[ast.Call] = set()
    scopes: dict[ast.AST, dict[str, ast.AST]] = {}
    for node in walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "keys"
            and not node.args
            and not node.keywords
        ):
            continue
        receiver = node.func.value
        if _literal_dict(receiver, shadowed) or (
            isinstance(receiver, ast.Name) and _local_dict(receiver, parents, shadowed, scopes)
        ):
            result.add(node)
    return result


def _literal_dict(node: ast.expr, shadowed: frozenset[str]) -> bool:
    return isinstance(node, ast.Dict | ast.DictComp) or (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dict"
        and "dict" not in shadowed
    )


def _local_dict(
    node: ast.Name,
    parents: Mapping[ast.AST, ast.AST],
    shadowed: frozenset[str],
    scopes: dict[ast.AST, dict[str, ast.AST]],
) -> bool:
    ancestor: ast.AST = node
    while not isinstance(ancestor, _SCOPES):
        if isinstance(ancestor, _NESTED):
            return False
        ancestor = parents[ancestor]
    if isinstance(ancestor, ast.ClassDef):
        return False
    if ancestor not in scopes:
        scopes[ancestor] = _unique_bindings(ancestor)
    binding = scopes[ancestor].get(node.id)
    if binding is None:
        return False
    statement = parents.get(binding)
    if not isinstance(statement, ast.Assign | ast.AnnAssign) or parents.get(statement) is not ancestor:
        return False
    if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
        return False
    return statement.lineno < node.lineno and statement.value is not None and _literal_dict(statement.value, shadowed)


def _unique_bindings(scope: ast.AST) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    repeated: set[str] = set()
    for node in walk(scope):
        for name in _bound_names(node):
            if name == "*":
                return {}
            if name in bindings:
                repeated.add(name)
            bindings[name] = node
    return {name: node for name, node in bindings.items() if name not in repeated}


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
            return (name,)
        case ast.alias():
            return (node.asname or node.name.split(".")[0],)
        case (
            ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            return (name,)
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return tuple(names)
        case _:
            return ()
