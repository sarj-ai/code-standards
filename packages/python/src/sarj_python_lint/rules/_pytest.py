from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import walk


if TYPE_CHECKING:
    from collections.abc import Iterator


def collected_tests(statements: list[ast.stmt]) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for statement in statements:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if statement.name.startswith("test"):
                yield statement
            case ast.ClassDef() if statement.name.startswith("Test"):
                yield from collected_tests(statement.body)
            case _:
                pass


_BENCHMARK = "benchmark"


def uses_benchmark_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    declared = any(arg.arg == _BENCHMARK for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
    return declared and any(isinstance(child, ast.Name) and child.id == _BENCHMARK for child in walk(node))


def has_benchmark_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_attr(dec) == _BENCHMARK for dec in node.decorator_list)


def _decorator_attr(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if not isinstance(target, ast.Attribute):
        return None
    parent = target.value
    if isinstance(parent, ast.Attribute) and parent.attr == "mark":
        return target.attr
    return None
