from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TYPING = frozenset({"typing", "typing_extensions"})
_GETATTR_ARITIES = frozenset({2, 3})
_MAX_LITERAL_DEPTH = 12
_CAST_LENGTH = len("cast")
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


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
    return not _type_parameter_shadowed(name, call.func, provenance) and all(
        name not in provenance.bindings.get(scope, {}) for scope in _lexical_scopes(call.func, provenance)
    )


def _lexical_scopes(node: ast.AST, provenance: ResourceProvenance) -> Iterator[ast.AST]:
    scope = _evaluation_scope(node, provenance)
    immediate = True
    while scope is not None:
        # Ordinary nested code blocks do not capture class locals.
        if immediate or not isinstance(scope, ast.ClassDef):
            yield scope
        immediate = False
        scope = _evaluation_scope(scope, provenance)


def _evaluation_scope(node: ast.AST, provenance: ResourceProvenance) -> ast.AST | None:
    scope = provenance.scope(node)
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and _owner_annotation(
        node, scope, provenance
    ):
        node, scope = scope, provenance.scope(scope)
    while isinstance(scope, _COMPREHENSIONS):
        iterable = scope.generators[0].iter
        if iterable is not node and not provenance.contains(iterable, node):
            break
        # A comprehension's first iterable is evaluated in the enclosing scope.
        node, scope = scope, provenance.scope(scope)
    return scope


def _owner_annotation(
    node: ast.AST, owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, provenance: ResourceProvenance
) -> bool:
    if any(parameter is node or provenance.contains(parameter, node) for parameter in owner.type_params):
        return True
    return isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) and _function_annotation(node, owner, provenance)


def _function_annotation(
    node: ast.AST, function: ast.FunctionDef | ast.AsyncFunctionDef, provenance: ResourceProvenance
) -> bool:
    current = node
    while (parent := provenance.context.parents.get(current)) is not None:
        if (parent is function and current is function.returns) or (
            isinstance(parent, ast.arg) and current is parent.annotation
        ):
            return True
        if parent is function:
            break
        current = parent
    return False


def _type_parameter_shadowed(name: str, node: ast.AST, provenance: ResourceProvenance) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if (
            isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.TypeAlias)
            and any(
                isinstance(parameter, ast.TypeVar | ast.TypeVarTuple | ast.ParamSpec) and parameter.name == name
                for parameter in current.type_params
            )
            and not _outside_parameter_scope(node, current, provenance)
            and not _local_binding_overrides(name, node, current, provenance)
        ):
            return True
        current = provenance.context.parents.get(current)
    return False


def _outside_parameter_scope(
    node: ast.AST,
    owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.TypeAlias,
    provenance: ResourceProvenance,
) -> bool:
    outside = [] if isinstance(owner, ast.TypeAlias) else list(owner.decorator_list)
    if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        outside.extend(owner.args.defaults)
        outside.extend(value for value in owner.args.kw_defaults if value is not None)
    # Defaults and decorators evaluate in the enclosing scope.
    return any(value is node or provenance.contains(value, node) for value in outside)


def _local_binding_overrides(name: str, node: ast.AST, owner: ast.AST, provenance: ResourceProvenance) -> bool:
    for scope in _lexical_scopes(node, provenance):
        if scope is not owner and not provenance.contains(owner, scope):
            return False
        if name in provenance.bindings.get(scope, {}):
            return True
    return False


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
    binding = _name_binding(node, provenance)
    if not (
        isinstance(binding, ast.alias)
        and isinstance(provenance.context.parents.get(binding), ast.Import)
        and binding.name in _TYPING
    ):
        return None
    for read in provenance.reads.get(node.id, ()):
        if _name_binding(read, provenance) is not binding:
            continue
        parent = provenance.context.parents.get(read)
        if isinstance(parent, ast.Attribute) and parent.value is read:
            continue
        if id(read) in receivers:
            continue
        return None
    return binding.name


def _name_binding(node: ast.Name, provenance: ResourceProvenance) -> ast.AST | None:
    if _type_parameter_shadowed(node.id, node, provenance):
        return None
    for scope in _lexical_scopes(node, provenance):
        if bindings := provenance.bindings.get(scope, {}).get(node.id):
            return provenance.binding(node.id, bindings[0])
    return None
