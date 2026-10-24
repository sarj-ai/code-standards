from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


MODEL_BASES = frozenset({"pydantic.BaseModel", "pydantic.main.BaseModel"})
SETTINGS_BASES = frozenset({"pydantic_settings.BaseSettings", "pydantic_settings.main.BaseSettings"})
_MAX_DEPTH = 8
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True)
class DeclaredClass:
    unit: SourceUnit
    declaration: ast.ClassDef


def _class_metadata_annotation(annotation: ast.expr, semantics: AnnotationSemantics) -> bool:
    pending = [annotation]
    seen: set[str] = set()
    while pending:
        node = semantics.parse(pending.pop())
        if node is None:
            return True
        for member in ast.walk(node):
            if isinstance(member, ast.Subscript) and semantics.imports.resolved_symbol(
                member.value, sources=_TYPING_SOURCES
            ) in {"ClassVar", "Final"}:
                return True
            if isinstance(member, ast.Name) and member.id in semantics.aliases and member.id not in seen:
                seen.add(member.id)
                pending.append(semantics.aliases[member.id])
    return False


class DeclaredContracts:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self._field_cache: dict[ast.ClassDef, dict[str, ast.AnnAssign]] = {}
        self._module_annotations: dict[Path, AnnotationSemantics] = {}
        self.project = context.session.project or ProjectIndexSet.single(context.path, context.source)
        self.unit = self.project.unit(context.path)
        if self.unit is not None and self.unit.tree is not context.tree:
            self.unit = SourceUnit(self.unit.path, self.unit.module, self.unit.source, context.tree, self.unit.imports)
            self.project = self.project.with_unit(self.unit)
        if self.unit is not None and self.unit.module is None:
            self.unit = SourceUnit(
                context.path,
                "__snippet__",
                context.source,
                context.tree,
                {
                    name: SymbolRef(target.module, target.symbol or "")
                    for name, target in context.module_imports.bindings.items()
                },
            )
            self.project = self.project.with_unit(self.unit)

    def class_type(
        self, expression: ast.expr, unit: SourceUnit | None = None, *, at: ast.AST | None = None
    ) -> DeclaredClass | None:
        owner = unit or self.unit
        if owner is None or not self._lookup_allowed(expression, owner, at):
            return None
        summary = self.project.class_for(owner, expression)
        source = self.project.source_unit(summary.symbol.module) if summary is not None else None
        if source is None or source.tree is None or summary is None:
            return None
        declaration = self._stable_declaration(source, summary.symbol.name)
        return DeclaredClass(source, declaration) if declaration is not None else None

    def _lookup_allowed(self, expression: ast.expr, owner: SourceUnit, at: ast.AST | None) -> bool:
        if owner is not self.unit or (at or expression) not in self.context.parents:
            return True
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name):
            return True
        binding = self.context.static_resource_provenance.binding(root.id, at or expression)
        return (
            isinstance(binding, ast.alias | ast.ClassDef)
            and root.id not in self.context.static_resource_provenance.mutated
        )

    def _stable_declaration(self, source: SourceUnit, name: str) -> ast.ClassDef | None:
        if source.tree is None:
            return None
        declarations = [node for node in source.tree.body if isinstance(node, ast.ClassDef) and node.name == name]
        if len(declarations) != 1 or declarations[0].keywords:
            return None
        if not self._identity_decorators(source, declarations[0]):
            return None
        if any(
            isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store | ast.Del)
            for statement in source.tree.body
            if not isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            for node in ast.walk(statement)
        ):
            return None
        return declarations[0]

    def _identity_decorators(self, source: SourceUnit, declaration: ast.ClassDef) -> bool:
        if not declaration.decorator_list:
            return True
        if source.tree is None:
            return False
        imports = (
            self.context.module_imports
            if source.path == self.context.path
            else ImportIndex.from_tree(source.tree, module_scope_only=True)
        )
        return all(
            imports.resolves(decorator, sources=_TYPING_SOURCES, symbol="final")
            for decorator in declaration.decorator_list
        )

    def inherits(self, model: DeclaredClass, bases: frozenset[str]) -> bool:
        return self.project.class_inherits_from(model.unit, model.declaration.name, bases)

    def model_fields(self, model: DeclaredClass) -> dict[str, ast.AnnAssign]:
        if model.unit.tree is None:
            return {}
        cached = self._field_cache.get(model.declaration)
        if cached is not None:
            return cached
        semantics = self._module_semantics(model.unit)
        fields = {
            node.target.id: node
            for node in model.declaration.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and not node.target.id.startswith("_")
            and node.target.id != "model_config"
            and not _class_metadata_annotation(node.annotation, semantics)
        }
        self._field_cache[model.declaration] = fields
        return fields

    def _module_semantics(self, unit: SourceUnit) -> AnnotationSemantics:
        if unit.tree is None:
            return self.context.annotation_semantics
        semantics = self._module_annotations.get(unit.path)
        if semantics is None:
            imports = (
                self.context.module_imports
                if unit.path == self.context.path
                else ImportIndex.from_tree(unit.tree, module_scope_only=True)
            )
            semantics = AnnotationSemantics.from_imports(unit.tree, imports)
            self._module_annotations[unit.path] = semantics
        return semantics

    def annotation(self, expression: ast.expr, unit: SourceUnit | None = None) -> DeclaredClass | None:
        semantics = self.context.annotation_semantics
        if unit is not None and unit is not self.unit and unit.tree is not None:
            semantics = self._module_semantics(unit)
        candidates = [
            model
            for member in semantics.transparent_members(expression)
            if (model := self.class_type(member, unit, at=expression)) is not None
        ]
        return candidates[0] if len(candidates) == 1 else None

    def value(self, expression: ast.expr, *, depth: int = 0) -> DeclaredClass | None:
        if depth > _MAX_DEPTH:
            return None
        match expression:
            case ast.Await():
                return self.value(expression.value, depth=depth + 1)
            case ast.Name():
                return self._local_value(expression, depth)
            case ast.Call():
                return self.class_type(expression.func) or self._call_result(expression, depth)
            case _:
                return None

    def _local_value(self, expression: ast.Name, depth: int) -> DeclaredClass | None:
        binding = self.context.static_resource_provenance.binding(expression.id, expression)
        if isinstance(binding, ast.arg) and binding.annotation is not None:
            return self.annotation(binding.annotation)
        parent = self.context.parents.get(binding) if binding is not None else None
        if isinstance(parent, ast.AnnAssign):
            return self.annotation(parent.annotation)
        if isinstance(binding, ast.Name):
            value = self.context.static_resource_provenance.assignment_value(binding, expression)
            return self.value(value, depth=depth + 1) if value is not None else None
        return None

    def _call_result(self, expression: ast.Call, depth: int) -> DeclaredClass | None:
        match expression.func:
            case ast.Name():
                binding = self.context.static_resource_provenance.binding(expression.func.id, expression)
                if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef) and binding.returns is not None:
                    return self.annotation(binding.returns)
                return None
            case ast.Attribute():
                return self._method_result(expression.func, depth)
            case _:
                return None

    def _method_result(self, target: ast.Attribute, depth: int) -> DeclaredClass | None:
        model = self.class_type(target.value) or self.value(target.value, depth=depth + 1)
        if model is None:
            return None
        if target.attr in {"model_validate", "model_validate_json", "model_copy"} and self.inherits(
            model, MODEL_BASES | SETTINGS_BASES
        ):
            return model
        methods = [
            node
            for node in model.declaration.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == target.attr
        ]
        if len(methods) == 1 and methods[0].returns is not None and not methods[0].decorator_list:
            return self.annotation(methods[0].returns, model.unit)
        return None


def ordinary_pytest_test(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    if not function.name.startswith("test_"):
        return False
    owner = context.parents.get(function)
    if isinstance(owner, ast.ClassDef) and (owner.bases or owner.decorator_list or owner.keywords):
        return False
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        qualified = context.imports.resolved_qualified_name(target)
        if qualified is None or not qualified.startswith("pytest.mark."):
            return False
    return True
