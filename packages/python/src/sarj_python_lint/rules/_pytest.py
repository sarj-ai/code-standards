from __future__ import annotations

import ast

from sarj_python_lint.rules._ast_index import walk


# The pytest-benchmark fixture: the test measures time, it does not verify.
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
    # Only `*.mark.<name>`, so a `@benchmark.something` helper is not mistaken
    # for a pytest marker.
    parent = target.value
    if isinstance(parent, ast.Attribute) and parent.attr == "mark":
        return target.attr
    return None
