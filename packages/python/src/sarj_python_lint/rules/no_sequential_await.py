"""SARJ001: detect `for x in xs: await f(x)` patterns.

Sequential `await` in a for-loop serializes I/O that could be parallelized
with `asyncio.gather([f(x) for x in xs])`. The performance gap is often 10-100x
for network-bound work (HTTP, DB queries, LLM calls).

References:
- https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently
"""

from __future__ import annotations

import ast
from pathlib import Path

from sarj_python_lint.rule_base import Diagnostic, Rule


class LoopBodyAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.has_await = False
        self.has_early_exit = False
        self.first_await_node = None

    def visit_For(self, node):
        pass  # Do not traverse into nested loops

    def visit_AsyncFor(self, node):
        pass

    def visit_While(self, node):
        pass

    def visit_FunctionDef(self, node):
        pass

    def visit_AsyncFunctionDef(self, node):
        pass

    def visit_ClassDef(self, node):
        pass

    def visit_Break(self, node):
        self.has_early_exit = True

    def visit_Return(self, node):
        self.has_early_exit = True

    def visit_Await(self, node):
        is_allowed = False
        if isinstance(node.value, ast.Call):
            func = node.value.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in ("gather", "sleep"):
                is_allowed = True
                
        if not is_allowed:
            self.has_await = True
            if not self.first_await_node:
                self.first_await_node = node
                
        self.generic_visit(node)


class NoSequentialAwait(Rule):
    """Sequential await calls in a loop that could be parallelized."""

    id = "no-sequential-await"
    code = "SARJ001"
    description = "Sequential `await` in a for-loop — prefer asyncio.gather."

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return []
            
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
                
            analyzer = LoopBodyAnalyzer()
            for stmt in node.body:
                analyzer.visit(stmt)
                
            if analyzer.has_await and not analyzer.has_early_exit:
                child = analyzer.first_await_node
                diags.append(
                    Diagnostic(
                        path=path,
                        line=child.lineno,
                        col=child.col_offset + 1,
                        code=self.code,
                        message=(
                            "Sequential `await` inside `for` — prefer "
                            "`asyncio.gather([f(x) for x in xs])`."
                        ),
                    )
                )
                
        return diags
