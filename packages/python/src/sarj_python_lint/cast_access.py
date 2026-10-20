from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from pathlib import Path


_TYPING = frozenset({"typing", "typing_extensions"})
_GETATTR_ARITIES = frozenset({2, 3})


@dataclass(frozen=True, slots=True)
class CastAccess:
    node: ast.Call | ast.ImportFrom
    qualified_api: str
    kind: Literal["wildcard", "reflection"]


def indirect_typing_cast_accesses(path: Path, source: str) -> tuple[CastAccess, ...]:
    context = PythonFileContext(path, source)
    if "*" not in source and "getattr" not in context.symbol_source:
        return ()
    if context.tree is None:
        return ()
    accesses = [
        CastAccess(node, f"{node.module}.cast", "wildcard")
        for node in context.nodes(ast.ImportFrom)
        if node.level == 0 and node.module in _TYPING and any(alias.name == "*" for alias in node.names)
    ]
    provenance = ResourceProvenance(context, require_static_namespace=True)
    if provenance.wildcard or provenance.dynamic_namespace or not provenance.builtin_namespace_untouched:
        return tuple(accesses)
    for call in context.nodes(ast.Call):
        if not _getattr_call(call, provenance):
            continue
        module = _typing_receiver(call.args[0], provenance)
        if module is not None:
            accesses.append(CastAccess(call, f"{module}.cast", "reflection"))
    return tuple(sorted(accesses, key=lambda access: (access.node.lineno, access.node.col_offset)))


def _getattr_call(call: ast.Call, provenance: ResourceProvenance) -> bool:
    if not (
        isinstance(call.func, ast.Name)
        and call.func.id == "getattr"
        and len(call.args) in _GETATTR_ARITIES
        and not call.keywords
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "cast"
    ):
        return False
    scope = provenance.scope(call.func)
    while scope is not None:
        if "getattr" in provenance.bindings.get(scope, {}):
            return False
        scope = provenance.scope(scope)
    return True


def _typing_receiver(node: ast.expr, provenance: ResourceProvenance) -> str | None:
    if not isinstance(node, ast.Name) or node.id in provenance.mutated | provenance.external_bindings:
        return None
    binding = provenance.binding(node.id, node)
    if not (
        isinstance(binding, ast.alias)
        and isinstance(provenance.context.parents.get(binding), ast.Import)
        and binding.name in _TYPING
    ):
        return None
    for read in provenance.reads.get(node.id, ()):
        if provenance.binding(read.id, read) is not binding:
            continue
        parent = provenance.context.parents.get(read)
        if isinstance(parent, ast.Attribute) and parent.value is read:
            continue
        if isinstance(parent, ast.Call) and _getattr_call(parent, provenance) and parent.args[0] is read:
            continue
        return None
    return binding.name
