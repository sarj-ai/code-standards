from __future__ import annotations

import ast
from dataclasses import dataclass
import keyword
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sarj_python_lint._file_context import PythonFileContext


_FUNCTION_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
_NATIVE_NAMES = frozenset(
    {
        "__import__",
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "compile",
        "delattr",
        "dict",
        "float",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "int",
        "list",
        "locals",
        "object",
        "range",
        "set",
        "setattr",
        "str",
        "tuple",
    }
)

_RUFF_BANNED_API = frozenset({"locals", "globals", "compile", "__import__", "getattr", "hasattr", "delattr"})


@dataclass(frozen=True, slots=True)
class BuiltinReference:
    node: ast.expr | ast.alias
    name: str


@final
class RuntimeNames:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.inventory = context.binding_inventory

    def builtin(self, node: ast.Name) -> bool:
        return not self.inventory.wildcard and self._binding_scope(node.id, node) is None

    def qualified(self, expression: ast.expr) -> str | None:
        if self.inventory.wildcard:
            return None
        return self._qualified(expression, frozenset(), assignments=True)

    def imported_qualified(self, expression: ast.expr) -> str | None:
        if self.inventory.wildcard:
            return None
        return self._qualified(expression, frozenset(), assignments=False)

    def assigned_value(self, node: ast.Name) -> ast.expr | None:
        scope = self._binding_scope(node.id, node)
        declarations = self.inventory.bindings.get(scope, {}).get(node.id, ())
        stable = tuple(item for item in declarations if not self._inplace_target(item))
        if len(stable) != 1 or not isinstance(stable[0], ast.Name):
            return None
        return self._assignment(stable[0])

    def banned_references(self, names: frozenset[str]) -> list[BuiltinReference]:
        references = [
            reference
            for node in self.context.nodes(ast.Name, ast.Attribute)
            if (reference := self._banned_reference(node, names)) is not None
        ]
        if imported := names.intersection({"exec", "eval"}):
            references.extend(
                BuiltinReference(alias, alias.name)
                for statement in self.context.nodes(ast.ImportFrom)
                if statement.level == 0 and statement.module == "builtins"
                for alias in statement.names
                if alias.name in imported
            )
        return sorted(references, key=lambda item: (item.node.lineno, item.node.col_offset))

    def _banned_reference(self, node: ast.Name | ast.Attribute, names: frozenset[str]) -> BuiltinReference | None:
        if not isinstance(node.ctx, ast.Load):
            return None
        if isinstance(node, ast.Name):
            if node.id not in names or not self.builtin(node):
                return None
            name = node.id
            direct_import = False
        else:
            qualified = self.qualified(node)
            if qualified is None or not qualified.startswith("builtins."):
                return None
            name = qualified.removeprefix("builtins.")
            if name not in names:
                return None
            direct_import = self._direct_builtin_module(node.value)
        if self._native_owner(node, name, direct_import=direct_import):
            return None
        return BuiltinReference(node, name)

    def _direct_builtin_module(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Name):
            return False
        scope = self._binding_scope(node.id, node)
        declarations = self.inventory.bindings.get(scope, {}).get(node.id, ())
        return bool(declarations) and all(
            isinstance(item, ast.alias)
            and isinstance(self.context.parents.get(item), ast.Import)
            and item.name == "builtins"
            for item in declarations
        )

    def _native_owner(self, node: ast.expr, name: str, *, direct_import: bool) -> bool:
        if direct_import and name in _RUFF_BANNED_API:
            return True
        if name == "eval" and (isinstance(node, ast.Name) or direct_import):
            return True
        parent = self.context.parents.get(node)
        if not isinstance(parent, ast.Call) or parent.func is not node:
            return False
        if name in {"exec", "breakpoint"}:
            return isinstance(node, ast.Name) or direct_import
        if isinstance(node, ast.Attribute) or parent.keywords:
            return False
        match parent.args:
            case [receiver, ast.Constant(value=str() as value)]:
                if name == "getattr" and isinstance(receiver, ast.Starred):
                    return False
            case _:
                return False
        if name == "hasattr":
            return value == "__call__"
        if name == "delattr":
            return self._native_delattr_owner(parent, receiver, value)
        if name != "getattr":
            return False
        mangled = value.startswith("__") and not value.endswith("__")
        return value.isidentifier() and not keyword.iskeyword(value) and not mangled

    def _native_delattr_owner(self, call: ast.Call, receiver: ast.expr, value: str) -> bool:
        statement = self.context.parents.get(call)
        return (
            isinstance(statement, ast.Expr)
            and statement.value is call
            and not isinstance(receiver, ast.Starred)
            and value != "__debug__"
            and value.isidentifier()
            and not keyword.iskeyword(value)
            and not (value.startswith("__") and not value.endswith("__"))
        )

    def _binding_scope(self, name: str, at: ast.AST) -> ast.AST | None:
        scope = self._scope(at)
        skip_classes = False
        while scope is not None:
            if isinstance(scope, ast.ClassDef) and skip_classes:
                scope = self._scope(scope)
                continue
            declarations = self.inventory.bindings.get(scope, {}).get(name, ())
            globals_here = any(isinstance(item, ast.Global) for item in declarations)
            if globals_here and scope is not self.context.tree:
                if _declares_value(declarations):
                    return scope
                scope = self.context.tree
                continue
            if _declares_value(declarations) or name in _type_parameters(scope):
                return scope
            skip_classes |= isinstance(scope, _FUNCTION_SCOPES)
            scope = self._scope(scope)
        return None

    def _scope(self, node: ast.AST) -> ast.AST | None:
        original = node
        parent = self.context.parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.TypeAlias):
                return parent
            if isinstance(parent, ast.comprehension) and parent.iter is node:
                owner = self.context.parents.get(parent)
                if (
                    isinstance(owner, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp)
                    and owner.generators[0] is parent
                ):
                    return self._scope(owner)
            if isinstance(parent, (ast.Module, ast.ClassDef, *_FUNCTION_SCOPES)):
                break
            node, parent = parent, self.context.parents.get(parent)
        return self.inventory.scope(original)

    def _qualified(self, expression: ast.expr, seen: frozenset[ast.AST], *, assignments: bool) -> str | None:
        if expression in seen:
            return None
        seen |= {expression}
        if isinstance(expression, ast.Attribute):
            base = self._qualified(expression.value, seen, assignments=assignments)
            return None if base is None else f"{base}.{expression.attr}"
        if not isinstance(expression, ast.Name):
            return None
        scope = self._binding_scope(expression.id, expression)
        if scope is None:
            return f"builtins.{expression.id}" if expression.id in _NATIVE_NAMES else None
        declarations = self.inventory.bindings.get(scope, {}).get(expression.id, ())
        declarations = tuple(item for item in declarations if not self._inplace_target(item))
        if not declarations:
            return None
        origins = {self._declaration_origin(item, seen, assignments=assignments) for item in declarations}
        if len(origins) != 1:
            return None
        return next(iter(origins))

    def _declaration_origin(self, node: ast.AST, seen: frozenset[ast.AST], *, assignments: bool) -> str | None:
        if node in seen:
            return None
        parent = self.context.parents.get(node)
        if isinstance(node, ast.alias):
            if isinstance(parent, ast.Import):
                return node.name if node.asname else node.name.partition(".")[0]
            if isinstance(parent, ast.ImportFrom) and parent.level == 0 and parent.module is not None:
                return f"{parent.module}.{node.name}"
        if assignments and isinstance(node, ast.Name) and (value := self._assignment(node)) is not None:
            return self._qualified(value, seen | {node}, assignments=assignments)
        return None

    def _assignment(self, node: ast.Name) -> ast.expr | None:
        parent = self.context.parents.get(node)
        if isinstance(parent, ast.Assign) and node in parent.targets:
            return parent.value
        if isinstance(parent, ast.AnnAssign) and parent.target is node:
            return parent.value
        if isinstance(parent, ast.NamedExpr) and parent.target is node:
            return parent.value
        return None

    def _inplace_target(self, node: ast.AST) -> bool:
        parent = self.context.parents.get(node)
        return isinstance(parent, ast.AugAssign) and parent.target is node


def _declares_value(declarations: Iterable[ast.AST]) -> bool:
    return any(not isinstance(item, ast.Global) for item in declarations)


def _type_parameters(scope: ast.AST) -> frozenset[str]:
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.TypeAlias):
        return frozenset(
            parameter.name
            for parameter in scope.type_params
            if isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple)
        )
    return frozenset()
