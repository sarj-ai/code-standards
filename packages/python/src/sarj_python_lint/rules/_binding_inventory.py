from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SCOPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@final
@dataclass(frozen=True, slots=True)
class BindingInventory:
    parents: Mapping[ast.AST, ast.AST]
    bindings: Mapping[ast.AST | None, Mapping[str, tuple[ast.AST, ...]]]
    reads: Mapping[str, tuple[ast.Name, ...]]
    wildcard: bool
    mutated: frozenset[str]
    external_bindings: frozenset[str]

    @classmethod
    def from_context(cls, context: PythonFileContext) -> BindingInventory:
        parents = context.parents
        bindings: dict[ast.AST | None, dict[str, list[ast.AST]]] = defaultdict(lambda: defaultdict(list))
        reads: dict[str, list[ast.Name]] = defaultdict(list)
        mutated: set[str] = set()
        external_bindings: set[str] = set()
        wildcard = False
        for node in context.nodes(ast.AST):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reads[node.id].append(node)
            for name in _bound_names(node):
                bindings[_binding_scope(parents, node)][name].append(node)
                wildcard |= name == "*"
            if isinstance(node, ast.Global | ast.Nonlocal):
                external_bindings.update(node.names)
            if (name := _mutated_namespace(node)) is not None:
                mutated.add(name)
        return cls(
            parents=parents,
            bindings=MappingProxyType(
                {
                    scope: MappingProxyType({name: tuple(nodes) for name, nodes in names.items()})
                    for scope, names in bindings.items()
                }
            ),
            reads=MappingProxyType({name: tuple(nodes) for name, nodes in reads.items()}),
            wildcard=wildcard,
            mutated=frozenset(mutated),
            external_bindings=frozenset(external_bindings),
        )

    def scope(self, node: ast.AST) -> ast.AST | None:
        return _scope(self.parents, node)


def _mutated_namespace(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Store | ast.Del):
        return None
    root = node.value
    while isinstance(root, ast.Attribute):
        root = root.value
    return root.id if isinstance(root, ast.Name) else None


def _scope(parents: Mapping[ast.AST, ast.AST], node: ast.AST) -> ast.AST | None:
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.arguments) and (node in parent.defaults or node in parent.kw_defaults):
            parent = parents.get(parent)
        elif isinstance(parent, _SCOPES) and not (
            (
                isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and node in parent.decorator_list
            )
            or (isinstance(parent, ast.ClassDef) and (node in parent.bases or node in parent.keywords))
        ):
            return parent
        if parent is None:
            return None
        node = parent
        parent = parents.get(parent)
    return None


def _binding_scope(parents: Mapping[ast.AST, ast.AST], node: ast.AST) -> ast.AST | None:
    scope = _scope(parents, node)
    parent = parents.get(node)
    if isinstance(parent, ast.NamedExpr) and parent.target is node:
        while isinstance(scope, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            scope = _scope(parents, scope)
    return scope


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
            return (name,)
        case ast.alias():
            return (node.asname or node.name.partition(".")[0],)
        case (
            ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
        ):
            return (name,)
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return tuple(names)
        case _:
            return ()
