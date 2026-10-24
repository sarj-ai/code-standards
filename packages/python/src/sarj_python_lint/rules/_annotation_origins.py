from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


class AnnotationOrigins:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = context.static_resource_provenance
        self.imports = {
            node: ImportIndex.from_tree(ast.Module(body=[node], type_ignores=[]))
            for node in context.nodes(ast.Import, ast.ImportFrom)
        }

    def shadowed(self, name: str, at: ast.AST) -> bool:
        return type_parameter_shadow(name, at, self.context)

    def qualified(self, node: ast.expr, at: ast.AST) -> str | None:
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if (
            not isinstance(root, ast.Name)
            or root.id in self.provenance.mutated | self.provenance.external_bindings
            or type_parameter_shadow(root.id, at, self.context)
        ):
            return None
        binding = self.provenance.binding(root.id, at)
        parent = self.context.parents.get(binding) if binding is not None else None
        index = self.imports.get(parent) if isinstance(parent, ast.Import | ast.ImportFrom) else None
        return index.resolved_qualified_name(node) if index is not None else None

    def builtin(self, node: ast.expr, name: str, at: ast.AST) -> bool:
        return (
            self.provenance.builtin_namespace_untouched
            and isinstance(node, ast.Name)
            and node.id == name
            and not type_parameter_shadow(name, at, self.context)
            and self.provenance.binding(name, at) is None
        )


def type_parameter_shadow(name: str, at: ast.AST, context: PythonFileContext) -> bool:
    outside: set[ast.AST] = set()
    current = at
    while (parent := context.parents.get(current)) is not None:
        if (
            isinstance(parent, ast.arguments)
            and (current in parent.defaults or current in parent.kw_defaults)
            and (owner := context.parents.get(parent)) is not None
        ):
            outside.add(owner)
        if (
            isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.TypeAlias)
            and parent not in outside
            and not (
                isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and current in parent.decorator_list
            )
            and any(
                isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple) and parameter.name == name
                for parameter in parent.type_params
            )
        ):
            return True
        current = parent
    return False
