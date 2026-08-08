"""SARJ078 — Prefer `Self` type annotation for methods returning instance of enclosing class.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_self_type_annotation.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)


if TYPE_CHECKING:
    from pathlib import Path


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


def _is_classmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if function node is decorated with @classmethod."""
    return any(isinstance(dec, ast.Name) and dec.id == "classmethod" for dec in node.decorator_list)


class PreferSelfTypeAnnotation(Rule):
    id: str = "prefer-self-type-annotation"
    code: str = "SARJ078"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Annotate fluent methods and alternate constructors with `Self`.",
        rationale="`Self` preserves the concrete subclass type, while naming the enclosing class narrows inherited return types incorrectly.",
        remediation="Import `Self` from `typing` and use it as the return annotation.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only methods that directly return `self` or classmethods that directly return `cls(...)` are analyzed.",
            "Annotations naming other classes and methods without a return annotation are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="enclosing-class-return",
                title="Fluent method names its enclosing class",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        "class Builder:\n"
                        '    def set_name(self, name: str) -> "Builder":\n'
                        "        self.name = name\n"
                        "        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="self-return-annotation",
                title="Fluent method preserves subclass type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/builder.py",
                        "from typing import Self\n\n"
                        "class Builder:\n"
                        "    def set_name(self, name: str) -> Self:\n"
                        "        self.name = name\n"
                        "        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/builder.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
                                f"Method `{node.name}` returns an instance of its class but annotates it as `{matched_name}` — "
                                f"use `Self` (from `typing`) instead."
                            ),
                        )
                    )

        visitor = ClassVisitor()
        visitor.visit(tree)

        return sorted(diags, key=lambda d: (d.line, d.col))
