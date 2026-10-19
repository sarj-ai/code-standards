from __future__ import annotations

import ast
from types import MappingProxyType
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


type Function = ast.FunctionDef | ast.AsyncFunctionDef
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
    return {name: method for name, method in result.items() if name not in ambiguous}


def upsert_pair(owner: ast.ClassDef, imports: ImportIndex) -> tuple[Function, Function] | None:
    declared = methods(owner)
    single, bulk = declared.get("upsert"), declared.get("upsert_many")
    if (
        single is None
        or bulk is None
        or isinstance(single, ast.AsyncFunctionDef) != isinstance(bulk, ast.AsyncFunctionDef)
    ):
        return None
    if any(
        imports.resolved_qualified_name(decorator) not in _NEUTRAL_DECORATORS
        for method in (single, bulk)
        for decorator in method.decorator_list
    ):
        return None
    one, many = method_parameters(single), method_parameters(bulk)
    if one is None or many is None or len(one) != 1 or len(many) != 1:
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
    return single, bulk


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
    if (
        isinstance(loop.iter, ast.List | ast.Tuple | ast.Set)
        and len(loop.iter.elts) <= 1
        and not any(isinstance(item, ast.Starred) for item in loop.iter.elts)
    ):
        return None
    value = loop.body[0].value
    awaited = isinstance(value, ast.Await)
    value = value.value if awaited else value
    return (value, awaited) if isinstance(value, ast.Call) else None


def depends_on_target(expression: ast.expr, target: ast.expr) -> bool:
    names = {node.id for node in walk(target) if isinstance(node, ast.Name)}
    return any(isinstance(node, ast.Name) and node.id in names for node in own_nodes(expression))


class StoreOwners:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context)
        self.project = context.session.project

    def receiver(self, expression: ast.expr, at: ast.AST) -> tuple[ast.ClassDef, ImportIndex] | None:
        if isinstance(expression, ast.Name):
            binding = self.provenance.binding(expression.id, at)
            if isinstance(binding, ast.arg) and binding.annotation is not None:
                return self.annotation(binding.annotation)
            return None
        if (
            not isinstance(expression, ast.Attribute)
            or not isinstance(expression.value, ast.Name)
            or expression.value.id != "self"
        ):
            return None
        if not isinstance(self.provenance.binding("self", at), ast.arg):
            return None
        annotation = self._injected_annotation(expression.attr, at)
        return self.annotation(annotation) if annotation is not None else None

    def _injected_annotation(self, attribute: str, at: ast.AST) -> ast.expr | None:
        parent = self.context.parents.get(at)
        while parent is not None and not isinstance(parent, ast.ClassDef):
            parent = self.context.parents.get(parent)
        if parent is None:
            return None
        constructor = methods(parent).get("__init__")
        if constructor is None:
            return None
        assignments = [
            node
            for method in methods(parent).values()
            for node in own_nodes(method)
            if _writes_self_attribute(node, attribute)
        ]
        if len(assignments) != 1:
            return None
        for statement in constructor.body:
            if (
                not isinstance(statement, ast.Assign)
                or not isinstance(statement.value, ast.Name)
                or assignments[0] not in statement.targets
            ):
                continue
            return _injected_parameter(constructor, statement.value, self.provenance)
        return None

    def annotation(self, expression: ast.expr | None) -> tuple[ast.ClassDef, ImportIndex] | None:
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
                return declaration, self.context.module_imports
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
        provenance = ResourceProvenance(definition)
        if provenance.binding(symbol.name, declaration) is not declaration or symbol.name in provenance.mutated:
            return None
        return declaration, definition.module_imports


def _writes_self_attribute(node: ast.AST, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == attribute
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store | ast.Del)
    )


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
