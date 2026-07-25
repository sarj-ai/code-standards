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

References:
- https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


def _is_test_path(path: Path) -> bool:
    name = path.name
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in {"tests", "test"} for part in path.parts)


class NoSequentialAwait(Rule):
    """Sequential await calls in a loop that could be parallelized."""

    id: str = "no-sequential-await"
    code: str = "SARJ001"
    description: str = "Sequential `await` in a for-loop — prefer asyncio.gather."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _imports_non_asyncio_runtime(tree):
            return []
        visitor = _SequentialAwaitVisitor(_yield_exempt_awaits(tree))
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


def _imports_non_asyncio_runtime(tree: ast.AST) -> bool:
    """Report whether the module imports a non-asyncio async runtime (trio/anyio).

    `asyncio.gather` does not exist under those runtimes, and their structured
    concurrency makes sequential awaits in a loop the deliberate norm.

    Returns:
        True when trio or anyio is imported anywhere in the module.

    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in _NON_ASYNCIO_RUNTIMES for alias in node.names):
                return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.split(".")[0] in _NON_ASYNCIO_RUNTIMES
        ):
            return True
    return False


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _walk_same_scope(node: ast.AST) -> list[ast.AST]:
    """`node` and descendants, NOT descending into nested function/lambda bodies.

    A loop's per-iteration work is only the code that runs in the loop's own
    executable scope. An `await` inside a nested `async def`/`lambda` runs when
    *that* callable is invoked, not per loop iteration, so it must not make the
    loop look like a gatherable map.

    Returns:
        `node` and its same-scope descendants.

    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        out.append(current)
        # A nested function/lambda body runs in its own scope, not per iteration.
        # Record the def node itself but never descend into it.
        if isinstance(current, _SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(current))
    return out


def _yield_exempt_awaits(tree: ast.AST) -> set[int]:
    """`id()`s of awaits that are the value yielded by an async generator.

    `for x in xs: yield await fetch(x)` streams results one at a time; the yield
    imposes an inherent order, so it is not a gatherable map. Awaits reachable
    from a `yield` value (without crossing a nested scope) are exempt.

    Returns:
        The `id()`s of the yield-exempt awaits.

    """
    exempt: set[int] = set()
    for yield_node in ast.walk(tree):
        if not isinstance(yield_node, ast.Yield) or yield_node.value is None:
            continue
        for inner in _walk_same_scope(yield_node.value):
            if isinstance(inner, ast.Await):
                exempt.add(id(inner))
    return exempt


def _is_gather_antipattern(node: ast.For, yield_exempt: set[int]) -> bool:
    """Report whether `node` is `for x in xs: <straight-line body awaiting a call that uses x>`.

    Returns:
        True when the loop is a gatherable-map antipattern.

    """
    if any(isinstance(stmt, _CONTROL_FLOW) for stmt in node.body):
        return False
    targets = _names(node.target)
    for stmt in node.body:
        for inner in _walk_same_scope(stmt):
            if isinstance(inner, ast.Await) and id(inner) not in yield_exempt and _names(inner) & targets:
                return True
    return False


class _SequentialAwaitVisitor(ast.NodeVisitor):
    """Single O(n) pass: flag the first per-iteration `await` of each loop.

    Maintains a stack of enclosing loops within the current function. The stack
    resets at function boundaries so a loop in an outer function never claims an
    `await` in a nested one. Each loop is flagged at most once. A loop's
    once-evaluated iterable is excluded (see module comment).
    """

    def __init__(self, yield_exempt: set[int]) -> None:
        super().__init__()
        self._yield_exempt = yield_exempt
        self._loops: list[ast.AST] = []
        self._flagged: set[int] = set()
        self.hits: list[ast.Await] = []

    def _flag_if_in_loop(self, node: ast.Await) -> None:
        if id(node) in self._yield_exempt:
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
        antipattern = _is_gather_antipattern(node, self._yield_exempt)
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
