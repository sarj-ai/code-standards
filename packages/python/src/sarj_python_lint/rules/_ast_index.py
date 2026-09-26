# Breadth-first order and isinstance semantics intentionally match ast.walk because rules rely on first-match order.

from __future__ import annotations

import ast
from types import MappingProxyType
from typing import TYPE_CHECKING, TypeIs, final


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


_AST = ast.AST


def object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def children(node: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []
    for name in node._fields:
        value: object = getattr(node, name, None)
        if object_list(value):
            out += [item for item in value if isinstance(item, _AST)]
        elif isinstance(value, _AST):
            out.append(value)
    return out


def walk(node: ast.AST, *, index: NodeIndex | None = None) -> Iterator[ast.AST]:
    if index is not None and index.tree is node:
        yield from index.query((ast.AST,))
        return
    queue: list[ast.AST] = [node]
    i = 0
    while i < len(queue):
        current = queue[i]
        i += 1
        queue += children(current)
        yield current


@final
class NodeIndex:
    __slots__ = ("_buckets", "_flat", "_parents", "_queries", "tree")

    def __init__(self, tree: ast.AST) -> None:
        self.tree = tree
        buckets: dict[type[ast.AST], list[ast.AST]] = {}
        flat: list[ast.AST] = [tree]
        i = 0
        while i < len(flat):
            current = flat[i]
            i += 1
            cls = current.__class__
            bucket = buckets.get(cls)
            if bucket is None:
                buckets[cls] = [current]
            else:
                bucket.append(current)
            flat += children(current)
        self._buckets: dict[type[ast.AST], list[ast.AST]] = buckets
        self._flat: list[ast.AST] = flat
        self._parents: Mapping[ast.AST, ast.AST] | None = None
        self._queries: dict[tuple[type[ast.AST], ...], list[ast.AST]] = {}

    @property
    def parents(self) -> Mapping[ast.AST, ast.AST]:
        if self._parents is None:
            self._parents = MappingProxyType({child: parent for parent in self._flat for child in children(parent)})
        return self._parents

    def query(self, types: tuple[type[ast.AST], ...]) -> list[ast.AST]:
        hit = self._queries.get(types)
        if hit is not None:
            return hit
        matched = frozenset(cls for cls in self._buckets if issubclass(cls, types))
        if len(matched) == 1:
            # The single bucket is already the answer, in breadth-first order.
            result = self._buckets[next(iter(matched))]
        elif len(matched) == len(self._buckets):
            # Every class present matches — e.g. `nodes(tree, ast.AST)`, asked by
            # a rule whose loop body inspects every node rather than a few types.
            result = self._flat
        elif matched:
            result = [node for node in self._flat if node.__class__ in matched]
        else:
            result = []
        self._queries[types] = result
        return result


def nodes[NodeT: ast.AST](tree: ast.AST, *types: type[NodeT], index: NodeIndex | None = None) -> list[NodeT]:
    selected = index if index is not None and index.tree is tree else NodeIndex(tree)
    return [node for node in selected.query(types) if isinstance(node, types)]


def parent_map(tree: ast.AST, *, index: NodeIndex | None = None) -> Mapping[ast.AST, ast.AST]:
    selected = index if index is not None and index.tree is tree else NodeIndex(tree)
    return selected.parents
