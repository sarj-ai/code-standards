from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sarj_python_lint.rules._imports import ImportIndex


_NAMESPACE_APIS = frozenset({"globals", "locals", "vars", "exec", "eval", "__import__"})
_DYNAMIC_MEMBERS = frozenset(
    {
        "__dict__",
        "__globals__",
        "__code__",
        "__origin__",
        "__args__",
        "__parameters__",
        "__setattr__",
        "__delattr__",
        "__getattribute__",
        "f_globals",
        "f_locals",
        "f_builtins",
    }
)
_MODULE_APIS: Final[dict[str, frozenset[str]]] = {
    "sys": frozenset({"modules", "_getframe"}),
    "inspect": frozenset({"currentframe"}),
    "importlib": frozenset({"import_module"}),
    "builtins": _NAMESPACE_APIS,
}
_RESOLVED_MEMBERS = _NAMESPACE_APIS | {"modules", "import_module"}


def dynamic_namespace_access(
    nodes: Iterable[ast.AST], imports: ImportIndex, parents: Mapping[ast.AST, ast.AST]
) -> bool:
    indexed = tuple(nodes)
    aliases = _namespace_api_aliases(indexed)
    modules = _namespace_module_bindings(indexed)
    return any(_namespace_reference(node, aliases, modules, imports, parents) for node in indexed)


def _namespace_api_aliases(nodes: Iterable[ast.AST]) -> set[str]:
    aliases = set(_NAMESPACE_APIS) | {"__builtins__"}
    for node in nodes:
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or node.module not in _MODULE_APIS:
            continue
        members = _MODULE_APIS[node.module]
        aliases.update(alias.asname or alias.name for alias in node.names if alias.name in members)
    return aliases


def _namespace_module_bindings(nodes: Iterable[ast.AST]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, ast.Import):
            continue
        modules.update({alias.asname or alias.name: alias.name for alias in node.names if alias.name in _MODULE_APIS})
    return modules


def _namespace_reference(
    node: ast.AST,
    aliases: set[str],
    modules: dict[str, str],
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    if isinstance(node, ast.Attribute):
        if node.attr in _DYNAMIC_MEMBERS:
            return True
        if node.attr not in _RESOLVED_MEMBERS:
            return False
        qualified = imports.resolved_qualified_name(node)
        return qualified in {"sys.modules", "importlib.import_module"} or (
            imports.resolved_symbol(node, sources=frozenset({"builtins"})) in _NAMESPACE_APIS
        )
    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
        return False
    if node.id in aliases:
        return True
    module = modules.get(node.id)
    if module is None:
        return False
    parent = parents.get(node)
    return not isinstance(parent, ast.Attribute) or parent.value is not node or parent.attr in _MODULE_APIS[module]
