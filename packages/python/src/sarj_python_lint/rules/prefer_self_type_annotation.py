"""SARJ078 — Prefer `Self` type annotation for methods returning instance of enclosing class.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_self_type_annotation.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ078.md
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


def _is_classmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if function node is decorated with @classmethod."""
    return any(isinstance(dec, ast.Name) and dec.id == "classmethod" for dec in node.decorator_list)


def _is_return_self_or_cls(outer_func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if node directly returns `self` or `cls(...)` (excluding inner functions/classes)."""
    target_name = "cls" if _is_classmethod(outer_func) else "self"

    class ReturnVisitor(ast.NodeVisitor):
        found: bool = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            pass

        def visit_Return(self, node: ast.Return) -> None:
            val = node.value
            if (isinstance(val, ast.Name) and val.id == target_name) or (
                isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == target_name
            ):
                self.found = True
            self.generic_visit(node)

    visitor = ReturnVisitor()
    visitor.visit(outer_func)
    return visitor.found


class PreferSelfTypeAnnotation(Rule):
    id: str = "prefer-self-type-annotation"
    code: str = "SARJ078"
    has_evidence: bool = True
    description: str = (
        "prefer `Self` return type annotation instead of explicit class name "
        "or string literal reference when returning self/instance."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        class ClassVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.class_stack: list[str] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.class_stack.append(node.name)
                self.generic_visit(node)
                self.class_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._check_func(node)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._check_func(node)
                self.generic_visit(node)

            def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                if not self.class_stack:
                    return
                current_class = self.class_stack[-1]
                returns = node.returns
                if returns is None:
                    return

                matched_name: str | None = None
                if (
                    isinstance(returns, ast.Constant)
                    and isinstance(returns.value, str)
                    and returns.value == current_class
                ):
                    matched_name = f'"{current_class}"'
                elif isinstance(returns, ast.Name) and returns.id == current_class:
                    matched_name = current_class

                if (
                    matched_name
                    and _is_return_self_or_cls(node)
                    and not is_suppressed(source_lines, returns.lineno, "SARJ078")
                ):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=returns.lineno,
                            col=returns.col_offset + 1,
                            code="SARJ078",
                            message=(
                                f"Method `{node.name}` returns `self` but annotates return as `{matched_name}` — "
                                f"use `Self` (from `typing`) instead."
                            ),
                        )
                    )

        visitor = ClassVisitor()
        visitor.visit(tree)

        return sorted(diags, key=lambda d: (d.line, d.col))
