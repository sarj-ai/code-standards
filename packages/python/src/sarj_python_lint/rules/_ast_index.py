# Breadth-first order and isinstance semantics intentionally match ast.walk because rules rely on first-match order.

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from collections.abc import Iterator


_AST = ast.AST


def children(node: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []
    for name in node._fields:
        value: object = getattr(node, name, None)
        if isinstance(value, list):
            out += [item for item in value if isinstance(item, _AST)]  # pyright: ignore[reportUnknownVariableType] — element narrowed by isinstance
        elif isinstance(value, _AST):
            out.append(value)
    return out


def walk(node: ast.AST) -> Iterator[ast.AST]:
    queue: list[ast.AST] = [node]
    i = 0
    while i < len(queue):
        current = queue[i]
        i += 1
        for name in current._fields:
            value: object = getattr(current, name, None)
            if isinstance(value, list):
                queue += [item for item in value if isinstance(item, _AST)]  # pyright: ignore[reportUnknownVariableType] — element narrowed by isinstance
            elif isinstance(value, _AST):
                queue.append(value)
        yield current


@final
class _NodeIndex:
    __slots__ = ("_buckets", "_flat", "_queries")

    def __init__(self, tree: ast.AST) -> None:
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
            for name in cls._fields:
                value: object = getattr(current, name, None)
                if isinstance(value, list):
                    flat += [item for item in value if isinstance(item, _AST)]  # pyright: ignore[reportUnknownVariableType] — element narrowed by isinstance
                elif isinstance(value, _AST):
                    flat.append(value)
        self._buckets: dict[type[ast.AST], list[ast.AST]] = buckets
        self._flat: list[ast.AST] = flat
        self._queries: dict[tuple[type[ast.AST], ...], list[ast.AST]] = {}

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


_last_index: tuple[ast.AST, _NodeIndex] | None = None
# The strong tree reference prevents a recycled object id from ever reusing a stale index.


def nodes[NodeT: ast.AST](tree: ast.AST, *types: type[NodeT]) -> list[NodeT]:
    global _last_index  # ruff: ignore[global-statement] — single-slot memo, mirroring `parse_or_none`
    if _last_index is None or _last_index[0] is not tree:
        _last_index = (tree, _NodeIndex(tree))
    # The `isinstance` pass is what narrows `list[ast.AST]` to `list[NodeT]`
    return [node for node in _last_index[1].query(types) if isinstance(node, types)]
