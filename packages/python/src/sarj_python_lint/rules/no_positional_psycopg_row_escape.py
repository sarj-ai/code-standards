from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path


_CONNECTIONS = frozenset({"AsyncConnection", "Connection"})
_FETCH_METHODS = frozenset({"fetchall", "fetchmany", "fetchone"})
_POOLS = frozenset({"AsyncConnectionPool", "ConnectionPool"})
_PSYCOPG = frozenset({"psycopg"})
_PSYCOPG_POOL = frozenset({"psycopg_pool"})
_PSYCOPG_ROWS = frozenset({"psycopg.rows"})
_SAFE_FACTORIES = frozenset({"class_row", "dict_row", "kwargs_row", "namedtuple_row", "scalar_row"})
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_TYPING = frozenset({"typing"})
_MUTATING_METHODS = frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort", "update"})


class _Shape(StrEnum):
    NAMED_OR_SCALAR = "named-or-scalar"
    POSITIONAL = "positional"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class _Cursor:
    call: ast.Call
    name: str
    body: list[ast.stmt]
    inherited_shape: _Shape


@final
class NoPositionalPsycopgRowEscape(Rule):
    id = "no-positional-psycopg-row-escape"
    code = "SARJ414"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        aliases=("require-validated-row-factory",),
        summary="A positional Psycopg record must not escape its function unchanged.",
        rationale=(
            "Returning a tuple-shaped database record couples callers to selected-column order. A named row factory "
            "keeps the database boundary explicit; scalar and locally transformed results remain valid."
        ),
        remediation=(
            "For a returned record, use `row_factory=class_row(Model)` (prefer a validating model). Use `scalar_row` "
            "for scalar projections, or consume and transform a positional row inside the store."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only import- or annotation-proven Psycopg cursors with a proven positional factory are inspected.",
            "Direct fetch returns and unchanged local aliases are followed within one cursor context; iteration and helper-indirected flows are excluded.",
            "Unknown, custom, inherited, or branch-dependent row factories are intentionally not inferred.",
            "Test, generated, and migration files are excluded; exceptional record contracts require an exact suppression.",
        ),
        examples=(
            RuleExample(
                example_id="escaping-positional-record",
                title="A positional database record escapes unchanged",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'import psycopg\n\nasync def load(dsn: str):\n    async with await psycopg.AsyncConnection.connect(dsn) as conn:\n        async with conn.cursor() as cursor:\n            await cursor.execute("SELECT id, state FROM task")\n            return await cursor.fetchone()\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-record-factory",
                title="A returned record has a named row contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        'from psycopg import AsyncConnection\nfrom psycopg.rows import class_row\nfrom pydantic import BaseModel\n\nclass TaskRow(BaseModel):\n    id: str\n    state: str\n\nasync def load(conn: AsyncConnection[tuple[object, ...]]):\n    async with conn.cursor(row_factory=class_row(TaskRow)) as cursor:\n        await cursor.execute("SELECT id, state FROM task")\n        return await cursor.fetchone()\n',
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_generated(path, source)
            or is_test_path(path)
            or is_test_support_path(path)
            or "migrations" in {part.lower() for part in path.parts}
        ):
            return []
        if ".cursor" not in source or not any(f".{method}" in source for method in _FETCH_METHODS):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        source_lines = source.splitlines()
        class_attrs = _class_connection_attributes(tree, imports)
        diagnostics: list[Diagnostic] = []
        for function, owner in _functions(tree):
            shadowed = _scope_bindings(function)
            for cursor in _cursors(
                function,
                owner,
                imports=imports,
                class_attrs=class_attrs,
                shadowed=shadowed,
            ):
                for fetch in _escaping_fetches(cursor.body, cursor.name):
                    shape = _cursor_shape(cursor, fetch, imports, shadowed)
                    if shape is not _Shape.POSITIONAL or is_suppressed(source_lines, cursor.call.lineno, self.code):
                        continue
                    if is_suppressed(source_lines, fetch.lineno, self.code):
                        continue
                    diagnostics.append(
                        Diagnostic(
                            path=path,
                            line=cursor.call.lineno,
                            col=cursor.call.col_offset + 1,
                            code=self.code,
                            severity=Severity.WARNING,
                            message=(
                                "this positional Psycopg record escapes unchanged; return a named `class_row(Model)` "
                                "record, use `scalar_row` for a scalar, or transform the tuple locally"
                            ),
                        )
                    )
                    break
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _functions(tree: ast.Module) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None]]:
    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            yield statement, None
        elif isinstance(statement, ast.ClassDef):
            for child in statement.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield child, statement


def _class_connection_attributes(tree: ast.Module, imports: ImportIndex) -> dict[tuple[int, str], _Shape]:
    candidates: dict[tuple[int, str], list[_Shape]] = {}
    counts: Counter[tuple[int, str]] = Counter()
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        initializers = [
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "__init__"
        ]
        if len(initializers) != 1:
            continue
        init = initializers[0]
        parameters = _parameter_annotations(init)
        properties = _property_names(cls)
        for method in (node for node in cls.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)):
            for node in _scope_nodes(method.body):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Store | ast.Del)
                ):
                    counts[cls.lineno, node.attr] += 1
                elif isinstance(node, ast.Call) and (attribute := _self_setattr_name(node)) is not None:
                    counts[cls.lineno, attribute] += 1
        for index, node in enumerate(init.body):
            match node:
                case ast.Assign(
                    targets=[ast.Attribute(value=ast.Name(id="self"), attr=attribute)],
                    value=ast.Name(id=parameter),
                ) if (
                    parameter in parameters
                    and not _can_return_before(init.body[:index])
                    and not _is_rebound_before(parameter, init.body[:index])
                ):
                    if attribute in properties:
                        continue
                    shape = _pool_annotation_shape(parameters[parameter], imports)
                    if shape is not None:
                        candidates.setdefault((cls.lineno, attribute), []).append(shape)
                case _:
                    pass
    return {key: shapes[0] for key, shapes in candidates.items() if len(shapes) == 1 and counts[key] == 1}


def _can_return_before(statements: Iterable[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Return) for node in _scope_nodes(statements))


def _self_setattr_name(call: ast.Call) -> str | None:
    match call:
        case ast.Call(
            func=ast.Name(id="setattr"),
            args=[ast.Name(id="self"), ast.Constant(value=attribute), *_],
        ) if isinstance(attribute, str):
            return attribute
        case _:
            return None


def _is_rebound_before(name: str, statements: Iterable[ast.stmt]) -> bool:
    return any(name in _same_scope_bindings(statement) for statement in statements)


def _property_names(cls: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        node.name
        for node in cls.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            (isinstance(decorator, ast.Name) and decorator.id == "property")
            or (isinstance(decorator, ast.Attribute) and decorator.attr == "property")
            for decorator in node.decorator_list
        )
    )


def _parameter_annotations(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.expr]:
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    return {argument.arg: argument.annotation for argument in arguments if argument.annotation is not None}


def _cursors(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    *,
    imports: ImportIndex,
    class_attrs: dict[tuple[int, str], _Shape],
    shadowed: frozenset[str],
) -> Iterator[_Cursor]:
    yield from _walk_cursors(
        function.body,
        owner,
        imports=imports,
        visible=_initial_bindings(function, imports),
        class_attrs=class_attrs,
        invalidated_attrs=frozenset(),
        shadowed=shadowed,
    )


def _initial_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex
) -> dict[str, _Shape]:
    result: dict[str, _Shape] = {}
    for name, annotation in _parameter_annotations(function).items():
        shape = _connection_annotation_shape(annotation, imports)
        if shape is None:
            shape = _pool_annotation_shape(annotation, imports)
        if shape is not None:
            result[name] = shape
    return result


def _walk_cursors(
    statements: list[ast.stmt],
    owner: ast.ClassDef | None,
    *,
    imports: ImportIndex,
    visible: dict[str, _Shape],
    class_attrs: dict[tuple[int, str], _Shape],
    invalidated_attrs: frozenset[str],
    shadowed: frozenset[str],
) -> Iterator[_Cursor]:
    current = dict(visible)
    current_invalidated = set(invalidated_attrs)
    for statement in statements:
        _invalidate_reassigned_bindings(statement, current)
        current_invalidated.update(_assigned_self_attributes(statement))
        if isinstance(statement, ast.With | ast.AsyncWith):
            nested = dict(current)
            for item in statement.items:
                if not isinstance(item.optional_vars, ast.Name):
                    continue
                connection_shape = _connection_context_shape(item.context_expr, imports, nested, shadowed)
                context_call = _as_call(item.context_expr)
                if (
                    connection_shape is None
                    and context_call is not None
                    and isinstance(context_call.func, ast.Attribute)
                    and context_call.func.attr == "connection"
                ):
                    connection_shape = _receiver_shape(
                        context_call.func.value,
                        owner,
                        nested,
                        class_attrs,
                        current_invalidated,
                    )
                if connection_shape is not None:
                    nested[item.optional_vars.id] = connection_shape
                    continue
                call = _as_call(item.context_expr)
                if call is None or not isinstance(call.func, ast.Attribute) or call.func.attr != "cursor":
                    continue
                inherited = _receiver_shape(call.func.value, owner, nested, class_attrs, current_invalidated)
                explicit = _explicit_factory_shape(call, imports, shadowed)
                if explicit is _Shape.UNKNOWN and _has_explicit_factory(call):
                    inherited = _Shape.UNKNOWN
                elif explicit is not None:
                    inherited = explicit
                if inherited is not _Shape.UNKNOWN:
                    yield _Cursor(call, item.optional_vars.id, statement.body, inherited)
            yield from _walk_cursors(
                statement.body,
                owner,
                imports=imports,
                visible=nested,
                class_attrs=class_attrs,
                invalidated_attrs=frozenset(current_invalidated),
                shadowed=shadowed,
            )
            continue
        for block in _child_statement_blocks(statement):
            yield from _walk_cursors(
                block,
                owner,
                imports=imports,
                visible=current,
                class_attrs=class_attrs,
                invalidated_attrs=frozenset(current_invalidated),
                shadowed=shadowed,
            )


def _invalidate_reassigned_bindings(statement: ast.stmt, visible: dict[str, _Shape]) -> None:
    for name in _same_scope_bindings(statement):
        visible.pop(name, None)
    for node in ast.walk(statement):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "row_factory"
            and isinstance(node.value, ast.Name)
            and isinstance(node.ctx, ast.Store)
        ):
            visible.pop(node.value.id, None)
        elif isinstance(node, ast.Call):
            target = _setattr_row_factory_target(node)
            if target is not None:
                visible.pop(target, None)


class _BindingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store | ast.Del):
            self.names.add(node.id)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    @override
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    @override
    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    @override
    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    @override
    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


def _same_scope_bindings(statement: ast.stmt) -> frozenset[str]:
    visitor = _BindingVisitor()
    visitor.visit(statement)
    return frozenset(visitor.names)


def _assigned_self_attributes(statement: ast.stmt) -> frozenset[str]:
    return frozenset(
        node.attr
        for node in _scope_nodes((statement,))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store | ast.Del)
    )


def _child_statement_blocks(statement: ast.stmt) -> Iterator[list[ast.stmt]]:
    match statement:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            yield statement.body
            yield statement.orelse
        case ast.Try() | ast.TryStar():
            yield statement.body
            yield statement.orelse
            yield statement.finalbody
            for handler in statement.handlers:
                yield handler.body
        case ast.Match():
            for case in statement.cases:
                yield case.body
        case _:
            return


def _connection_context_shape(
    expression: ast.expr,
    imports: ImportIndex,
    visible: dict[str, _Shape],
    shadowed: frozenset[str],
) -> _Shape | None:
    call = _as_call(expression)
    if call is None:
        return None
    root = _root_name(call.func)
    if root not in shadowed and (
        imports.resolves(call.func, sources=_PSYCOPG, symbol="connect")
        or _resolves_connection_connect(call.func, imports)
    ):
        return _connect_call_shape(call, imports, shadowed)
    if isinstance(call.func, ast.Attribute) and call.func.attr == "connection" and isinstance(call.func.value, ast.Name):
        return visible.get(call.func.value.id)
    return None


def _resolves_connection_connect(node: ast.expr, imports: ImportIndex) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "connect"
        and any(imports.resolves(node.value, sources=_PSYCOPG, symbol=symbol) for symbol in _CONNECTIONS)
    )


def _connect_call_shape(call: ast.Call, imports: ImportIndex, shadowed: frozenset[str]) -> _Shape:
    explicit = _explicit_factory_shape(call, imports, shadowed)
    if explicit is not None:
        return explicit
    return _Shape.UNKNOWN if any(keyword.arg is None for keyword in call.keywords) else _Shape.POSITIONAL


def _receiver_shape(
    receiver: ast.expr,
    owner: ast.ClassDef | None,
    visible: dict[str, _Shape],
    class_attrs: dict[tuple[int, str], _Shape],
    invalidated_attrs: set[str],
) -> _Shape:
    if isinstance(receiver, ast.Name):
        return visible.get(receiver.id, _Shape.UNKNOWN)
    if owner is not None and isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) and receiver.value.id == "self":
        if receiver.attr in invalidated_attrs:
            return _Shape.UNKNOWN
        return class_attrs.get((owner.lineno, receiver.attr), _Shape.UNKNOWN)
    return _Shape.UNKNOWN


def _connection_annotation_shape(annotation: ast.expr, imports: ImportIndex) -> _Shape | None:
    annotation = _strip_string_annotation(annotation)
    if isinstance(annotation, ast.Subscript) and any(
        imports.resolves(annotation.value, sources=_PSYCOPG, symbol=symbol) for symbol in _CONNECTIONS
    ):
        return _row_type_shape(annotation.slice, imports)
    if any(imports.resolves(annotation, sources=_PSYCOPG, symbol=symbol) for symbol in _CONNECTIONS):
        return _Shape.UNKNOWN
    return None


def _pool_annotation_shape(annotation: ast.expr, imports: ImportIndex) -> _Shape | None:
    annotation = _strip_string_annotation(annotation)
    if isinstance(annotation, ast.Subscript) and any(
        imports.resolves(annotation.value, sources=_PSYCOPG_POOL, symbol=symbol) for symbol in _POOLS
    ):
        return _connection_annotation_shape(annotation.slice, imports)
    if any(imports.resolves(annotation, sources=_PSYCOPG_POOL, symbol=symbol) for symbol in _POOLS):
        return _Shape.UNKNOWN
    return None


def _strip_string_annotation(annotation: ast.expr) -> ast.expr:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return annotation
    return annotation


def _row_type_shape(annotation: ast.expr, imports: ImportIndex) -> _Shape:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name) and target.id == "tuple" and imports.builtin_is_unshadowed("tuple"):
        return _Shape.POSITIONAL
    if imports.resolves(target, sources=_TYPING, symbol="Tuple"):
        return _Shape.POSITIONAL
    if imports.resolves(target, sources=_PSYCOPG_ROWS, symbol="TupleRow"):
        return _Shape.POSITIONAL
    return _Shape.UNKNOWN


def _explicit_factory_shape(call: ast.Call, imports: ImportIndex, shadowed: frozenset[str]) -> _Shape | None:
    factories = [keyword.value for keyword in call.keywords if keyword.arg == "row_factory"]
    if not factories:
        return None
    if len(factories) != 1:
        return _Shape.UNKNOWN
    factory = factories[0]
    target = factory.func if isinstance(factory, ast.Call) else factory
    root = _root_name(target)
    if root is not None and root in shadowed:
        return _Shape.UNKNOWN
    if imports.resolves(target, sources=_PSYCOPG_ROWS, symbol="tuple_row"):
        return _Shape.POSITIONAL
    if any(imports.resolves(target, sources=_PSYCOPG_ROWS, symbol=symbol) for symbol in _SAFE_FACTORIES):
        return _Shape.NAMED_OR_SCALAR
    return _Shape.UNKNOWN


def _has_explicit_factory(call: ast.Call) -> bool:
    return any(keyword.arg is None or keyword.arg == "row_factory" for keyword in call.keywords)


def _cursor_shape(cursor: _Cursor, fetch: ast.Call, imports: ImportIndex, shadowed: frozenset[str]) -> _Shape:
    assignments: list[ast.expr] = []
    ambiguous = False
    for statement in cursor.body:
        if _position(statement) >= _position(fetch):
            break
        match statement:
            case ast.Assign(targets=[ast.Attribute(value=ast.Name(id=name), attr="row_factory")], value=value) if name == cursor.name:
                assignments.append(value)
            case _ if _assigns_cursor_factory(statement, cursor.name):
                ambiguous = True
            case _:
                pass
    if ambiguous:
        return _Shape.UNKNOWN
    if not assignments:
        return cursor.inherited_shape
    synthetic = ast.Call(
        func=ast.Name(id="cursor", ctx=ast.Load()),
        args=[],
        keywords=[ast.keyword(arg="row_factory", value=assignments[-1])],
    )
    return _explicit_factory_shape(synthetic, imports, shadowed) or _Shape.UNKNOWN


def _assigns_cursor_factory(node: ast.AST, cursor: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _setattr_row_factory_target(child) == cursor:
            return True
        if isinstance(child, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets: Sequence[ast.expr] = child.targets if isinstance(child, ast.Assign) else (child.target,)
            if any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == cursor
                and target.attr == "row_factory"
                for target in targets
            ):
                return True
    return False


def _setattr_row_factory_target(call: ast.Call) -> str | None:
    match call:
        case ast.Call(
            func=ast.Name(id="setattr"),
            args=[ast.Name(id=target), ast.Constant(value="row_factory"), *_],
        ):
            return target
        case _:
            return None


def _escaping_fetches(body: list[ast.stmt], cursor: str) -> list[ast.Call]:
    nodes = list(_scope_nodes(body, stop_rebinding=cursor))
    fetches = [node for node in nodes if isinstance(node, ast.Call) and _fetch_cursor(node) == cursor]
    if not fetches:
        return []
    flow = _flow_block(body, cursor, {})
    return [fetch for fetch in fetches if fetch in flow.escaped and not _cursor_rebound_before(nodes, cursor, fetch)]


type _OriginSet = frozenset[ast.Call | None]


@dataclass(slots=True)
class _Flow:
    origins: dict[str, _OriginSet]
    escaped: set[ast.Call]
    falls_through: bool = True


def _flow_block(statements: list[ast.stmt], cursor: str, incoming: dict[str, _OriginSet]) -> _Flow:
    state = dict(incoming)
    escaped: set[ast.Call] = set()
    for statement in statements:
        for mutated in _statement_mutation_roots(statement):
            _invalidate_origin_group(state, mutated)
        match statement:
            case ast.Return(value=value):
                escaped.update(origin for origin in _value_origins(value, state, cursor) if origin is not None)
                return _Flow(state, escaped, falls_through=False)
            case ast.Raise() | ast.Break() | ast.Continue():
                return _Flow(state, escaped, falls_through=False)
            case ast.Expr(value=ast.Yield(value=value)):
                escaped.update(origin for origin in _value_origins(value, state, cursor) if origin is not None)
            case ast.Assign(targets=targets, value=value) if targets and all(
                isinstance(target, ast.Name) for target in targets
            ):
                origins = _value_origins(value, state, cursor)
                for target in targets:
                    if isinstance(target, ast.Name):
                        state[target.id] = origins
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                state[name] = _value_origins(value, state, cursor)
            case ast.AugAssign(target=target):
                _invalidate_origin_group(state, _root_name(target))
            case ast.Assign(targets=targets):
                for target in targets:
                    _invalidate_origin_group(state, _mutation_root(target))
            case ast.If():
                branches = (
                    _flow_block(statement.body, cursor, state),
                    _flow_block(statement.orelse, cursor, state),
                )
                escaped.update(origin for branch in branches for origin in branch.escaped)
                falling = [branch.origins for branch in branches if branch.falls_through]
                if not falling:
                    return _Flow(state, escaped, falls_through=False)
                state = _merge_origins(falling)
            case ast.Match():
                branches = [_flow_block(case.body, cursor, state) for case in statement.cases]
                escaped.update(origin for branch in branches for origin in branch.escaped)
                falling = [branch.origins for branch in branches if branch.falls_through]
                if not _match_is_exhaustive(statement):
                    falling.append(state)
                if not falling:
                    return _Flow(state, escaped, falls_through=False)
                state = _merge_origins(falling)
            case ast.For() | ast.AsyncFor() | ast.While():
                before_loop = dict(state)
                abrupt = _contains_same_scope_loop_control(statement.body)
                branch = _flow_block(statement.body, cursor, state)
                escaped.update(branch.escaped)
                if branch.falls_through and not abrupt:
                    state = _merge_origins((state, branch.origins))
                if statement.orelse:
                    otherwise = _flow_block(statement.orelse, cursor, state)
                    escaped.update(otherwise.escaped)
                    if abrupt and otherwise.falls_through:
                        state = _merge_origins((before_loop, otherwise.origins))
                    elif abrupt:
                        state = before_loop
                    elif otherwise.falls_through:
                        state = otherwise.origins
                    else:
                        return _Flow(state, escaped, falls_through=False)
            case ast.With() | ast.AsyncWith():
                if any(
                    isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == cursor
                    for item in statement.items
                ):
                    continue
                branch = _flow_block(statement.body, cursor, state)
                escaped.update(branch.escaped)
                if not branch.falls_through:
                    return _Flow(state, escaped, falls_through=False)
                state = branch.origins
            case ast.Try() | ast.TryStar():
                # A finally block can replace a pending return. Avoid path claims across this construct.
                for name in _same_scope_bindings(statement):
                    state[name] = frozenset({None})
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                state[statement.name] = frozenset({None})
            case ast.Expr(value=ast.Call() as call):
                if isinstance(call.func, ast.Attribute) and call.func.attr in _MUTATING_METHODS:
                    _invalidate_origin_group(state, _root_name(call.func.value))
            case _:
                pass
    return _Flow(state, escaped)


def _value_origins(value: ast.expr | None, state: dict[str, _OriginSet], cursor: str) -> _OriginSet:
    unwrapped = _strip_await(value)
    if isinstance(unwrapped, ast.Call) and _fetch_cursor(unwrapped) == cursor:
        return frozenset({unwrapped})
    if isinstance(unwrapped, ast.Name):
        return state.get(unwrapped.id, frozenset({None}))
    return frozenset({None})


def _merge_origins(states: Iterable[dict[str, _OriginSet]]) -> dict[str, _OriginSet]:
    materialized = tuple(states)
    names = {name for state in materialized for name in state}
    return {
        name: frozenset(
            origin
            for state in materialized
            for origin in state.get(name, frozenset({None}))
        )
        for name in names
    }


def _invalidate_origin_group(state: dict[str, _OriginSet], name: str | None) -> None:
    if name is None:
        return
    affected = {origin for origin in state.get(name, frozenset()) if origin is not None}
    for alias, origins in tuple(state.items()):
        if not affected.isdisjoint(origin for origin in origins if origin is not None):
            state[alias] = frozenset({None})


def _mutation_root(target: ast.expr) -> str | None:
    return _root_name(target) if isinstance(target, ast.Attribute | ast.Subscript) else None


def _statement_mutation_roots(statement: ast.stmt) -> frozenset[str]:
    roots: set[str] = set()
    expressions = [child for child in ast.iter_child_nodes(statement) if isinstance(child, ast.expr)]
    if isinstance(statement, ast.With | ast.AsyncWith):
        expressions.extend(item.context_expr for item in statement.items)
    elif isinstance(statement, ast.Match):
        expressions.extend(case.guard for case in statement.cases if case.guard is not None)
    nodes = (node for expression in expressions for node in ast.walk(expression))
    for node in nodes:
        root: str | None = None
        if isinstance(node, ast.Attribute | ast.Subscript) and isinstance(node.ctx, ast.Store | ast.Del):
            root = _root_name(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _MUTATING_METHODS:
            root = _root_name(node.func.value)
        if root is not None:
            roots.add(root)
    if isinstance(statement, ast.AugAssign) and (root := _root_name(statement.target)) is not None:
        roots.add(root)
    return frozenset(roots)


def _contains_same_scope_loop_control(statements: Iterable[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Break | ast.Continue) for node in _scope_nodes(statements))


def _match_is_exhaustive(statement: ast.Match) -> bool:
    return bool(
        statement.cases
        and isinstance(statement.cases[-1].pattern, ast.MatchAs)
        and statement.cases[-1].pattern.pattern is None
        and statement.cases[-1].guard is None
    )


def _fetch_cursor(call: ast.Call) -> str | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in _FETCH_METHODS:
        return None
    receiver = call.func.value
    if isinstance(receiver, ast.Name):
        return receiver.id
    if (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr == "execute"
        and isinstance(receiver.func.value, ast.Name)
    ):
        return receiver.func.value.id
    return None


def _cursor_rebound_before(nodes: Iterable[ast.AST], cursor: str, fetch: ast.Call) -> bool:
    return any(
        isinstance(node, ast.Name)
        and node.id == cursor
        and isinstance(node.ctx, ast.Store | ast.Del)
        and _position(node) < _position(fetch)
        for node in nodes
    )


def _strip_await(node: ast.expr | None) -> ast.expr | None:
    return node.value if isinstance(node, ast.Await) else node


def _as_call(node: ast.expr) -> ast.Call | None:
    unwrapped = _strip_await(node)
    return unwrapped if isinstance(unwrapped, ast.Call) else None


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _scope_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names: set[str] = set()
    for node in _scope_nodes(function.body):
        match node:
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                names.add(name)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.Import(names=aliases):
                names.update(alias.asname or alias.name.partition(".")[0] for alias in aliases)
            case ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name for alias in aliases if alias.name != "*")
            case _:
                pass
    args = function.args
    names.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return frozenset(names)


def _target_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple | ast.List):
        return {name for element in node.elts for name in _target_names(element)}
    return set()


def _position(node: ast.AST) -> tuple[int, int]:
    return getattr(node, "lineno", -1), getattr(node, "col_offset", -1)


def _scope_nodes(statements: Iterable[ast.stmt], *, stop_rebinding: str | None = None) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(list(statements)))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _SCOPE_NODES):
            continue
        if stop_rebinding is not None and isinstance(node, ast.With | ast.AsyncWith) and any(
            isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == stop_rebinding
            for item in node.items
        ):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))
