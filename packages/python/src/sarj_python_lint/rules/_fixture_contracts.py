from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._binding_inventory import scope_binding_names
from sarj_python_lint.rules._declared_contracts import DeclaredClass
from sarj_python_lint.rules._project_index import SourceUnit, SymbolRef
from sarj_python_lint.rules._resolved_operation_signature import resolved_operation_signature
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_yields


if TYPE_CHECKING:
    from sarj_python_lint.rules._declared_contracts import DeclaredContracts
    from sarj_python_lint.rules._imports import ImportIndex


PORT_BASES = frozenset({"abc.ABC", "typing.Protocol", "typing_extensions.Protocol"})
MAX_DEPTH = 8
_METHOD_DECORATORS = frozenset({"abc.abstractmethod", "typing.override", "typing_extensions.override"})
CONSTRUCTION_HOOKS = frozenset({"__new__", "__init_subclass__"})
_MEMBER_HOOKS = frozenset({"__getattribute__", "__getattr__", "__init_subclass__"})


@dataclass(frozen=True)
class DeclaredMethod:
    declaration: ast.FunctionDef | ast.AsyncFunctionDef
    owner: DeclaredClass


def abstract_contract(model: DeclaredClass, contracts: DeclaredContracts) -> bool:
    if model.unit.tree is None:
        return False
    imports = contracts.imports_for(model.unit)
    return any(
        imports.resolved_qualified_name(base) in {"typing.Protocol", "typing_extensions.Protocol"}
        for base in model.declaration.bases
    ) or bool(_abstract_members(model, contracts))


def _abstract_members(
    model: DeclaredClass,
    contracts: DeclaredContracts,
    seen: frozenset[ast.ClassDef] = frozenset(),
    *,
    cache: dict[tuple[ast.ClassDef, int], frozenset[str]] | None = None,
) -> frozenset[str]:
    if model.unit.tree is None or model.declaration in seen or len(seen) >= MAX_DEPTH:
        return frozenset()
    memo = {} if cache is None else cache
    key = model.declaration, len(seen)
    if key in memo:
        return memo[key]
    imports = contracts.imports_for(model.unit)
    pending: set[str] = set()
    for base in model.declaration.bases:
        parent = contracts.class_type(base, model.unit)
        if parent is not None:
            pending.update(_abstract_members(parent, contracts, seen | {model.declaration}, cache=memo))
    for member in model.declaration.body:
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(
                imports.resolves(decorator, sources=frozenset({"abc"}), symbol="abstractmethod")
                for decorator in member.decorator_list
            ):
                pending.add(member.name)
            else:
                pending.discard(member.name)
    result = frozenset(pending)
    memo[key] = result
    return result


def abstract_ancestors(model: DeclaredClass, contracts: DeclaredContracts) -> tuple[DeclaredClass, ...]:
    pending = [(model, 0)]
    seen: set[ast.ClassDef] = set()
    found: dict[ast.ClassDef, DeclaredClass] = {}
    checked: list[DeclaredClass] = []
    while pending:
        current, depth = pending.pop()
        if depth >= MAX_DEPTH:
            return ()
        if current.declaration in seen:
            continue
        seen.add(current.declaration)
        checked.append(current)
        for base in current.declaration.bases:
            owner = contracts.class_type(base, current.unit)
            if owner is None:
                continue
            if abstract_contract(owner, contracts) and contracts.inherits(owner, PORT_BASES):
                found[owner.declaration] = owner
            else:
                pending.append((owner, depth + 1))
    candidates = tuple(found.values())
    if len(candidates) != 1:
        return candidates
    return candidates if all(class_identity_stable(current, contracts) for current in checked) else ()


def contract_accepts(model: DeclaredClass, target: DeclaredClass, contracts: DeclaredContracts) -> bool:
    pending = [(model, 0)]
    seen: set[ast.ClassDef] = set()
    while pending:
        current, depth = pending.pop()
        if current.declaration is target.declaration:
            return True
        if current.declaration in seen or depth >= MAX_DEPTH:
            continue
        seen.add(current.declaration)
        pending.extend(
            (parent, depth + 1)
            for base in current.declaration.bases
            if (parent := contracts.class_type(base, current.unit)) is not None
        )
    return False


def has_class_hook(
    model: DeclaredClass,
    contracts: DeclaredContracts,
    names: frozenset[str],
) -> bool:
    pending = [(model, 0)]
    seen: set[ast.ClassDef] = set()
    while pending:
        current, depth = pending.pop()
        if depth >= MAX_DEPTH:
            return True
        if current.declaration in seen:
            continue
        seen.add(current.declaration)
        if _declares_hook(current, names):
            return True
        parents = _hook_parents(current, contracts)
        if parents is None:
            return True
        pending.extend((parent, depth + 1) for parent in parents)
    return False


def _declares_hook(model: DeclaredClass, names: frozenset[str]) -> bool:
    return any(
        (isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name in names)
        or any(_class_member_replaced(member, name) for name in names)
        for member in model.declaration.body
    )


def _hook_parents(model: DeclaredClass, contracts: DeclaredContracts) -> tuple[DeclaredClass, ...] | None:
    imports = contracts.imports_for(model.unit) if model.unit.tree is not None else None
    parents: list[DeclaredClass] = []
    for base in model.declaration.bases:
        parent = contracts.class_type(base, model.unit)
        if parent is not None:
            parents.append(parent)
        elif imports is None or imports.resolved_qualified_name(base) not in PORT_BASES:
            return None
    return tuple(parents)


def method_definition(
    model: DeclaredClass,
    name: str,
    contracts: DeclaredContracts,
    seen: frozenset[ast.ClassDef] = frozenset(),
) -> DeclaredMethod | None:
    if (
        model.declaration in seen
        or len(seen) >= MAX_DEPTH
        or model.declaration.type_params
        or not class_identity_stable(model, contracts)
    ):
        return None
    if _method_replaced(model.declaration, name):
        return None
    definitions = [
        member
        for member in model.declaration.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name == name
    ]
    if definitions:
        return DeclaredMethod(definitions[0], model) if len(definitions) == 1 else None
    if len(model.declaration.bases) != 1:
        return None
    inherited = [
        result
        for base in model.declaration.bases
        if (parent := contracts.class_type(base, model.unit)) is not None
        and (result := method_definition(parent, name, contracts, seen | {model.declaration})) is not None
    ]
    return inherited[0] if len(inherited) == 1 else None


def _method_replaced(declaration: ast.ClassDef, name: str) -> bool:
    instance_write = any(
        isinstance(node, ast.Attribute) and node.attr == name and isinstance(node.ctx, ast.Store | ast.Del)
        for node in ast.walk(declaration)
    )
    return instance_write or any(_class_member_replaced(member, name) for member in declaration.body)


def _class_member_replaced(member: ast.AST, name: str) -> bool:
    match member:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return False
        case ast.ClassDef(name=bound):
            return bound == name
        case _:
            pass
    return name in scope_binding_names(member)


def compatible_operation(
    implementation: DeclaredClass, contract: DeclaredClass, name: str, contracts: DeclaredContracts
) -> bool:
    if name.startswith("_") or has_class_hook(implementation, contracts, _MEMBER_HOOKS):
        return False
    concrete = method_definition(implementation, name, contracts)
    abstract = method_definition(contract, name, contracts)
    if concrete is None or abstract is None:
        return False
    if isinstance(concrete.declaration, ast.AsyncFunctionDef) and fixture_yields(
        concrete.declaration
    ) != fixture_yields(abstract.declaration):
        return False
    concrete_signature = _operation_signature(concrete, contracts)
    return concrete_signature is not None and concrete_signature == _operation_signature(abstract, contracts)


def class_identity_stable(model: DeclaredClass, contracts: DeclaredContracts) -> bool:
    module = model.unit.module
    return module is not None and not contracts.project.nominal_membership_is_dynamic(
        SymbolRef(module, model.declaration.name)
    )


def _operation_signature(definition: DeclaredMethod, contracts: DeclaredContracts) -> str | None:
    method, unit = definition.declaration, definition.owner.unit
    if unit.tree is None:
        return None
    imports = contracts.imports_for(unit)
    if any(imports.resolved_qualified_name(decorator) not in _METHOD_DECORATORS for decorator in method.decorator_list):
        return None
    annotations = [
        method.returns,
        *(argument.annotation for argument in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)),
    ]
    shadowed = frozenset(name for member in definition.owner.declaration.body for name in contracts.bound_names(member))
    if any(
        _opaque_annotation(annotation, unit, contracts, imports, shadowed)
        for annotation in annotations
        if annotation is not None
    ):
        return None
    return resolved_operation_signature(method, unit, imports)


def _opaque_annotation(
    annotation: ast.expr, unit: SourceUnit, contracts: DeclaredContracts, imports: ImportIndex, shadowed: frozenset[str]
) -> bool:
    for node in ast.walk(annotation):
        if not isinstance(node, ast.Name | ast.Attribute):
            continue
        if isinstance(node, ast.Name) and node.id in shadowed:
            return True
        if imports.resolved_qualified_name(node) in {"typing.Self", "typing_extensions.Self"}:
            return True
        if _source_alias_annotation(node, unit, contracts):
            return True
    return False


def _source_alias_annotation(node: ast.Name | ast.Attribute, unit: SourceUnit, contracts: DeclaredContracts) -> bool:
    symbol = contracts.project.resolve(unit, node)
    source = contracts.project.source_unit(symbol.module) if symbol is not None else None
    return source is not None and source is not unit and contracts.class_type(node, unit) is None
