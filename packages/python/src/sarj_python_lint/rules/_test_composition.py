from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


type Function = ast.FunctionDef | ast.AsyncFunctionDef
_PORT_BASES = frozenset({"abc.ABC", "typing.Protocol", "typing_extensions.Protocol"})
_MIN_COLLABORATORS = 2


@dataclass(frozen=True)
class Constructor:
    symbol: SymbolRef
    positional: tuple[str, ...]
    collaborators: frozenset[str]


@dataclass(frozen=True)
class WiringScope:
    parameters: frozenset[str]
    aliases: dict[str, ast.expr]
    blocked: frozenset[str]


def direct_nodes(node: ast.AST) -> Iterator[ast.AST]:
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from direct_nodes(child)


def _class_owner(
    context: PythonFileContext, expression: ast.expr, project: ProjectIndexSet
) -> tuple[SourceUnit, ast.ClassDef] | None:
    qualified = context.module_imports.resolved_qualified_name(expression)
    unit = project.unit(context.path)
    if qualified is not None:
        module, _, name = qualified.rpartition(".")
        unit = project.source_unit(module)
    elif isinstance(expression, ast.Name):
        name = expression.id
    else:
        return None
    if unit is None or unit.tree is None or unit.module is None:
        return None
    owner = next((node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == name), None)
    if owner is None:
        return None
    if any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
        for node in direct_nodes(unit.tree)
    ):
        return None
    return unit, owner


def constructor(context: PythonFileContext, expression: ast.expr, project: ProjectIndexSet) -> Constructor | None:
    resolved = _class_owner(context, expression, project)
    if resolved is None:
        return None
    unit, owner = resolved
    if unit.module is None:
        return None
    initializer = next(
        (node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None
    )
    if initializer is None:
        return None
    parameters = (*initializer.args.posonlyargs, *initializer.args.args, *initializer.args.kwonlyargs)
    invoked = _invoked_fields(owner)
    stored = _stored_parameters(initializer)
    collaborators = frozenset(
        parameter.arg
        for parameter in parameters
        if parameter.annotation is not None
        and _is_port(project, unit, parameter.annotation)
        and stored.get(parameter.arg) in invoked
    )
    if len(collaborators) < _MIN_COLLABORATORS:
        return None
    return Constructor(
        SymbolRef(unit.module, owner.name),
        tuple(arg.arg for arg in (*initializer.args.posonlyargs, *initializer.args.args)[1:]),
        collaborators,
    )


def _is_port(project: ProjectIndexSet, unit: SourceUnit, annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    summary = project.class_for(unit, annotation)
    if summary is None:
        return False
    owner = project.source_unit(summary.symbol.module)
    return owner is not None and project.class_inherits_from(owner, summary.symbol.name, _PORT_BASES)


def _stored_parameters(initializer: Function) -> dict[str, str]:
    stored: dict[str, str] = {}
    writes = Counter(
        node.attr
        for node in direct_nodes(initializer)
        if isinstance(node, ast.Attribute) and _is_self(node.value) and isinstance(node.ctx, (ast.Store, ast.Del))
    )
    for statement in initializer.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        else:
            continue
        if (
            isinstance(value, ast.Name)
            and isinstance(target, ast.Attribute)
            and _is_self(target.value)
            and writes[target.attr] == 1
        ):
            stored[value.id] = target.attr
    return stored


def _is_self(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _invoked_fields(owner: ast.ClassDef) -> frozenset[str]:
    invoked: set[str] = set()
    for method in owner.body:
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name != "__init__":
            invoked.update(_method_fields(method))
    return frozenset(invoked)


def _method_fields(method: Function) -> Iterator[str]:
    for node in direct_nodes(method):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if isinstance(target, ast.Attribute) and _is_self(target.value):
            yield target.attr


def bindings(function: Function) -> dict[str, ast.expr]:
    candidates: dict[str, list[ast.expr]] = {}
    for statement in function.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            candidates.setdefault(statement.targets[0].id, []).append(statement.value)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            candidates.setdefault(statement.target.id, []).append(statement.value)
    writes = [
        node.id
        for node in direct_nodes(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    ]
    return {name: values[0] for name, values in candidates.items() if len(values) == 1 and writes.count(name) == 1}


def local_names(function: Function) -> set[str]:
    names: set[str] = set()
    for node in direct_nodes(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
    return names


def changed_before(function: Function, call: ast.Call, aliases: dict[str, ast.expr]) -> set[str]:
    changed: set[str] = set()
    for node in direct_nodes(function):
        if not isinstance(node, (ast.Call, ast.Attribute, ast.Subscript)) or (node.lineno, node.col_offset) >= (
            call.lineno,
            call.col_offset,
        ):
            continue
        target = node.func.value if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else None
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            target = node.value
        while isinstance(target, (ast.Attribute, ast.Subscript)):
            target = target.value
        seen: set[str] = set()
        while isinstance(target, ast.Name) and target.id not in seen:
            seen.add(target.id)
            changed.add(target.id)
            value = aliases.get(target.id)
            if value is None or (value.lineno, value.col_offset) >= (node.lineno, node.col_offset):
                break
            target = value
    return changed


def unalias(node: ast.expr, aliases: dict[str, ast.expr]) -> ast.expr:
    seen: set[str] = set()
    while isinstance(node, ast.Name) and node.id in aliases and node.id not in seen:
        seen.add(node.id)
        node = aliases[node.id]
    return node


def shadowed(node: ast.expr, names: frozenset[str]) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id in names


def wiring(
    context: PythonFileContext,
    project: ProjectIndexSet,
    call: ast.Call,
    spec: Constructor,
    scope: WiringScope,
) -> tuple[tuple[str, str], ...] | None:
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(keyword.arg is None for keyword in call.keywords):
        return None
    if len(call.args) > len(spec.positional):
        return None
    values = dict(zip(spec.positional, call.args, strict=False))
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in values:
            return None
        values[keyword.arg] = keyword.value
    result: list[tuple[str, str]] = []
    for name in sorted(spec.collaborators):
        value = values.get(name)
        if value is None or not isinstance(unalias(value, scope.aliases), (ast.Name, ast.Call)):
            return None
        identity = _value_key(context, project, value, scope)
        if identity is None:
            return None
        result.append((name, identity))
    return tuple(result)


def _value_key(
    context: PythonFileContext,
    project: ProjectIndexSet,
    value: ast.expr,
    scope: WiringScope,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(value, ast.Name):
        if value.id in seen or value.id in scope.blocked:
            return None
        if value.id in scope.aliases:
            return _value_key(
                context,
                project,
                scope.aliases[value.id],
                scope,
                seen=seen | {value.id},
            )
        return f"fixture:{value.id}" if value.id in scope.parameters else None
    if isinstance(value, ast.Constant):
        return ast.dump(value)
    if not isinstance(value, ast.Call):
        return None
    callee = unalias(value.func, scope.aliases)
    if shadowed(callee, scope.parameters | scope.blocked):
        return None
    owner = _class_owner(context, callee, project)
    if owner is None or any(keyword.arg is None for keyword in value.keywords):
        return None
    positional = [_value_key(context, project, argument, scope, seen=seen) for argument in value.args]
    keywords = [
        (
            keyword.arg,
            _value_key(context, project, keyword.value, scope, seen=seen),
        )
        for keyword in value.keywords
    ]
    if any(key is None for key in positional) or any(key is None for _, key in keywords):
        return None
    return f"{owner[0].module}.{owner[1].name}:{positional!r}:{sorted(keywords)!r}"
