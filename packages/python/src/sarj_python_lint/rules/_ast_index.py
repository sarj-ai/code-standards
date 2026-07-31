"""One tree traversal per file, shared by every rule that needs node lookups.

Profiling the whole registry over a 1,920-line module showed `ast.walk` and its
helpers (`iter_child_nodes` / `iter_fields`) accounting for ~60% of all rule
time. The cause is structural rather than any one rule's fault: the dominant
shape of a rule is

    for node in ast.walk(tree):
        if isinstance(node, ast.Something):
            ...

so a file with N nodes and R rules asking that question pays R full traversals,
each one re-deriving the same partition of the tree by node type.

`nodes()` derives that partition **once per file** and answers every subsequent
type query from it. The index is memoized in a single slot keyed on tree
identity, mirroring `parse_or_none`: the CLI iterates files on the outer loop
and rules on the inner one, so one slot is all that is ever live. The slot holds
a strong reference to the tree, so a recycled `id()` can never alias a stale
index.

Two invariants make the substitution finding-preserving, not merely faster:

* **Order.** The index is built by breadth-first traversal, the same order
  `ast.walk` yields, and every query preserves it. `nodes(tree, T)` is therefore
  elementwise equal to `[n for n in ast.walk(tree) if isinstance(n, T)]`, so a
  rule that takes the *first* match, or reports in discovery order, is
  unaffected.
* **Subclasses.** Queries match by `isinstance`, not by exact type: the buckets
  are keyed on exact class, and a query resolves to the set of present classes
  that are subclasses of the requested types. Asking for `ast.stmt` still
  returns every statement.

`walk()` is the same breadth-first order for the cases the index cannot serve —
traversing a *subtree* rather than the module, where containment is not
something a whole-module partition can answer.

No rule may mutate the tree. That was already required — every rule shares one
memoized parse, and `duplicate_test_body` deep-copies before normalizing — and
the index inherits the requirement, since it holds references into the tree it
was built from.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from collections.abc import Iterator


_AST = ast.AST


def children(node: ast.AST) -> list[ast.AST]:
    """`node`'s direct children, in the same order as `ast.iter_child_nodes`.

    A list rather than a generator: every caller either iterates it once or
    extends a stack with it, and the hand-rolled walkers in this package call
    this once per node, where the generator's setup cost dominates the work.

    """
    out: list[ast.AST] = []
    for name in node._fields:
        value: object = getattr(node, name, None)
        if isinstance(value, list):
            out += [item for item in value if isinstance(item, _AST)]  # pyright: ignore[reportUnknownVariableType] — element narrowed by isinstance
        elif isinstance(value, _AST):
            out.append(value)
    return out


def walk(node: ast.AST) -> Iterator[ast.AST]:
    """Yield `node` and every descendant, breadth-first.

    Identical in order to `ast.walk`, but reads each node's fields directly
    instead of routing every node through two intermediate generators.

    """
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
    """A module's nodes partitioned by exact class, in breadth-first order."""

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
        """Return every node matching `isinstance(node, types)`, breadth-first."""
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


def nodes[NodeT: ast.AST](tree: ast.AST, *types: type[NodeT]) -> list[NodeT]:
    """Every node of `tree` matching `types`, in `ast.walk` order.

    A drop-in, memoized replacement for the ubiquitous
    `[n for n in ast.walk(tree) if isinstance(n, types)]`. Pass the *module*
    tree: the index is per-file, so calling this with a subtree builds a fresh
    index and evicts the module's. Use `walk` for subtrees.

    """
    global _last_index  # ruff: ignore[global-statement] — single-slot memo, mirroring `parse_or_none`
    if _last_index is None or _last_index[0] is not tree:
        _last_index = (tree, _NodeIndex(tree))
    # The `isinstance` pass is what narrows `list[ast.AST]` to `list[NodeT]`
    # honestly, rather than asserting it with a `cast` the house style bans. It
    # runs over the matches only — never the tree — and every element passes by
    # construction, so it costs one type check per node actually returned.
    return [node for node in _last_index[1].query(types) if isinstance(node, types)]
