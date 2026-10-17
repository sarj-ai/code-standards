from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_NAMESPACE_RETURNING_FUNCTIONS = frozenset({"__lazy_import__"})
_BUILTIN_NAMESPACE_FUNCTIONS = frozenset(
    {
        "__build_class__",
        "__import__",
        "__lazy_import__",
        "abs",
        "aiter",
        "all",
        "anext",
        "any",
        "ascii",
        "bin",
        "breakpoint",
        "callable",
        "chr",
        "compile",
        "delattr",
        "dir",
        "divmod",
        "eval",
        "exec",
        "format",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "hex",
        "id",
        "input",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "locals",
        "max",
        "min",
        "next",
        "oct",
        "ord",
        "pow",
        "print",
        "repr",
        "round",
        "setattr",
        "sorted",
        "sum",
        "vars",
    }
)


def native_namespace_capability_escapes(context: PythonFileContext) -> bool:
    function_names = _possible_native_function_names(context)
    namespace_function_names = _possible_native_function_names(context, symbols=_NAMESPACE_RETURNING_FUNCTIONS)
    module_names = frozenset(
        alias.asname or alias.name
        for node in context.nodes(ast.Import)
        for alias in node.names
        if alias.name == "builtins"
    )
    for node in context.nodes(ast.Name, ast.Attribute):
        if isinstance(node, ast.Attribute) and (
            not isinstance(node.value, ast.Name) or node.attr not in _BUILTIN_NAMESPACE_FUNCTIONS
        ):
            continue
        if not isinstance(node.ctx, ast.Load) or not _possible_native_function(node, function_names, module_names):
            continue
        parent = context.parents.get(node)
        if (
            not isinstance(parent, ast.Call)
            or parent.func is not node
            or _namespace_returning_function(node, namespace_function_names)
        ):
            return True
    return False


def _possible_native_function_names(
    context: PythonFileContext, *, symbols: frozenset[str] = _BUILTIN_NAMESPACE_FUNCTIONS
) -> frozenset[str]:
    return symbols | frozenset(
        alias.asname or alias.name
        for node in context.nodes(ast.ImportFrom)
        if node.level == 0 and node.module == "builtins"
        for alias in node.names
        if alias.name in symbols
    )


def _namespace_returning_function(node: ast.Name | ast.Attribute, function_names: frozenset[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in function_names
    return node.attr in _NAMESPACE_RETURNING_FUNCTIONS


def _possible_native_function(
    node: ast.Name | ast.Attribute,
    function_names: frozenset[str],
    module_names: frozenset[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in function_names
    return (
        isinstance(node.value, ast.Name) and node.value.id in module_names and node.attr in _BUILTIN_NAMESPACE_FUNCTIONS
    )
