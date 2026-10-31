from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, bit_or_members, scope_bound_names
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._ast_position import ast_position
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_position import AstPosition
    from sarj_python_lint.rules._imports import ImportIndex
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type Function = ast.FunctionDef | ast.AsyncFunctionDef


class _MethodPair(NamedTuple):
    singleton: Function
    bulk: Function


_COLLECTIONS = frozenset(
    {
        "collections.abc.Collection",
        "collections.abc.Iterable",
        "collections.abc.Sequence",
        "typing.Collection",
        "typing.Iterable",
        "typing.Sequence",
        "typing.List",
    }
)
_NEUTRAL_DECORATORS = frozenset({"abc.abstractmethod", "typing.override", "typing_extensions.override"})
_READ_SEQUENCES = frozenset({"collections.abc.Sequence", "typing.Sequence", "typing.List"})
_READ_MAPPINGS = frozenset({"collections.abc.Mapping", "typing.Mapping", "typing.Dict"})
_STORE_MEMBERS = frozenset(
    {
        "upsert",
        "upsert_many",
        "create",
        "create_many",
        "insert",
        "insert_many",
        "update",
        "update_many",
        "delete",
        "delete_many",
        "get",
        "get_many",
        "get_by_ids",
        "__class__",
    }
)


def method_parameters(method: Function) -> list[ast.arg] | None:
    args = method.args
    positional = [*args.posonlyargs, *args.args]
    if not positional or positional[0].arg != "self":
        return None
    if args.vararg or args.kwarg or args.defaults or any(args.kw_defaults):
        return None
    return [*positional[1:], *args.kwonlyargs]


def methods(owner: ast.ClassDef) -> dict[str, Function]:
    result: dict[str, Function] = {}
    ambiguous: set[str] = set()
    for node in owner.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name in result:
                ambiguous.add(node.name)
            result[node.name] = node
        else:
            ambiguous.update(scope_bound_names([node]))
    ambiguous.update(
        node.attr
        for method in result.values()
        for node in own_nodes(method)
        if isinstance(node, ast.Attribute) and _writes_self_attribute(node, node.attr)
    )
    return {name: method for name, method in result.items() if name not in ambiguous}


def instance_member_bindings(owner: ast.ClassDef, context: PythonFileContext) -> set[str]:
    bindings: set[str] = set()
    for method in owner.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in own_nodes(method):
            if isinstance(node, ast.Attribute) and _writes_self_attribute(node, node.attr):
                bindings.add(node.attr)
            elif (member := _builtin_member_binding(node, method, context)) is not None:
                bindings.add(member)
    return bindings


def _builtin_member_binding(node: ast.AST, method: Function, context: PythonFileContext) -> str | None:
    if not isinstance(node, ast.Call) or node.keywords:
        return None
    provenance = context.static_resource_provenance
    if provenance.wildcard or provenance.dynamic_namespace:
        return None
    name = provenance.runtime_import_name(node.func)
    if (
        isinstance(node.func, ast.Name)
        and node.func.id in {"setattr", "delattr"}
        and context.imports.builtin_is_unshadowed(node.func.id)
        and provenance.runtime_binding(node.func.id, node.func) is None
        and provenance.builtin_namespace_untouched
    ):
        name = "builtins." + node.func.id
    arity = {"builtins.setattr": 3, "builtins.delattr": 2}.get(name or "")
    if arity is None or len(node.args) != arity:
        return None
    receiver, member = node.args[:2]
    if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
        return None
    positional = [*method.args.posonlyargs, *method.args.args]
    if (
        not positional
        or positional[0].arg != "self"
        or not isinstance(receiver, ast.Name)
        or provenance.runtime_binding(receiver.id, receiver) is not positional[0]
    ):
        return None
    return member.value


def decorator_name(
    expression: ast.expr, declaration: Function | ast.ClassDef, owner: ast.ClassDef | ast.Module, imports: ImportIndex
) -> str | None:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return None
    for statement in owner.body:
        if statement is declaration:
            return imports.resolved_qualified_name(expression)
        if _evaluation_writes(statement, root.id, names=isinstance(owner, ast.ClassDef)):
            return None
    return None


def _evaluation_writes(statement: ast.stmt, name: str, *, names: bool) -> bool:
    pending: list[tuple[ast.AST, bool]] = [(statement, names)]
    while pending:
        node, names = pending.pop()
        if _writes_decorator_root(node, name, names=names):
            return True
        pending.extend(_evaluation_children(node, names=names))
    return False


def _writes_decorator_root(node: ast.AST, name: str, *, names: bool) -> bool:
    match node:
        case ast.Name(id=bound, ctx=ast.Store() | ast.Del()) if names:
            return bound == name
        case ast.Attribute(ctx=ast.Store() | ast.Del()):
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            return isinstance(root, ast.Name) and root.id == name
        case (
            ast.FunctionDef()
            | ast.AsyncFunctionDef()
            | ast.ClassDef()
            | ast.ExceptHandler()
            | ast.MatchAs()
            | ast.MatchStar()
        ) if names:
            return node.name == name
        case ast.Import() | ast.ImportFrom() if names:
            return any((alias.asname or alias.name.partition(".")[0]) == name for alias in node.names)
        case ast.Global() | ast.Nonlocal():
            return name in node.names
        case ast.MatchMapping() if names:
            return node.rest == name
        case _:
            return False


def _evaluation_children(node: ast.AST, *, names: bool) -> Iterable[tuple[ast.AST, bool]]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            expressions = [*node.decorator_list, *node.args.defaults]
            expressions.extend(default for default in node.args.kw_defaults if default is not None)
        case ast.Lambda():
            expressions = list(node.args.defaults)
            expressions.extend(default for default in node.args.kw_defaults if default is not None)
        case ast.ClassDef():
            expressions = [*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)]
            return [(child, names) for child in expressions] + [(child, False) for child in node.body]
        case ast.Import() | ast.ImportFrom() | ast.AnnAssign(value=None):
            return []
        case ast.comprehension():
            expressions = [node.iter, *node.ifs]
        case _:
            return [(child, names) for child in ast.iter_child_nodes(node)]
    return [(child, names) for child in expressions]


def _decorator_imports(context: PythonFileContext, owner: ast.ClassDef) -> ImportIndex:
    imports = context.module_imports
    if context.tree is None:
        return imports
    preceding = context.tree.body[: context.tree.body.index(owner)]
    return replace(
        imports,
        bindings=MappingProxyType(
            {
                name: target
                for name, target in imports.bindings.items()
                if not any(_evaluation_writes(statement, name, names=False) for statement in preceding)
            }
        ),
    )


def upsert_pair(owner: ast.ClassDef, imports: ImportIndex) -> tuple[Function, Function] | None:
    return compatible_collection_pair(owner, imports, "upsert", "upsert_many")


def compatible_collection_pair(
    owner: ast.ClassDef, imports: ImportIndex, singleton_name: str, bulk_name: str
) -> _MethodPair | None:
    pair = _method_pair(owner, imports, singleton_name, bulk_name)
    if pair is None:
        return None
    single, bulk = pair
    one, many = method_parameters(single), method_parameters(bulk)
    if one is None or many is None:
        return None
    item = collection_item(many[0].annotation, imports)
    result = collection_item(bulk.returns, imports)
    if (
        item is None
        or result is None
        or not same_type(one[0].annotation, item)
        or not same_type(single.returns, result)
    ):
        return None
    return pair


def read_pair(owner: ast.ClassDef, imports: ImportIndex, bulk_name: str) -> _MethodPair | None:
    pair = _method_pair(owner, imports, "get", bulk_name)
    if pair is None:
        return None
    single, bulk = pair
    one, many = method_parameters(single), method_parameters(bulk)
    if one is None or many is None:
        return None
    item = collection_item(many[0].annotation, imports)
    result = _read_result(bulk.returns, one[0].annotation, imports)
    if (
        item is None
        or result is None
        or not same_type(one[0].annotation, item)
        or not same_type(_read_scalar(single.returns, imports), result)
    ):
        return None
    return pair


def _read_scalar(annotation: ast.expr | None, imports: ImportIndex) -> ast.expr | None:
    annotation = AnnotationSemantics.parse(annotation)
    if isinstance(annotation, ast.Subscript) and imports.resolved_qualified_name(annotation.value) in {
        "typing.Optional",
        "typing_extensions.Optional",
    }:
        return annotation.slice if not isinstance(annotation.slice, ast.Tuple) else None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        match bit_or_members(annotation):
            case [value, ast.Constant(value=None)] | [ast.Constant(value=None), value]:
                return None if isinstance(value, ast.Constant) and value.value is None else value
            case _:
                return None
    return None if isinstance(annotation, ast.Constant) and annotation.value is None else annotation


def _read_result(annotation: ast.expr | None, key: ast.expr | None, imports: ImportIndex) -> ast.expr | None:
    annotation = AnnotationSemantics.parse(annotation)
    if not isinstance(annotation, ast.Subscript):
        return None
    container = annotation.value
    name = imports.resolved_qualified_name(container)
    if isinstance(container, ast.Name) and imports.builtin_is_unshadowed(container.id):
        name = "builtins." + container.id
    if name in {*_READ_SEQUENCES, "builtins.list"}:
        return annotation.slice if not isinstance(annotation.slice, ast.Tuple) else None
    if name in {*_READ_MAPPINGS, "builtins.dict"}:
        match annotation.slice:
            case ast.Tuple(elts=[mapping_key, value]) if same_type(key, mapping_key):
                return value
            case _:
                pass
    return None


def _method_pair(owner: ast.ClassDef, imports: ImportIndex, singleton_name: str, bulk_name: str) -> _MethodPair | None:
    if owner.keywords:
        return None
    declared = methods(owner)
    single, bulk = declared.get(singleton_name), declared.get(bulk_name)
    if (
        single is None
        or bulk is None
        or isinstance(single, ast.AsyncFunctionDef) != isinstance(bulk, ast.AsyncFunctionDef)
    ):
        return None
    if any(
        decorator_name(decorator, method, owner, imports) not in _NEUTRAL_DECORATORS
        for method in (single, bulk)
        for decorator in method.decorator_list
    ):
        return None
    one, many = method_parameters(single), method_parameters(bulk)
    if one is None or many is None or len(one) != 1 or len(many) != 1:
        return None
    return _MethodPair(single, bulk)


def collection_item(annotation: ast.expr | None, imports: ImportIndex) -> ast.expr | None:
    annotation = AnnotationSemantics(imports, MappingProxyType({})).parse(annotation)
    if not isinstance(annotation, ast.Subscript):
        return None
    container = annotation.value
    if isinstance(container, ast.Name) and container.id == "list" and imports.builtin_is_unshadowed("list"):
        return annotation.slice
    if imports.resolved_qualified_name(container) in _COLLECTIONS:
        return annotation.slice
    return None


def same_type(left: ast.expr | None, right: ast.expr | None) -> bool:
    left, right = AnnotationSemantics.parse(left), AnnotationSemantics.parse(right)
    return (
        left is not None
        and right is not None
        and ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)
    )


def own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    pending = [node]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(
            child
            for child in reversed(list(ast.iter_child_nodes(current)))
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda)
        )


def discarded_call(loop: ast.For) -> tuple[ast.Call, bool] | None:
    if loop.orelse or len(loop.body) != 1 or not isinstance(loop.body[0], ast.Expr):
        return None
    if known_single_iteration(loop.iter):
        return None
    value = loop.body[0].value
    awaited = isinstance(value, ast.Await)
    value = value.value if awaited else value
    return (value, awaited) if isinstance(value, ast.Call) else None


def known_single_iteration(iterable: ast.expr) -> bool:
    match iterable:
        case ast.List(elts=items) | ast.Tuple(elts=items) | ast.Set(elts=items):
            return len(items) <= 1 and not any(isinstance(item, ast.Starred) for item in items)
        case ast.Dict(keys=keys):
            return len(keys) <= 1 and None not in keys
        case ast.Constant(value=str() | bytes() as value):
            return len(value) <= 1
        case _:
            return False


def depends_on_target(expression: ast.expr, target: ast.expr) -> bool:
    names = _target_names(target)
    return any(name in names for name in _free_names(expression))


def _target_names(target: ast.expr) -> frozenset[str]:
    return frozenset(node.id for node in walk(target) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))


def _free_names(expression: ast.expr) -> Iterator[str]:
    pending: list[tuple[ast.AST, frozenset[str]]] = [(expression, frozenset())]
    while pending:
        node, shadowed = pending.pop()
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in shadowed:
            yield node.id
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                continue
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                pending.extend(_comprehension_scopes(node, shadowed))
                continue
            case _:
                pass
        pending.extend((child, shadowed) for child in ast.iter_child_nodes(node))


def _comprehension_scopes(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, shadowed: frozenset[str]
) -> Iterator[tuple[ast.AST, frozenset[str]]]:
    for generator in node.generators:
        yield generator.iter, shadowed
        shadowed |= _target_names(generator.target)
        yield from ((condition, shadowed) for condition in generator.ifs)
    values = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
    yield from ((value, shadowed) for value in values)


@dataclass(frozen=True, slots=True)
class _ReceiverOrigin:
    binding: ast.AST
    attribute: str | None = None


class _ReceiverAliases:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = context.static_resource_provenance

    def origins(self, expression: ast.expr, remaining: int = 16) -> frozenset[_ReceiverOrigin] | None:
        if remaining == 0:
            return None
        if isinstance(expression, ast.Attribute):
            return self._injected_origin(expression)
        if not isinstance(expression, ast.Name):
            return frozenset()
        bindings = self._preceding_bindings(expression)
        origins: set[_ReceiverOrigin] = set()
        for binding in bindings:
            match binding:
                case ast.arg():
                    origins.add(_ReceiverOrigin(binding))
                case ast.Name():
                    assignment = self.context.parents.get(binding)
                    if (
                        isinstance(assignment, ast.Assign | ast.AnnAssign)
                        and assignment.value is not None
                        and binding
                        in (assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target])
                    ):
                        assigned = self.origins(assignment.value, remaining - 1)
                        if assigned is None:
                            return None
                        origins.update(assigned)
                case _:
                    pass
        return frozenset(origins)

    def replaced(self, origin: _ReceiverOrigin, nodes: Iterable[ast.AST]) -> bool:
        return any(
            (origins := self.origins(target)) is None or origin in origins
            for node in nodes
            if (target := _replaced_receiver(node, self.context.imports)) is not None
        )

    def _preceding_bindings(self, expression: ast.Name) -> tuple[ast.AST, ...]:
        scope = self.provenance.scope(expression)
        while scope is not None:
            bindings = self.provenance.bindings.get(scope, {}).get(expression.id)
            if bindings:
                return self._reaching_bindings(bindings, expression, scope)
            scope = self.provenance.scope(scope)
        return ()

    def _reaching_bindings(
        self, bindings: tuple[ast.AST, ...], expression: ast.Name, scope: ast.AST
    ) -> tuple[ast.AST, ...]:
        preceding = sorted(
            (binding for binding in bindings if self._precedes_read(binding, expression)), key=_source_position
        )
        # A definite local overwrite discards earlier possible objects; conditional
        # writes retain all possible origins until another definite overwrite.
        start = 0
        for index, binding in enumerate(preceding):
            statement = self.context.parents.get(binding)
            if (
                isinstance(binding, ast.arg)
                or self.context.parents.get(binding) is scope
                or (
                    isinstance(statement, ast.Assign | ast.AnnAssign | ast.Delete | ast.Import | ast.ImportFrom)
                    and self.context.parents.get(statement) is scope
                )
            ):
                start = index
        return tuple(preceding[start:])

    def _precedes_read(self, binding: ast.AST, expression: ast.Name) -> bool:
        assignment = self.context.parents.get(binding)
        return _source_position(binding) < _source_position(expression) and not (
            isinstance(assignment, ast.Assign | ast.AnnAssign)
            and (assignment.value is None or assignment.value is expression)
        )

    def _injected_origin(self, expression: ast.Attribute) -> frozenset[_ReceiverOrigin]:
        if not isinstance(expression.value, ast.Name) or expression.value.id != "self":
            return frozenset()
        binding = self.provenance.binding("self", expression)
        arguments = self.context.parents.get(binding) if binding is not None else None
        method = self.context.parents.get(arguments) if arguments is not None else None
        owner = self.context.parents.get(method) if method is not None else None
        if (
            isinstance(binding, ast.arg)
            and isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
            and isinstance(owner, ast.ClassDef)
            and [*method.args.posonlyargs, *method.args.args][:1] == [binding]
        ):
            return frozenset({_ReceiverOrigin(owner, expression.attr)})
        return frozenset()


def _source_position(node: ast.AST) -> AstPosition:
    return ast_position(node, missing=-1)


class StoreOwners:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = context.static_resource_provenance
        self.project = context.session.project
        self.aliases = _ReceiverAliases(context)

    def receiver(self, expression: ast.expr, at: ast.AST) -> tuple[ast.ClassDef, ImportIndex] | None:
        if isinstance(expression, ast.Name):
            binding = self.provenance.binding(expression.id, at)
            if (
                isinstance(binding, ast.arg)
                and binding.annotation is not None
                and not self._receiver_method_replaced(binding)
            ):
                return self.annotation(binding.annotation)
            return None
        if (
            not isinstance(expression, ast.Attribute)
            or not isinstance(expression.value, ast.Name)
            or expression.value.id != "self"
        ):
            return None
        binding = self.provenance.binding("self", at)
        if not isinstance(binding, ast.arg):
            return None
        arguments = self.context.parents.get(binding)
        method = self.context.parents.get(arguments) if arguments is not None else None
        owner = self.context.parents.get(method) if method is not None else None
        if (
            not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
            or not isinstance(owner, ast.ClassDef)
            or not (positional := [*method.args.posonlyargs, *method.args.args])
            or positional[0] is not binding
            or any(
                decorator_name(decorator, method, owner, self.context.module_imports) not in _NEUTRAL_DECORATORS
                for decorator in method.decorator_list
            )
        ):
            return None
        annotation = self._injected_annotation(expression.attr, at)
        return self.annotation(annotation) if annotation is not None else None

    def _receiver_method_replaced(self, binding: ast.arg) -> bool:
        return self.aliases.replaced(_ReceiverOrigin(binding), self.context.nodes(ast.Attribute, ast.Call))

    def _injected_annotation(self, attribute: str, at: ast.AST) -> ast.expr | None:
        parent = self.context.parents.get(at)
        while parent is not None and not isinstance(parent, ast.ClassDef):
            parent = self.context.parents.get(parent)
        if parent is None:
            return None
        constructor = _injection_constructor(parent, attribute)
        if constructor is None:
            return None
        declared_methods = [node for node in parent.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
        assignments = [
            node for method in declared_methods for node in own_nodes(method) if _writes_self_attribute(node, attribute)
        ]
        if len(assignments) != 1 or self.aliases.replaced(
            _ReceiverOrigin(parent, attribute), (node for method in declared_methods for node in own_nodes(method))
        ):
            return None
        value = _constructor_injected_value(constructor, assignments[0])
        return _injected_parameter(constructor, value, self.provenance) if value is not None else None

    def annotation(self, expression: ast.expr | None) -> tuple[ast.ClassDef, ImportIndex] | None:
        if self.provenance.dynamic_namespace or self.provenance.wildcard:
            return None
        original = expression
        expression = AnnotationSemantics(self.context.module_imports, MappingProxyType({})).parse(expression)
        if expression is None or self.context.tree is None:
            return None
        root = expression.value if isinstance(expression, ast.Attribute) else expression
        if (
            not isinstance(root, ast.Name)
            or original is None
            or not isinstance(self.provenance.binding(root.id, original), ast.ClassDef | ast.alias)
        ):
            return None
        if root.id in self.provenance.mutated:
            return None
        if isinstance(expression, ast.Name):
            declaration = _declared_class(self.context.tree, expression.id)
            if declaration is not None:
                return declaration, _decorator_imports(self.context, declaration)
        return self._imported_annotation(expression)

    def _imported_annotation(self, expression: ast.expr) -> tuple[ast.ClassDef, ImportIndex] | None:
        if self.project is None or self.context.tree is None:
            return None
        unit = self.project.unit_or_source(self.context.path, self.context.source, self.context.tree)
        symbol = ProjectIndexSet.resolve(unit, expression) if unit is not None else None
        owner = self.project.source_unit(symbol.module) if symbol is not None else None
        if symbol is None or owner is None or owner.tree is None or is_generated(owner.path, owner.source):
            return None
        declaration = _declared_class(owner.tree, symbol.name)
        if declaration is None:
            return None
        from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- defer to avoid the rule registry's context import cycle.

        definition = PythonFileContext(owner.path, owner.source, self.context.session)
        provenance = definition.static_resource_provenance
        if (
            provenance.dynamic_namespace
            or provenance.wildcard
            or provenance.binding(symbol.name, declaration) is not declaration
            or symbol.name in provenance.mutated
        ):
            return None
        return declaration, _decorator_imports(definition, declaration)


def _writes_self_attribute(node: ast.AST, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store | ast.Del)
    )


def _injection_constructor(owner: ast.ClassDef, attribute: str) -> Function | None:
    runtime_statements = [
        statement for statement in owner.body if not (isinstance(statement, ast.AnnAssign) and statement.value is None)
    ]
    return None if attribute in scope_bound_names(runtime_statements) else methods(owner).get("__init__")


def _constructor_injected_value(constructor: Function, assignment: ast.AST) -> ast.Name | None:
    for statement in constructor.body:
        match statement:
            case ast.Assign(value=ast.Name() as value, targets=targets) if assignment in targets:
                return value
            case ast.AnnAssign(value=ast.Name() as value, target=target) if target is assignment:
                return value
            case _:
                pass
    return None


def _replaced_receiver(node: ast.AST, imports: ImportIndex) -> ast.expr | None:
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del) and node.attr in _STORE_MEMBERS:
        return node.value
    if not isinstance(node, ast.Call) or node.keywords:
        return None
    name = imports.resolved_qualified_name(node.func)
    if isinstance(node.func, ast.Name) and imports.builtin_is_unshadowed(node.func.id):
        name = "builtins." + node.func.id
    required = {"builtins.setattr": 3, "builtins.delattr": 2}.get(name or "")
    if required is None or len(node.args) != required:
        return None
    member = node.args[1]
    return node.args[0] if isinstance(member, ast.Constant) and member.value in _STORE_MEMBERS else None


def _injected_parameter(constructor: Function, value: ast.Name, provenance: ResourceProvenance) -> ast.expr | None:
    parameter = next(
        (
            arg
            for arg in (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs)
            if arg.arg == value.id
        ),
        None,
    )
    if parameter is None or provenance.binding(parameter.arg, value) is not parameter:
        return None
    return parameter.annotation


def _declared_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    candidates = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    return candidates[0] if len(candidates) == 1 and not candidates[0].decorator_list else None


def sql_query(node: ast.expr, imports: ImportIndex) -> exp.Expr | None:
    if (
        isinstance(node, ast.Call)
        and imports.resolved_qualified_name(node.func) == "psycopg.sql.SQL"
        and len(node.args) == 1
        and not node.keywords
    ):
        node = node.args[0]
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    try:
        statements = sqlglot.parse(node.value, read="postgres")
    except SqlglotError:
        return None
    return statements[0] if len(statements) == 1 else None


def executed_queries(method: Function, imports: ImportIndex) -> list[exp.Expr]:
    queries: list[exp.Expr] = []
    calls = [
        node
        for statement in method.body
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for node in own_nodes(statement)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
    ]
    for call in calls:
        if not call.args or (query := sql_query(call.args[0], imports)) is None:
            return []
        queries.append(query)
    return queries


def sql_arg(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)


def sql_args(node: exp.Expr, key: str) -> tuple[exp.Expr, ...]:
    return tuple(child for child in node.iter_expressions() if child.arg_key == key)


def sql_identifier(node: exp.Expr | None) -> str | None:
    if isinstance(node, exp.Column):
        node = sql_arg(node, "this")
    if not isinstance(node, exp.Identifier):
        return None
    return node.name if node.quoted else node.name.lower()


def sql_table(node: exp.Expr | None) -> tuple[str | None, ...] | None:
    if not isinstance(node, exp.Table) or sql_arg(node, "alias") is not None:
        return None
    return tuple(
        sql_identifier(value) if (value := sql_arg(node, key)) is not None else None
        for key in ("catalog", "db", "this")
    )
