"""SARJ001 — `for x in xs: await f(x)` gather antipattern.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_sequential_await.py
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
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

# Top-level body statements that signal conditional or ordered logic rather than
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
    """Report whether the module imports a non-asyncio async runtime (trio/anyio)."""
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
    """Report whether the module uses a trio/anyio-only concurrency primitive."""
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
    """Report whether `node`'s subtree reads any name in `names`."""
    return any(isinstance(n, ast.Name) and n.id in names for n in walk(node))


def _same_scope_awaits(node: ast.AST) -> Iterator[ast.Await]:
    """Every `Await` under `node`, NOT descending into nested function/lambda bodies."""
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
    """`id()`s of every await that is not a per-element map step."""
    return _yield_exempt_awaits(tree, source) | _loop_carried_awaits(tree)


def _loop_carried_awaits(tree: ast.AST) -> set[int]:
    """`id()`s of awaits whose result feeds the next iteration through the same name."""
    exempt: set[int] = set()
    for node in nodes(tree, ast.Assign):
        # An assignment's *value* cannot contain another assignment, so each
        awaits = list(_same_scope_awaits(node.value))
        if not awaits:
            continue
        targets = {name for target in node.targets for name in _names(target)}
        exempt.update(id(inner) for inner in awaits if _reads_any(inner, targets))
    return exempt


def _yield_exempt_awaits(tree: ast.AST, source: str) -> set[int]:
    """`id()`s of awaits that are the value yielded by an async generator."""
    if "yield" not in source:
        return set()
    return {
        id(inner)
        for yield_node in nodes(tree, ast.Yield)
        if yield_node.value is not None
        for inner in _same_scope_awaits(yield_node.value)
    }


def _is_gather_antipattern(node: ast.For, exempt: set[int]) -> bool:
    """Report whether `node` is `for x in xs: <straight-line body awaiting a call that uses x>`."""
    if any(isinstance(stmt, _CONTROL_FLOW) for stmt in node.body):
        return False
    targets = _names(node.target)
    return any(
        id(inner) not in exempt and _reads_any(inner, targets)
        for stmt in node.body
        for inner in _same_scope_awaits(stmt)
    )


class _SequentialAwaitVisitor(ast.NodeVisitor):
    """Single O(n) pass: flag the first per-iteration `await` of each loop."""

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
