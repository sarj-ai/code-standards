from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts, written_attribute_roots


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex


_DATACLASSES = frozenset({"dataclasses", "pydantic.dataclasses", "pydantic.v1.dataclasses"})
_MODELS = frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"})
_SETTINGS = frozenset({"pydantic_settings", "pydantic_settings.main", "pydantic.v1", "pydantic.v1.env_settings"})
_TYPING = frozenset({"typing", "typing_extensions"})
_MAX_ANCESTORS = 32


def value_model(model: DeclaredClass, contracts: DeclaredContracts, *, include_settings: bool = False) -> bool:
    pending = [model]
    seen: set[ast.ClassDef] = set()
    while pending and len(seen) < _MAX_ANCESTORS:
        current = pending.pop()
        owner = current.declaration
        if owner in seen:
            continue
        seen.add(owner)
        if not _supported_declaration(current, contracts):
            continue
        if _native_value_identity(current, contracts, include_settings=include_settings):
            return True
        for base in owner.bases:
            parent = contracts.class_type(base, current.unit)
            if parent is not None:
                pending.append(parent)
    return False


def _supported_declaration(model: DeclaredClass, contracts: DeclaredContracts) -> bool:
    owner = model.declaration
    tree = model.unit.tree
    if owner.keywords or owner.type_params or tree is None or _wildcard(tree):
        return False
    imports = contracts.imports_for(model.unit)
    return all(_identity_decorator(node, model, imports) for node in owner.decorator_list)


def _identity_decorator(decorator: ast.expr, model: DeclaredClass, imports: ImportIndex) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return stable_native(target, model) and (
        imports.resolves(target, sources=_DATACLASSES, symbol="dataclass")
        or imports.resolves(target, sources=_TYPING, symbol="final")
    )


def _native_value_identity(model: DeclaredClass, contracts: DeclaredContracts, *, include_settings: bool) -> bool:
    imports = contracts.imports_for(model.unit)
    decorators = [node.func if isinstance(node, ast.Call) else node for node in model.declaration.decorator_list]
    if any(imports.resolves(node, sources=_DATACLASSES, symbol="dataclass") for node in decorators):
        return True
    return any(
        _native_model_base(base, model, imports, include_settings=include_settings) for base in model.declaration.bases
    )


def _native_model_base(base: ast.expr, model: DeclaredClass, imports: ImportIndex, *, include_settings: bool) -> bool:
    return stable_native(base, model) and (
        imports.resolves(base, sources=_MODELS, symbol="BaseModel")
        or (include_settings and imports.resolves(base, sources=_SETTINGS, symbol="BaseSettings"))
    )


def _wildcard(tree: ast.Module) -> bool:
    return any(alias.name == "*" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names)


def stable_native(expression: ast.expr, model: DeclaredClass) -> bool:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    return (
        isinstance(root, ast.Name)
        and model.unit.tree is not None
        and root.id not in written_attribute_roots(model.unit.tree)
    )
