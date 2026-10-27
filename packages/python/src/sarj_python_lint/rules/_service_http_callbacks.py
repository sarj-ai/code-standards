from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


_CALLABLE_SOURCES = frozenset({"typing", "typing_extensions", "collections.abc"})
_NATIVE_CLIENTS = frozenset({"httpx.Client", "httpx.AsyncClient"})
_MAX_REEXPORTS = 8
_CALLABLE_ARITY = 2


@dataclass(frozen=True, slots=True)
class ResolvedWrapper:
    symbol: "SymbolRef"
    unit: "SourceUnit"
    declaration: ast.ClassDef


def http_callback_dispatch(call: ast.Call, context: PythonFileContext | None) -> bool:
    if context is None or not isinstance(call.func, ast.Name) or len(call.args) != 1 or call.keywords:
        return False
    if not isinstance(context.parents.get(call), ast.Await) or not isinstance(call.args[0], ast.Name):
        return False
    provenance = context.static_resource_provenance
    callback = provenance.binding(call.func.id, call)
    if not isinstance(callback, ast.arg) or (target := _callback_target(callback.annotation, context)) is None:
        return False
    receiver = call.args[0]
    constructor = provenance.constructor(receiver, call)
    return (
        constructor is not None
        and _stable_constructor(constructor, context)
        and _bounded_receiver(receiver, call, context)
        and _same_http_wrapper(target, constructor.func, receiver, call, context)
    )


def _callback_target(annotation: ast.expr | None, context: PythonFileContext) -> ast.expr | None:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return None
    if context.tree is None:
        return None
    imports = ImportIndex.from_tree(context.tree, module_scope_only=True)
    if not isinstance(annotation, ast.Subscript) or not imports.resolves(
        annotation.value, sources=_CALLABLE_SOURCES, symbol="Callable"
    ):
        return None
    if not isinstance(annotation.slice, ast.Tuple) or len(annotation.slice.elts) != _CALLABLE_ARITY:
        return None
    arguments = annotation.slice.elts[0]
    return arguments.elts[0] if isinstance(arguments, ast.List) and len(arguments.elts) == 1 else None


def _stable_constructor(constructor: ast.Call, context: PythonFileContext) -> bool:
    return _stable_reference(constructor.func, context)


def _stable_reference(expression: ast.expr, context: PythonFileContext) -> bool:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    provenance = context.static_resource_provenance
    binding = provenance.runtime_binding(root.id, expression) if isinstance(root, ast.Name) else None
    return (
        isinstance(root, ast.Name)
        and not provenance.dynamic_namespace
        and not provenance.wildcard
        and root.id not in provenance.mutated
        and isinstance(binding, ast.alias | ast.ClassDef)
        and all(_safe_import_read(read, context) for read in provenance.binding_reads(root.id, binding))
    )


def _safe_import_read(read: ast.Name, context: PythonFileContext) -> bool:
    expression: ast.AST = read
    parent = context.parents.get(expression)
    while isinstance(parent, ast.Attribute) and parent.value is expression:
        expression, parent = parent, context.parents.get(parent)
    return (
        _annotation_reference(expression, context)
        or (isinstance(parent, ast.Call) and parent.func is expression)
        or (isinstance(parent, ast.ClassDef) and expression in parent.decorator_list)
    )


def _annotation_reference(node: ast.AST, context: PythonFileContext) -> bool:
    owner = context.parents.get(node)
    while isinstance(owner, ast.expr):
        node, owner = owner, context.parents.get(owner)
    return (isinstance(owner, ast.arg | ast.AnnAssign) and owner.annotation is node) or (
        isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) and owner.returns is node
    )


def _bounded_receiver(receiver: ast.Name, call: ast.Call, context: PythonFileContext) -> bool:
    provenance = context.static_resource_provenance
    binding = provenance.binding(receiver.id, call)
    if binding is None or provenance.dynamic_namespace or receiver.id in provenance.mutated:
        return False
    return all(_receiver_read(read, receiver, context) for read in provenance.binding_reads(receiver.id, binding))


def _receiver_read(read: ast.Name, receiver: ast.Name, context: PythonFileContext) -> bool:
    if read is receiver:
        return True
    parent = context.parents.get(read)
    if isinstance(parent, ast.withitem) and parent.context_expr is read:
        return True
    return (
        isinstance(parent, ast.Attribute)
        and parent.value is read
        and parent.attr not in {"__setattr__", "__delattr__", "__getattribute__"}
        and isinstance(owner := context.parents.get(parent), ast.Call)
        and owner.func is parent
    )


def _same_http_wrapper(
    annotation: ast.expr, constructor: ast.expr, receiver: ast.Name, call: ast.Call, context: PythonFileContext
) -> bool:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- avoid the rule registry/context initialization cycle.

    project = context.session.project
    unit = project.unit(context.path) if project is not None else None
    if project is None or unit is None:
        return False
    declared = _resolve_wrapper(project, unit, annotation)
    constructed = _resolve_wrapper(project, unit, constructor)
    if declared is None or constructed is None or declared.symbol != constructed.symbol:
        return False
    source_unit = constructed.unit
    declaration = constructed.declaration
    if not context.session.nominal_project.owns_source(context.path, source_unit.path, context.session.first_party):
        return False
    source_context = PythonFileContext(source_unit.path, source_unit.source, context.session)
    if not _wrapper_decorators(declaration, source_context):
        return False
    return _active_native_factory(declaration, _resource_entries(receiver, call, context), source_context)


def _resource_entries(receiver: ast.Name, call: ast.Call, context: PythonFileContext) -> set[str]:
    binding = context.static_resource_provenance.binding(receiver.id, call)
    if binding is None:
        return set()
    entries = {"__init__"}
    bound_item = context.parents.get(binding)
    bound_owner = context.parents.get(bound_item) if isinstance(bound_item, ast.withitem) else None
    if context.static_resource_provenance.contains(bound_owner, call):
        entries.add("__aenter__" if isinstance(bound_owner, ast.AsyncWith) else "__enter__")
    for read in context.static_resource_provenance.binding_reads(receiver.id, binding):
        item = context.parents.get(read)
        owner = context.parents.get(item) if isinstance(item, ast.withitem) else None
        if context.static_resource_provenance.contains(owner, call):
            entries.add("__aenter__" if isinstance(owner, ast.AsyncWith) else "__enter__")
    return entries


def _wrapper_decorators(declaration: ast.ClassDef, context: PythonFileContext) -> bool:
    return (
        not declaration.bases
        and not declaration.keywords
        and declaration.name not in context.static_resource_provenance.mutated
        and all(
            _stable_reference(expression := decorator.func if isinstance(decorator, ast.Call) else decorator, context)
            and context.imports.resolved_qualified_name(expression)
            in {
                "attrs.define",
                "attrs.frozen",
                "attr.s",
                "dataclasses.dataclass",
                "typing.final",
                "typing_extensions.final",
            }
            for decorator in declaration.decorator_list
        )
    )


def _active_native_factory(declaration: ast.ClassDef, entries: set[str], context: PythonFileContext) -> bool:
    methods = {
        method.name: method for method in declaration.body if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    pending = list(entries)
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or (method := methods.get(name)) is None:
            continue
        seen.add(name)
        if method.decorator_list:
            continue
        if _returns_native_client(method, context):
            return True
        pending.extend(_unconditional_self_calls(method, context, methods))
    return False


def _unconditional_self_calls(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    methods: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> set[str]:
    called: set[str] = set()
    for statement in method.body:
        if isinstance(statement, ast.Raise):
            break
        if not isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign | ast.Return):
            continue
        called.update(
            node.func.attr
            for node in _eager_nodes(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and _function_owner(node, context) is method
            and (
                not isinstance(methods.get(node.func.attr), ast.AsyncFunctionDef)
                or isinstance(context.parents.get(node), ast.Await)
            )
        )
        if isinstance(statement, ast.Return):
            break
    return called


def _eager_nodes(node: ast.AST) -> list[ast.AST]:
    pending = [node]
    result: list[ast.AST] = []
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(_eager_children(current))
    return result


def _eager_children(node: ast.AST) -> list[ast.AST]:
    match node:
        case ast.Lambda() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return []
        case ast.BoolOp():
            return _boolean_operands(node)
        case ast.IfExp():
            return (
                [node.test, node.body if node.test.value else node.orelse]
                if isinstance(node.test, ast.Constant)
                else [node.test]
            )
        case ast.GeneratorExp() | ast.ListComp() | ast.SetComp() | ast.DictComp():
            return [node.generators[0].iter]
        case _:
            return children(node)


def _boolean_operands(node: ast.BoolOp) -> list[ast.AST]:
    operands: list[ast.AST] = []
    for value in node.values:
        operands.append(value)
        if not isinstance(value, ast.Constant):
            break
        if (isinstance(node.op, ast.And) and not value.value) or (isinstance(node.op, ast.Or) and value.value):
            break
    return operands


def _resolve_wrapper(project: ProjectIndexSet, unit: SourceUnit, expression: ast.expr) -> ResolvedWrapper | None:
    for _ in range(_MAX_REEXPORTS):
        if not _stable_export(unit, expression):
            return None
        symbol = project.resolve(unit, expression)
        if symbol is None:
            return None
        summary = project.class_for(unit, expression)
        if summary is not None:
            return _wrapper_declaration(project, summary.symbol)
        target = project.source_unit(symbol.module)
        if target is None or symbol.name not in target.imports:
            return None
        unit, expression = target, ast.Name(id=symbol.name)
    return None


def _wrapper_declaration(project: ProjectIndexSet, symbol: SymbolRef) -> ResolvedWrapper | None:
    unit = project.source_unit(symbol.module)
    if unit is None or unit.tree is None:
        return None
    declaration = next(
        (node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == symbol.name), None
    )
    return ResolvedWrapper(symbol, unit, declaration) if declaration is not None else None


def _stable_export(unit: SourceUnit, expression: ast.expr) -> bool:
    if unit.tree is None:
        return False
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    if root.id in unit.imports:
        return root.id not in imports.shadowed_names and len(_import_bindings(unit.tree, root.id)) == 1
    return (
        sum(
            (isinstance(node, ast.ClassDef) and node.name == root.id)
            or (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == root.id)
            for node in walk(unit.tree)
        )
        == 1
    )


def _import_bindings(tree: ast.Module, local: str) -> set[tuple[int, str | None, str | None]]:
    bindings: set[tuple[int, str | None, str | None]] = set()
    for node in tree.body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            bound = alias.asname or (alias.name if isinstance(node, ast.ImportFrom) else alias.name.partition(".")[0])
            if bound != local:
                continue
            bindings.add(
                (node.level, node.module, alias.name) if isinstance(node, ast.ImportFrom) else (0, alias.name, None)
            )
    return bindings


def _returns_native_client(method: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    if (
        method.decorator_list
        or method.returns is None
        or context.imports.resolved_qualified_name(method.returns) not in _NATIVE_CLIENTS
    ):
        return False
    members = [node for node in walk(method) if _function_owner(node, context) is method]
    native_fields = _native_fields(members, context)
    returns = [node for node in members if isinstance(node, ast.Return)]
    return bool(returns) and all(
        _native_constructor(node.value, context) or _returned_field(node.value) in native_fields for node in returns
    )


def _native_fields(members: list[ast.AST], context: PythonFileContext) -> set[str]:
    native: set[str] = set()
    unknown: set[str] = set()
    for node in members:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        fields = _assigned_fields(node)
        if _native_constructor(node.value, context):
            native.update(fields)
        elif node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            unknown.update(fields)
    return native - unknown


def _assigned_fields(node: ast.Assign | ast.AnnAssign) -> set[str]:
    return {
        target.attr
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
    }


def _native_constructor(expression: ast.expr | None, context: PythonFileContext) -> bool:
    return (
        isinstance(expression, ast.Call)
        and _stable_constructor(expression, context)
        and context.imports.resolved_qualified_name(expression.func) in _NATIVE_CLIENTS
    )


def _returned_field(expression: ast.expr | None) -> str | None:
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "self"
    ):
        return expression.attr
    return None


def _function_owner(node: ast.AST, context: PythonFileContext) -> ast.AST | None:
    owner = context.parents.get(node)
    while owner is not None and not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        owner = context.parents.get(owner)
    return owner
