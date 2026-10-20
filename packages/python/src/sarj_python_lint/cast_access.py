from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from pathlib import Path


_TYPING = frozenset({"typing", "typing_extensions"})
_GETATTR_ARITIES = frozenset({2, 3})
_MAX_LITERAL_DEPTH = 12
_CAST_LENGTH = len("cast")


@dataclass(frozen=True, slots=True)
class CastAccess:
    node: ast.Call | ast.Subscript | ast.ImportFrom
    qualified_api: str
    kind: Literal["wildcard", "reflection"]


def indirect_typing_cast_accesses(path: Path, source: str) -> tuple[CastAccess, ...]:
    context = PythonFileContext(path, source)
    if not any(marker in context.symbol_source for marker in ("*", "getattr", "__dict__", "vars", "__getattribute__")):
        return ()
    if context.tree is None:
        return ()
    accesses = [
        CastAccess(node, f"{node.module}.cast", "wildcard")
        for node in context.nodes(ast.ImportFrom)
        if node.level == 0 and node.module in _TYPING and any(alias.name == "*" for alias in node.names)
    ]
    accesses.extend(_reflection_accesses(context))
    return tuple(sorted(accesses, key=lambda access: (access.node.lineno, access.node.col_offset)))


def _reflection_accesses(context: PythonFileContext) -> list[CastAccess]:
    provenance = ResourceProvenance(context)
    candidates = [
        (node, receiver)
        for node in context.nodes(ast.Call, ast.Subscript)
        if (receiver := _cast_receiver(node, provenance)) is not None
    ]
    if not candidates:
        return []
    receivers = {id(receiver) for _, receiver in candidates}
    proven = [
        (node, module)
        for node, receiver in candidates
        if (module := _typing_receiver(receiver, provenance, receivers)) is not None
    ]
    safe_reflection = {id(carrier) for node, _ in proven if (carrier := _reflection_carrier(node)) is not None}
    namespace_hazard = dynamic_namespace_access(
        (node for node in context.nodes(ast.AST) if id(node) not in safe_reflection), context.imports, context.parents
    )
    if provenance.wildcard or namespace_hazard or not provenance.builtin_namespace_untouched:
        return []
    return [CastAccess(node, f"{module}.cast", "reflection") for node, module in proven]


def _cast_receiver(node: ast.Call | ast.Subscript, provenance: ResourceProvenance) -> ast.Name | None:
    if isinstance(node, ast.Call):
        return _call_receiver(node, provenance)
    if not isinstance(node.ctx, ast.Load) or _static_text(node.slice) != "cast":
        return None
    namespace = node.value
    if isinstance(namespace, ast.Attribute) and namespace.attr == "__dict__" and isinstance(namespace.value, ast.Name):
        return namespace.value
    if isinstance(namespace, ast.Call) and len(namespace.args) == 1 and _builtin_call(namespace, "vars", provenance):
        return namespace.args[0] if isinstance(namespace.args[0], ast.Name) else None
    return None


def _call_receiver(node: ast.Call, provenance: ResourceProvenance) -> ast.Name | None:
    if (
        len(node.args) in _GETATTR_ARITIES
        and _builtin_call(node, "getattr", provenance)
        and _static_text(node.args[1]) == "cast"
    ):
        return node.args[0] if isinstance(node.args[0], ast.Name) else None
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "__getattribute__"
        and len(node.args) == 1
        and not node.keywords
        and _static_text(node.args[0]) == "cast"
    ):
        return node.func.value if isinstance(node.func.value, ast.Name) else None
    return None


def _builtin_call(call: ast.Call, name: str, provenance: ResourceProvenance) -> bool:
    if not isinstance(call.func, ast.Name) or call.func.id != name or call.keywords:
        return False
    scope = provenance.scope(call.func)
    while scope is not None:
        if name in provenance.bindings.get(scope, {}):
            return False
        scope = provenance.scope(scope)
    return True


def _static_text(node: ast.expr, depth: int = 0) -> str | None:
    # Evaluate only bounded, side-effect-free string syntax, never runtime code.
    if depth > _MAX_LITERAL_DEPTH:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if len(node.value) <= _CAST_LENGTH else None
    if isinstance(node, ast.JoinedStr):
        # Parsing adjacent static f-strings folds them into one Constant.
        return _static_text(node.values[0], depth + 1) if len(node.values) == 1 else None
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
        return None
    left, right = _static_text(node.left, depth + 1), _static_text(node.right, depth + 1)
    if left is None or right is None:
        return None
    text = left + right
    return text if len(text) <= _CAST_LENGTH else None


def _reflection_carrier(node: ast.Call | ast.Subscript) -> ast.AST | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func
    if isinstance(node, ast.Subscript):
        return node.value.func if isinstance(node.value, ast.Call) else node.value
    return None


def _typing_receiver(node: ast.Name, provenance: ResourceProvenance, receivers: set[int]) -> str | None:
    if node.id in provenance.mutated | provenance.external_bindings:
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
        if id(read) in receivers:
            continue
        return None
    return binding.name
