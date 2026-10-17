from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING

from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._native_namespace_capability import native_namespace_capability_escapes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_NAMESPACE_IMPORT_CAPABILITIES = frozenset(
    {"__dict__", "__builtins__", "__getattribute__", "__setattr__", "__delattr__"}
)


def builtin_guard_symbol(node: ast.expr | None, imports: ImportIndex, builtin_symbols: frozenset[str]) -> str | None:
    if node is None:
        return None
    symbol = imports.resolved_symbol(node, sources=frozenset({"builtins"}))
    if symbol in builtin_symbols:
        return symbol
    if isinstance(node, ast.Name) and node.id in builtin_symbols and imports.builtin_is_unshadowed(node.id):
        return node.id
    return None


def unique_guard_function_names(context: PythonFileContext) -> frozenset[str]:
    if context.tree is None:
        return frozenset()
    counts: Counter[str] = Counter()
    pending: list[ast.AST] = list(context.tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts[node.name] += 1
        elif not isinstance(node, (ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(node))
    return frozenset(name for name, count in counts.items() if count == 1)


def guard_symbols_ambiguous(
    context: PythonFileContext,
    builtin_symbols: frozenset[str],
    *,
    typing_symbols: frozenset[str] = frozenset({"TypeGuard", "TypeIs"}),
) -> bool:
    namespace_names = _namespace_import_names(context)
    if _namespace_escapes(context, namespace_names):
        return True
    mutation_targets = (
        {f"builtins.{symbol}" for symbol in builtin_symbols}
        | {f"{module}.{symbol}" for module in TYPING_SOURCES for symbol in typing_symbols}
        | {f"{module}.__class__" for module in TYPING_SOURCES | {"builtins"}}
    )
    sensitive_names = (
        builtin_symbols
        | namespace_names
        | {
            name
            for name, target in context.module_imports.bindings.items()
            if target.module in TYPING_SOURCES | {"builtins"}
            and (target.symbol is None or target.symbol in builtin_symbols | typing_symbols)
        }
    )
    return any(
        _ambiguous_node(node, context, mutation_targets, sensitive_names)
        for node in context.nodes(
            ast.Import,
            ast.ImportFrom,
            ast.Attribute,
            ast.ExceptHandler,
            ast.MatchAs,
            ast.MatchStar,
            ast.MatchMapping,
            ast.NamedExpr,
        )
    )


def _namespace_import_names(context: PythonFileContext) -> frozenset[str]:
    return frozenset(
        alias.asname or alias.name
        for node in context.nodes(ast.Import)
        for alias in node.names
        if alias.name in TYPING_SOURCES | {"builtins"}
    )


def _namespace_escapes(context: PythonFileContext, namespace_names: frozenset[str]) -> bool:
    if context.dynamic_namespace or any(node.id == "__builtins__" for node in context.nodes(ast.Name)):
        return True
    if any(
        node.level == 0
        and node.module in TYPING_SOURCES | {"builtins"}
        and any(alias.name in _NAMESPACE_IMPORT_CAPABILITIES for alias in node.names)
        for node in context.nodes(ast.ImportFrom)
    ):
        return True
    if native_namespace_capability_escapes(context):
        return True
    for name in context.nodes(ast.Name):
        if name.id not in namespace_names:
            continue
        parent = context.parents.get(name)
        if not isinstance(parent, ast.Attribute) or parent.value is not name or parent.attr == "__dict__":
            return True
    return False


def _ambiguous_node(
    node: ast.AST, context: PythonFileContext, mutation_targets: set[str], sensitive_names: frozenset[str]
) -> bool:
    match node:
        case ast.Import() | ast.ImportFrom():
            return _ambiguous_import(node, context.module_imports, sensitive_names)
        case ast.Attribute(ctx=(ast.Store() | ast.Del())):
            return context.module_imports.resolved_qualified_name(node) in mutation_targets
        case (
            ast.ExceptHandler(name=name)
            | ast.MatchAs(name=name)
            | ast.MatchStar(name=name)
            | ast.MatchMapping(rest=name)
            | ast.NamedExpr(target=ast.Name(id=name))
        ):
            return name in sensitive_names
        case _:
            return False


def _ambiguous_import(node: ast.Import | ast.ImportFrom, imports: ImportIndex, sensitive_names: frozenset[str]) -> bool:
    if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
        return True
    for alias in node.names:
        name = alias.asname or alias.name.partition(".")[0]
        if name not in sensitive_names:
            continue
        if not _preserves_canonical_import(node, alias, imports):
            return True
    return False


def _preserves_canonical_import(node: ast.Import | ast.ImportFrom, alias: ast.alias, imports: ImportIndex) -> bool:
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return False
        module, symbol = node.module, alias.name
    else:
        module, symbol = alias.name, None
    name = alias.asname or alias.name.partition(".")[0]
    target = imports.bindings.get(name)
    if target is None:
        return module == "builtins" and symbol == name
    return target.module == module and target.symbol == symbol
