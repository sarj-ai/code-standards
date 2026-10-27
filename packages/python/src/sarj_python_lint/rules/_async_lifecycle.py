from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_INTROSPECTION = frozenset({"__dict__", "__setattr__", "__delattr__", "__getattribute__"})


@dataclass(frozen=True, slots=True)
class _LocalAssignment:
    binding: ast.Name
    value: ast.expr


@final
class AsyncApiProof:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = context.static_resource_provenance
        self._namespace_safety: dict[str, bool] = {}
        self._origins: dict[str, set[str]] = {}
        for node in context.nodes(ast.Import, ast.ImportFrom):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.partition(".")[0]
                    target = alias.name if alias.asname else alias.name.partition(".")[0]
                    self._origins.setdefault(name, set()).add(target)
            elif node.level == 0 and node.module is not None:
                for alias in node.names:
                    self._origins.setdefault(alias.asname or alias.name, set()).add(f"{node.module}.{alias.name}")

    def imported(self, expression: ast.expr, qualified: str) -> bool:
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name):
            return False
        if (
            self.context.dynamic_namespace
            or self.provenance.wildcard
            or root.id in self.provenance.mutated
            or root.id in self.provenance.external_bindings
        ):
            return False
        binding = self.provenance.binding(root.id, expression)
        if (
            not isinstance(binding, ast.alias)
            or not isinstance(self.provenance.scope(binding), ast.Module)
            or import_name_for_binding(expression, binding, self.context.parents.get(binding)) != qualified
        ):
            return False
        declaration = self.context.parents.get(binding)
        if not isinstance(declaration, ast.Import | ast.ImportFrom) or not isinstance(
            self.context.parents.get(declaration), ast.Module
        ):
            return False
        if qualified not in self._namespace_safety:
            self._namespace_safety[qualified] = self._namespace_untouched(qualified)
        return self._namespace_safety[qualified]

    def _namespace_untouched(self, qualified: str) -> bool:
        for node in self.context.nodes(ast.Name, ast.Attribute):
            targets = self._targets(node)
            if not any(
                target == qualified or target.startswith(qualified + ".") or qualified.startswith(target + ".")
                for target in targets
            ):
                continue
            if not isinstance(node.ctx, ast.Load) or not self._safe_api_read(node, qualified):
                return False
        return True

    def _targets(self, expression: ast.Name | ast.Attribute) -> tuple[str, ...]:
        parts: list[str] = []
        root: ast.expr = expression
        while isinstance(root, ast.Attribute):
            parts.append(root.attr)
            root = root.value
        if not isinstance(root, ast.Name):
            return ()
        suffix = ".".join(reversed(parts))
        return tuple(f"{origin}.{suffix}" if suffix else origin for origin in self._origins.get(root.id, ()))

    def _safe_api_read(self, node: ast.Name | ast.Attribute, qualified: str) -> bool:
        parent = self.context.parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.value is node:
            return parent.attr not in _INTROSPECTION
        if isinstance(parent, ast.Call) and parent.func is node:
            return True
        if isinstance(parent, ast.Subscript) and parent.value is node:
            return True
        if isinstance(parent, ast.arg | ast.AnnAssign) and parent.annotation is node:
            return True
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            return parent.returns is node or (
                qualified == "contextlib.asynccontextmanager" and node in parent.decorator_list
            )
        return isinstance(parent, ast.ExceptHandler) and parent.type is node

    def assignment(self, name: ast.Name, at: ast.AST) -> _LocalAssignment | None:
        binding = self.provenance.binding(name.id, at)
        if (
            not isinstance(binding, ast.Name)
            or name.id in self.provenance.mutated
            or name.id in self.provenance.external_bindings
        ):
            return None
        value = self.provenance.assignment_value(binding, at)
        return _LocalAssignment(binding=binding, value=value) if value is not None else None


def method_receiver(call: ast.Call, methods: frozenset[str]) -> ast.Name | None:
    callee = call.func
    if isinstance(callee, ast.Attribute) and callee.attr in methods and isinstance(callee.value, ast.Name):
        return callee.value
    return None
