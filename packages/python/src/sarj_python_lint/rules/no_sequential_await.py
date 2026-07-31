"""SARJ001: detect the `for x in xs: await f(x)` gather antipattern.

Sequential `await` in a for-loop serializes I/O that could be parallelized
with `asyncio.gather([f(x) for x in xs])`. The performance gap is often 10-100x
for network-bound work (HTTP, DB queries, LLM calls).

Deliberately narrow, to flag the textbook antipattern and almost nothing else —
an over-broad version drowned real signal under suppressions. The rule fires
only for:

* a `for` loop whose body is **straight-line** (no `if`/`try`/`with`/`return`/
  `break`/`continue`/`raise`/nested loop — those signal conditional or ordered
  logic, not a parallel map) and awaits a call that **uses the loop variable**
  (so each iteration is a distinct, independent call); or
* a comprehension / generator expression with an `await` in its element or a
  per-element `if` (those have no ordered side effects).

It does NOT fire for: `while` loops (pagination, polling, queue drains — length
unknown, inherently sequential), a loop's once-evaluated iterable
(`for x in await fetch()`), `async for`, test modules (intentional ordering),
a `for` body containing control flow, or modules that import `trio`/`anyio` —
those runtimes have no `asyncio.gather`; their structured-concurrency style
makes a sequential-await loop the deliberate norm (channel sends, ordered
finalization), so the suggested fix does not exist there. Those were the
false-positive sources.

Two further exemptions, both minimized from a 2,657-file third-party sweep:

* **A loop-carried result** — `value = await function(value, element)` — is a
  fold, not a map: iteration N+1 consumes iteration N's result, so there is
  nothing to run concurrently and `gather` cannot express it (anyio's
  `functools.reduce`). Only an `Assign` whose own target is read inside the
  awaited expression qualifies; `results.append(await f(x))` is still a map and
  still fires.
* **Structured-concurrency primitives used without an absolute import** —
  `CancelScope`, `create_task_group`, `start_soon`, `open_nursery`,
  `checkpoint`, `fail_after`, `move_on_after`. trio's and anyio's *own* modules
  reach their runtime through relative imports (`from .. import
  create_task_group`), so the import check above cannot see it and every
  ordered `await listener.aclose()` in their cleanup paths was flagged with a
  fix (`asyncio.gather`) that does not exist in that codebase. `asyncio` has no
  such names, so an asyncio module is unaffected.

References:
- https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class NoSequentialAwait(Rule):
    """Sequential await calls in a loop that could be parallelized."""

    id: str = "no-sequential-await"
    code: str = "SARJ001"
    description: str = "Sequential `await` in a for-loop — prefer asyncio.gather."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        if "await" not in source or "for " not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _imports_non_asyncio_runtime(tree, source) or _uses_structured_concurrency(tree, source):
            return []
        visitor = _SequentialAwaitVisitor(_exempt_awaits(tree, source))
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=("Sequential `await` inside `for` — prefer `asyncio.gather([f(x) for x in xs])`."),
            )
            for node in visitor.hits
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


# A loop's *iterable* is evaluated once in the enclosing scope, NOT per element:
# `for x in await fetch()` / `{x for x in await fetch()}` await once. Iterables
# are visited *before* the loop is pushed, so an await there attributes to an
# enclosing loop (if any), not this one.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

# Top-level body statements that signal conditional or ordered logic rather than
# a straight-line parallel map. A `for` whose body contains any of these is not
# treated as the gather antipattern.
_CONTROL_FLOW = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
    ast.Return,
    ast.Break,
    ast.Continue,
    ast.Raise,
)


_NON_ASYNCIO_RUNTIMES = frozenset({"trio", "anyio"})


def _imports_non_asyncio_runtime(tree: ast.AST, source: str) -> bool:
    """Report whether the module imports a non-asyncio async runtime (trio/anyio).

    `asyncio.gather` does not exist under those runtimes, and their structured
    concurrency makes sequential awaits in a loop the deliberate norm.

    Naming either runtime in the text is a precondition for importing it, so the
    substring test gates the traversal without narrowing what qualifies.

    Returns:
        True when trio or anyio is imported anywhere in the module.

    """
    if not any(runtime in source for runtime in _NON_ASYNCIO_RUNTIMES):
        return False
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in _NON_ASYNCIO_RUNTIMES for alias in node.names):
                return True
        elif node.module is not None and node.module.split(".")[0] in _NON_ASYNCIO_RUNTIMES:
            return True
    return False


# Names that exist only in trio / anyio, so a module using one is a
# structured-concurrency module even when it reaches its runtime by a relative
# import. `TaskGroup` is deliberately absent: `asyncio.TaskGroup` shares it.
_STRUCTURED_CONCURRENCY_NAMES = frozenset(
    {
        "CancelScope",
        "create_task_group",
        "start_soon",
        "open_nursery",
        "checkpoint",
        "fail_after",
        "move_on_after",
        "create_memory_object_stream",
    }
)


def _uses_structured_concurrency(tree: ast.AST, source: str) -> bool:
    """Report whether the module uses a trio/anyio-only concurrency primitive.

    trio's and anyio's own modules import their runtime relatively, so the
    import check cannot see it; the primitives they use are the visible proof.

    A name can only be referenced if it is spelled in the text, so the substring
    test gates the traversal without narrowing what qualifies.

    Returns:
        True when a trio/anyio-only name appears anywhere in the module.

    """
    if not any(name in source for name in _STRUCTURED_CONCURRENCY_NAMES):
        return False
    return any(
        node.id in _STRUCTURED_CONCURRENCY_NAMES
        if isinstance(node, ast.Name)
        else node.attr in _STRUCTURED_CONCURRENCY_NAMES
        for node in nodes(tree, ast.Name, ast.Attribute)
    )


def _names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    return {n.id for n in walk(node) if isinstance(n, ast.Name)}


def _reads_any(node: ast.AST, names: set[str]) -> bool:
    """Report whether `node`'s subtree reads any name in `names`.

    Returns:
        True on the first matching `Name`, without collecting the rest.

    """
    return any(isinstance(n, ast.Name) and n.id in names for n in walk(node))


def _same_scope_awaits(node: ast.AST) -> Iterator[ast.Await]:
    """Every `Await` under `node`, NOT descending into nested function/lambda bodies.

    A loop's per-iteration work is only the code that runs in the loop's own
    executable scope. An `await` inside a nested `async def`/`lambda` runs when
    *that* callable is invoked, not per loop iteration, so it must not make the
    loop look like a gatherable map.

    Yields:
        The same-scope `Await` descendants of `node`, `node` itself included.

    """
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Await):
            yield current
        # A nested function/lambda body runs in its own scope, not per iteration,
        # so never descend into it.
        elif isinstance(current, _SCOPES):
            continue
        stack.extend(children(current))


def _exempt_awaits(tree: ast.AST, source: str) -> set[int]:
    """`id()`s of every await that is not a per-element map step.

    Returns:
        The union of the yield-streamed and loop-carried exempt awaits.

    """
    return _yield_exempt_awaits(tree, source) | _loop_carried_awaits(tree)


def _loop_carried_awaits(tree: ast.AST) -> set[int]:
    """`id()`s of awaits whose result feeds the next iteration through the same name.

    `value = await function(value, element)` is a fold: the awaited call reads
    the very name the assignment rebinds, so iteration N+1 cannot start before
    N finishes and `gather` cannot express it.

    Returns:
        The `id()`s of the loop-carried awaits.

    """
    exempt: set[int] = set()
    for node in nodes(tree, ast.Assign):
        # An assignment's *value* cannot contain another assignment, so each
        # await has at most one enclosing assignment to be carried by. Awaits
        # are collected before the targets so an await-free value — the common
        # case — costs nothing beyond the scan it needs anyway.
        awaits = list(_same_scope_awaits(node.value))
        if not awaits:
            continue
        targets = {name for target in node.targets for name in _names(target)}
        exempt.update(id(inner) for inner in awaits if _reads_any(inner, targets))
    return exempt


def _yield_exempt_awaits(tree: ast.AST, source: str) -> set[int]:
    """`id()`s of awaits that are the value yielded by an async generator.

    `for x in xs: yield await fetch(x)` streams results one at a time; the yield
    imposes an inherent order, so it is not a gatherable map. Awaits reachable
    from a `yield` value (without crossing a nested scope) are exempt.

    A `Yield` node requires the `yield` keyword in the text, so the substring
    test gates the traversal without narrowing what qualifies.

    Returns:
        The `id()`s of the yield-exempt awaits.

    """
    if "yield" not in source:
        return set()
    return {
        id(inner)
        for yield_node in nodes(tree, ast.Yield)
        if yield_node.value is not None
        for inner in _same_scope_awaits(yield_node.value)
    }


def _is_gather_antipattern(node: ast.For, exempt: set[int]) -> bool:
    """Report whether `node` is `for x in xs: <straight-line body awaiting a call that uses x>`.

    Returns:
        True when the loop is a gatherable-map antipattern.

    """
    if any(isinstance(stmt, _CONTROL_FLOW) for stmt in node.body):
        return False
    targets = _names(node.target)
    return any(
        id(inner) not in exempt and _reads_any(inner, targets)
        for stmt in node.body
        for inner in _same_scope_awaits(stmt)
    )


class _SequentialAwaitVisitor(ast.NodeVisitor):
    """Single O(n) pass: flag the first per-iteration `await` of each loop.

    Maintains a stack of enclosing loops within the current function. The stack
    resets at function boundaries so a loop in an outer function never claims an
    `await` in a nested one. Each loop is flagged at most once. A loop's
    once-evaluated iterable is excluded (see module comment).
    """

    def __init__(self, exempt: set[int]) -> None:
        super().__init__()
        self._exempt: set[int] = exempt
        self._loops: list[ast.AST] = []
        self._flagged: set[int] = set()
        self.hits: list[ast.Await] = []

    def _flag_if_in_loop(self, node: ast.Await) -> None:
        if id(node) in self._exempt:
            return
        if self._loops:
            loop = self._loops[-1]
            if id(loop) not in self._flagged:
                self._flagged.add(id(loop))
                self.hits.append(node)

    def visit_For(self, node: ast.For) -> None:
        # `<iter>` runs once in the enclosing scope; visit it before entering.
        self.visit(node.iter)
        # Only a straight-line per-element-await body is the gather antipattern;
        # control-flow bodies (conditional/ordered) are not pushed, so awaits in
        # them are not flagged for this loop.
        antipattern = _is_gather_antipattern(node, self._exempt)
        if antipattern:
            self._loops.append(node)
        self.visit(node.target)
        for stmt in (*node.body, *node.orelse):
            self.visit(stmt)
        if antipattern:
            self._loops.pop()

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
        elements: tuple[ast.expr, ...],
    ) -> None:
        gens = node.generators
        # Outermost iterable is evaluated once in the enclosing scope.
        self.visit(gens[0].iter)
        self._loops.append(node)
        for elt in elements:
            self.visit(elt)
        self.visit(gens[0].target)
        for cond in gens[0].ifs:
            self.visit(cond)
        # Later generators iterate per element of the preceding one.
        for gen in gens[1:]:
            self.visit(gen.iter)
            self.visit(gen.target)
            for cond in gen.ifs:
                self.visit(cond)
        self._loops.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, (node.key, node.value))

    @override
    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _SCOPES):
            saved = self._loops
            self._loops = []
            super().generic_visit(node)
            self._loops = saved
        elif isinstance(node, ast.Await):
            self._flag_if_in_loop(node)
            super().generic_visit(node)
        else:
            super().generic_visit(node)
