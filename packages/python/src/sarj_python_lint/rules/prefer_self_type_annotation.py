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
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


def _is_return_self_or_cls(outer_func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if _block_can_fall_through(outer_func.body):
        return False
    target_name = "cls" if _is_classmethod(outer_func) else "self"

    class ReturnVisitor(ast.NodeVisitor):
        returns: list[ast.expr | None]

        def __init__(self) -> None:
            self.returns = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is outer_func:
                self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            pass

        def visit_Return(self, node: ast.Return) -> None:
            self.returns.append(node.value)

    visitor = ReturnVisitor()
    visitor.visit(outer_func)
    if not visitor.returns:
        return False

    def preserves_type(value: ast.expr | None) -> bool:
        if target_name == "self":
            return isinstance(value, ast.Name) and value.id == "self"
        if not isinstance(value, ast.Call):
            return False
        if isinstance(value.func, ast.Name):
            return value.func.id == "cls"
        return (
            isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "cls"
            and value.func.attr in {"model_construct", "model_validate"}
        )

    return all(preserves_type(value) for value in visitor.returns)


def _block_can_fall_through(statements: list[ast.stmt]) -> bool:
    if not statements:
        return True
    match statements[-1]:
        case ast.Return() | ast.Raise():
            return False
        case ast.If(body=body, orelse=orelse):
            return _block_can_fall_through(body) or _block_can_fall_through(orelse)
        case _:
            return True


def _is_classmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
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
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        class ClassVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.class_stack: list[ast.ClassDef] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.class_stack.append(node)
                for child in node.body:
                    if isinstance(child, ast.ClassDef):
                        self.visit(child)
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._check_func(child)
                self.class_stack.pop()

            def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                if not self.class_stack:
                    return
                if _ruff_owns_self_annotation(node.name):
                    return
                current_class = self.class_stack[-1]
                if _is_metaclass(current_class):
                    return
                accepted_names = {current_class.name} | {
                    name for base in current_class.bases if (name := _trailing_annotation_name(base)) is not None
                }
                returns = node.returns
                if returns is None:
                    return

                matched_name: str | None = None
                if (
                    isinstance(returns, ast.Constant)
                    and isinstance(returns.value, str)
                    and returns.value in accepted_names
                ):
                    matched_name = f'"{returns.value}"'
                elif isinstance(returns, ast.Name) and returns.id in accepted_names:
                    matched_name = returns.id

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


def _is_metaclass(node: ast.ClassDef) -> bool:
    return any(_trailing_annotation_name(base) in {"type", "ABCMeta"} for base in node.bases)


def _trailing_annotation_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _trailing_annotation_name(value)
        case _:
            return None


_RUFF_SELF_DUNDERS = frozenset({"__aenter__", "__enter__", "__new__"})
_INPLACE_DUNDERS = frozenset(
    {
        "__iadd__",
        "__iand__",
        "__ifloordiv__",
        "__ilshift__",
        "__imatmul__",
        "__imod__",
        "__imul__",
        "__ior__",
        "__ipow__",
        "__irshift__",
        "__isub__",
        "__itruediv__",
        "__ixor__",
    }
)


def _ruff_owns_self_annotation(name: str) -> bool:
    return name in _RUFF_SELF_DUNDERS or name in _INPLACE_DUNDERS
