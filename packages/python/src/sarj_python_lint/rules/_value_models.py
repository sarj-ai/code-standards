from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts, written_attribute_roots


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex


_DATACLASSES = frozenset({"dataclasses", "pydantic.dataclasses", "pydantic.v1.dataclasses"})
_MODELS = frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"})
_MODEL_CONFIG = frozenset({"pydantic", "pydantic.config"})
_SETTINGS = frozenset({"pydantic_settings", "pydantic_settings.main", "pydantic.v1", "pydantic.v1.env_settings"})
_TYPING = frozenset({"typing", "typing_extensions"})
_TYPING_RECORDS = frozenset({"TypedDict", "NamedTuple"})
_TYPING_RECORD_OPTIONS = frozenset({"total", "closed", "extra_items"})
_MAX_ANCESTORS = 32


def value_model(
    model: DeclaredClass,
    contracts: DeclaredContracts,
    *,
    include_settings: bool = False,
    include_dataclasses: bool = True,
    include_typing_records: bool = False,
    include_typed_dict: bool = False,
) -> bool:
    pending = [model]
    seen: set[ast.ClassDef] = set()
    while pending and len(seen) < _MAX_ANCESTORS:
        current = pending.pop()
        owner = current.declaration
        if owner in seen:
            continue
        seen.add(owner)
        if (include_typing_records or include_typed_dict) and _native_typing_record(
            current, contracts, typed_dict_only=not include_typing_records
        ):
            return True
        if not _supported_declaration(
            current, contracts, allow_record_options=include_typed_dict, allow_model_config=include_typed_dict
        ):
            continue
        if _native_value_identity(
            current, contracts, include_settings=include_settings, include_dataclasses=include_dataclasses
        ):
            return True
        for base in owner.bases:
            parent = contracts.class_type(base, current.unit)
            if parent is not None:
                pending.append(parent)
    return False


def _supported_declaration(
    model: DeclaredClass,
    contracts: DeclaredContracts,
    *,
    allow_record_options: bool = False,
    allow_model_config: bool = False,
) -> bool:
    owner = model.declaration
    tree = model.unit.tree
    if owner.type_params or tree is None or _wildcard(tree):
        return False
    if owner.keywords and (
        not allow_record_options or any(keyword.arg not in _TYPING_RECORD_OPTIONS for keyword in owner.keywords)
    ):
        return False
    imports = contracts.imports_for(model.unit)
    return all(
        _identity_decorator(node, model, imports, allow_model_config=allow_model_config)
        for node in owner.decorator_list
    )


def _identity_decorator(
    decorator: ast.expr, model: DeclaredClass, imports: ImportIndex, *, allow_model_config: bool
) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return stable_native(target, model) and (
        imports.resolves(target, sources=_DATACLASSES, symbol="dataclass")
        or imports.resolves(target, sources=_TYPING, symbol="final")
        or (allow_model_config and imports.resolves(target, sources=_MODEL_CONFIG, symbol="with_config"))
    )


def _native_value_identity(
    model: DeclaredClass, contracts: DeclaredContracts, *, include_settings: bool, include_dataclasses: bool
) -> bool:
    imports = contracts.imports_for(model.unit)
    decorators = [node.func if isinstance(node, ast.Call) else node for node in model.declaration.decorator_list]
    if include_dataclasses and any(
        imports.resolves(node, sources=_DATACLASSES, symbol="dataclass") for node in decorators
    ):
        return True
    return any(
        _native_model_base(base, model, imports, include_settings=include_settings) for base in model.declaration.bases
    )


def _native_typing_record(model: DeclaredClass, contracts: DeclaredContracts, *, typed_dict_only: bool) -> bool:
    if not _supported_declaration(model, contracts, allow_record_options=True, allow_model_config=typed_dict_only):
        return False
    imports = contracts.imports_for(model.unit)
    allowed = ("TypedDict",) if typed_dict_only else _TYPING_RECORDS
    return any(
        stable_native(base, model) and imports.resolved_symbol(base, sources=_TYPING) in allowed
        for base in model.declaration.bases
    )


def _native_model_base(base: ast.expr, model: DeclaredClass, imports: ImportIndex, *, include_settings: bool) -> bool:
    return stable_native(base, model) and (
        imports.resolves(base, sources=_MODELS, symbol="BaseModel")
        or (include_settings and imports.resolves(base, sources=_SETTINGS, symbol="BaseSettings"))
    )


def _wildcard(tree: ast.Module) -> bool:
    return any(alias.name == "*" for node in nodes(tree, ast.ImportFrom) for alias in node.names)


def stable_native(expression: ast.expr, model: DeclaredClass) -> bool:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    return (
        isinstance(root, ast.Name)
        and model.unit.tree is not None
        and root.id not in written_attribute_roots(model.unit.tree)
    )
