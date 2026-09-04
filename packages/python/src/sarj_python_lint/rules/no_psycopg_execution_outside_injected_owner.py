from __future__ import annotations

import ast
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
    from collections.abc import Iterable
    from pathlib import Path


_POOL_MODULES = frozenset({"psycopg_pool"})
_POOL_TYPES = frozenset({"AsyncConnectionPool", "ConnectionPool"})
_CONNECTION_MODULES = frozenset({"psycopg"})
_CONNECTION_TYPES = frozenset({"AsyncConnection", "Connection"})
_EXECUTE_METHODS = frozenset({"execute", "executemany"})
_REFLECTIVE_WRITE_ARG_COUNT = 2
_LANGUAGE_ROOT_PATH_DEPTH = 2
_PACKAGE_ROOT_PATH_DEPTH = 3
_OPERATIONAL_ROOTS = frozenset({"backfill", "backfills", "bin", "scripts", "test_support", "tools"})


class _Origin(StrEnum):
    INJECTED = "injected"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class _TypeIndex:
    imports: ImportIndex
    aliases: dict[str, ast.expr]
    ambiguous: frozenset[str]
    globals: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ClassOwnership:
    injected: frozenset[str]
    external: frozenset[str]


@dataclass(frozen=True, slots=True)
class _FunctionScope:
    function: ast.FunctionDef | ast.AsyncFunctionDef
    owner: ast.ClassDef | None


@final
class NoPsycopgExecutionOutsideInjectedOwner(Rule):
    id = "no-psycopg-execution-outside-injected-owner"
    code = "SARJ415"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Psycopg execution occurs outside a constructor-injected persistence owner.",
        rationale=(
            "Free helpers and locally created clients can split query and transaction ownership across unrelated "
            "call sites, making persistence behavior harder to change consistently."
        ),
        remediation=(
            "Move the operation behind a store, repository, or narrow transaction owner that receives its Psycopg "
            "pool or connection through the constructor. Use an exact SARJ415 suppression when direct execution is "
            "the deliberate behavior under test."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("sql-requires-injected-pool-owner",),
        limitations=(
            "Only import-proven psycopg Connection or AsyncConnection and psycopg_pool ConnectionPool or AsyncConnectionPool flows are classified.",
            "Straightforward constructor injection, connection and cursor context managers, aliases, rebindings, and conservative control-flow joins are followed; interprocedural flows remain unreported.",
            "Tests, test support, migrations, generated files, conventional operational-script roots, and literal SELECT 1 probes are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="free-psycopg-helper",
                title="Do not execute persistence operations in a free helper",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/retry_rows.py",
                        "from psycopg_pool import AsyncConnectionPool\n\nasync def mark(pool: AsyncConnectionPool):\n    async with pool.connection() as conn:\n        await conn.execute('UPDATE call SET retry = true')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/retry_rows.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="injected-store-psycopg",
                title="Execute through an injected persistence owner",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "from psycopg_pool import AsyncConnectionPool\n\nclass Store:\n    def __init__(self, pool: AsyncConnectionPool):\n        self.pool = pool\n\n    async def save(self):\n        async with self.pool.connection() as conn:\n            await conn.execute('UPDATE call SET retry = true')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        path_parts = {part.lower() for part in path.parts}
        if (
            is_generated(path, source)
            or is_test_path(path)
            or is_test_support_path(path)
            or not path_parts.isdisjoint({"migration", "migrations"})
            or _is_operational_path(path)
        ):
            return []
        tree = parse_or_none(path, source)
        if not isinstance(tree, ast.Module):
            return []
        types = _type_index(tree)
        ownership = {node: _class_ownership(node, types) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        source_lines = source.splitlines()
        calls: list[ast.Call] = []
        for scope in _function_scopes(tree):
            owned = ownership[scope.owner] if scope.owner is not None else _ClassOwnership(frozenset(), frozenset())
            calls.extend(_FunctionAnalyzer(types, owned).analyze(scope.function))
        unique = {(call.lineno, call.col_offset): call for call in calls}
        return [
            Diagnostic(
                path=path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "Psycopg execution is outside a constructor-injected persistence owner; route it through the "
                    "owning store, repository, or transaction API"
                ),
            )
            for call in sorted(unique.values(), key=lambda item: (item.lineno, item.col_offset))
            if not _node_is_suppressed(source_lines, call, self.code)
        ]


def _type_index(tree: ast.Module) -> _TypeIndex:
    counts = _module_binding_counts(tree)
    aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        match statement:
            case ast.TypeAlias(name=ast.Name(id=name), value=value):
                if counts.get(name) == 1:
                    aliases[name] = value
            case ast.Assign(targets=[ast.Name(id=name)], value=value) if isinstance(value, ast.Name | ast.Attribute):
                if counts.get(name) == 1:
                    aliases[name] = value
            case _:
                continue
    preliminary = _TypeIndex(
        ImportIndex.from_tree(tree, module_scope_only=True),
        aliases,
        frozenset(name for name, count in counts.items() if count > 1),
        frozenset(),
    )
    globals_ = {
        target.id
        for statement in tree.body
        if isinstance(statement, ast.Assign) and _database_creator(statement.value, preliminary)
        for target in statement.targets
        if isinstance(target, ast.Name) and counts.get(target.id) == 1
    }
    globals_.update(
        statement.target.id
        for statement in tree.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.value is not None
        and _database_creator(statement.value, preliminary)
        and counts.get(statement.target.id) == 1
    )
    return _TypeIndex(preliminary.imports, aliases, preliminary.ambiguous, frozenset(globals_))


def _database_annotation(node: ast.expr | None, types: _TypeIndex, seen: frozenset[str] = frozenset()) -> bool:
    return _annotation_kind(node, types, seen) is not None


def _compatible_union_kind(elements: Iterable[ast.expr], types: _TypeIndex, seen: frozenset[str]) -> str | None:
    kinds = {
        kind
        for element in elements
        if not _is_none_annotation(element)
        if (kind := _annotation_kind(element, types, seen)) is not None
    }
    required = [element for element in elements if not _is_none_annotation(element)]
    if len(kinds) != 1 or any(_annotation_kind(element, types, seen) is None for element in required):
        return None
    return next(iter(kinds))


def _is_none_annotation(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _annotation_kind(
    node: ast.expr | None,
    types: _TypeIndex,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return None
        return _annotation_kind(parsed.body, types, seen)
    if isinstance(node, ast.Name) and node.id in types.aliases and node.id not in seen:
        return _annotation_kind(types.aliases[node.id], types, seen | {node.id})
    if _root_name(node) in types.ambiguous:
        return None
    if node is not None:
        if any(types.imports.resolves(node, sources=_POOL_MODULES, symbol=name) for name in _POOL_TYPES):
            return "pool"
        if any(types.imports.resolves(node, sources=_CONNECTION_MODULES, symbol=name) for name in _CONNECTION_TYPES):
            return "connection"
    match node:
        case ast.Subscript(value=value, slice=content):
            direct = _annotation_kind(value, types, seen)
            if direct is not None:
                return direct
            tail = _tail(value)
            if tail == "Annotated":
                first = content.elts[0] if isinstance(content, ast.Tuple) and content.elts else content
                return _annotation_kind(first, types, seen)
            if tail == "Optional":
                return _annotation_kind(content, types, seen)
            if tail == "Union":
                elements = content.elts if isinstance(content, ast.Tuple) else [content]
                return _compatible_union_kind(elements, types, seen)
            return None
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _compatible_union_kind([left, right], types, seen)
        case ast.Tuple(elts=elements):
            return next((kind for item in elements if (kind := _annotation_kind(item, types, seen))), None)
        case _:
            return None


def _class_ownership(cls: ast.ClassDef, types: _TypeIndex) -> _ClassOwnership:
    constructors = [
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "__init__"
    ]
    injected: set[str] = set()
    external: set[str] = set()
    if len(constructors) == 1:
        constructor = constructors[0]
        parameters = {
            argument.arg for argument in _arguments(constructor) if _database_annotation(argument.annotation, types)
        }
        origins = dict.fromkeys(parameters, _Origin.INJECTED)
        for statement in constructor.body:
            _apply_constructor_statement(statement, types, origins, injected, external)
    methods = [
        method
        for method in cls.body
        if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) and method.name != "__init__"
    ]
    if any(_has_dynamic_reflective_self_write(method) for method in methods):
        return _ClassOwnership(frozenset(), frozenset())
    mutated = {attribute for method in methods for attribute in _self_attribute_writes(method)}
    return _ClassOwnership(frozenset(injected - mutated), frozenset(external - mutated))


def _apply_constructor_statement(
    statement: ast.stmt,
    types: _TypeIndex,
    origins: dict[str, _Origin],
    injected: set[str],
    external: set[str],
) -> None:
    assignment = _self_attribute_assignment(statement)
    if assignment is not None:
        attribute, value = assignment
        injected.discard(attribute)
        external.discard(attribute)
        origin = origins.get(value.id) if isinstance(value, ast.Name) else None
        origin = _Origin.EXTERNAL if origin is None and _database_creator(value, types) else origin
        if origin is _Origin.INJECTED:
            injected.add(attribute)
        elif origin is _Origin.EXTERNAL:
            external.add(attribute)
    if not isinstance(statement, ast.Assign):
        if not isinstance(statement, ast.AnnAssign) or statement.value is None:
            return
        value = statement.value
        targets = [statement.target]
    else:
        value = statement.value
        targets = statement.targets
    origin = origins.get(value.id) if isinstance(value, ast.Name) else None
    origin = _Origin.EXTERNAL if origin is None and _database_creator(value, types) else origin
    for target in targets:
        for name in _target_names(target):
            if origin is None:
                origins.pop(name, None)
            else:
                origins[name] = origin


def _self_attribute_assignment(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    match statement:
        case ast.Assign(targets=[ast.Attribute(value=ast.Name(id="self"), attr=attribute)], value=value):
            return attribute, value
        case ast.AnnAssign(
            target=ast.Attribute(value=ast.Name(id="self"), attr=attribute),
            value=value,
        ) if value is not None:
            return attribute, value
        case _:
            return None


def _self_attribute_writes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    attributes: set[str] = set()
    for node in _scope_nodes(function):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, ast.Store | ast.Del)
        ):
            attributes.add(node.attr)
        if (attribute := _reflective_self_write(node)) is not None:
            attributes.add(attribute)
    return attributes


def _reflective_self_write(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id not in {"delattr", "setattr"} or len(node.args) < _REFLECTIVE_WRITE_ARG_COUNT:
        return None
    owner, attribute = node.args[:_REFLECTIVE_WRITE_ARG_COUNT]
    if not isinstance(owner, ast.Name) or owner.id != "self":
        return None
    return attribute.value if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str) else None


def _has_dynamic_reflective_self_write(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in _scope_nodes(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"delattr", "setattr"} or len(node.args) < _REFLECTIVE_WRITE_ARG_COUNT:
            continue
        owner, attribute = node.args[:_REFLECTIVE_WRITE_ARG_COUNT]
        if (
            isinstance(owner, ast.Name)
            and owner.id == "self"
            and not (isinstance(attribute, ast.Constant) and isinstance(attribute.value, str))
        ):
            return True
    return False


def _function_scopes(tree: ast.Module) -> list[_FunctionScope]:
    scopes: list[_FunctionScope] = []

    class Collector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.owner: ast.ClassDef | None = None

        @override
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            previous = self.owner
            self.owner = node
            for statement in node.body:
                self.visit(statement)
            self.owner = previous

        @override
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._function(node)

        @override
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._function(node)

        def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            scopes.append(_FunctionScope(node, self.owner))
            previous = self.owner
            self.owner = None
            for statement in node.body:
                self.visit(statement)
            self.owner = previous

        @override
        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

    Collector().visit(tree)
    return scopes


@final
class _FunctionAnalyzer:
    def __init__(self, types: _TypeIndex, ownership: _ClassOwnership) -> None:
        self._types = types
        self._ownership = ownership
        self._findings: list[ast.Call] = []
        self._shadowed: set[str] = set()

    def analyze(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
        state = {
            argument.arg: _Origin.EXTERNAL
            for argument in _arguments(function)
            if _database_annotation(argument.annotation, self._types)
        }
        self._shadowed = {argument.arg for argument in _arguments(function)}
        if function.name == "__init__":
            state = dict.fromkeys(state, _Origin.INJECTED)
        self._block(function.body, state)
        return self._findings

    def _block(self, statements: Iterable[ast.stmt], state: dict[str, _Origin]) -> dict[str, _Origin] | None:
        current = dict(state)
        for statement in statements:
            next_state = self._statement(statement, current)
            if next_state is None:
                return None
            current = next_state
        return current

    def _statement(self, statement: ast.stmt, state: dict[str, _Origin]) -> dict[str, _Origin] | None:
        current = dict(state)
        match statement:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                self._shadowed.add(name)
                return current
            case ast.Import(names=aliases):
                self._shadowed.update(alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in aliases)
                return current
            case ast.ImportFrom(names=aliases):
                self._shadowed.update(alias.asname or alias.name for alias in aliases)
                return current
            case ast.Assign(targets=targets, value=value):
                self._inspect(value, current)
                origin = self._expression_origin(value, current)
                for target in targets:
                    self._bind(target, origin, current)
                    self._shadowed.update(_target_names(target))
                return current
            case ast.AnnAssign(target=target, annotation=annotation, value=value):
                if value is not None:
                    self._inspect(value, current)
                origin = self._expression_origin(value, current)
                if origin is None and _database_annotation(annotation, self._types):
                    origin = _Origin.EXTERNAL
                self._bind(target, origin, current)
                self._shadowed.update(_target_names(target))
                return current
            case ast.Delete(targets=targets):
                for target in targets:
                    self._bind(target, None, current)
                    self._shadowed.update(_target_names(target))
                return current
            case ast.With(items=items, body=body) | ast.AsyncWith(items=items, body=body):
                for item in items:
                    self._inspect(item.context_expr, current)
                    if item.optional_vars is not None:
                        self._bind(item.optional_vars, self._context_origin(item.context_expr, current), current)
                        self._shadowed.update(_target_names(item.optional_vars))
                return self._block(body, current)
            case _:
                return self._control_statement(statement, current)

    def _control_statement(self, statement: ast.stmt, current: dict[str, _Origin]) -> dict[str, _Origin] | None:
        match statement:
            case ast.If(test=test, body=body, orelse=orelse):
                self._inspect(test, current)
                return _join_exits(self._block(body, current), self._block(orelse, current))
            case (
                ast.For(target=target, iter=iterator, body=body, orelse=orelse)
                | ast.AsyncFor(target=target, iter=iterator, body=body, orelse=orelse)
            ):
                self._inspect(iterator, current)
                body_state = dict(current)
                self._bind(target, None, body_state)
                self._shadowed.update(_target_names(target))
                body_exit = self._block(body, body_state)
                joined = _join_exits(current, body_exit)
                return current if joined is None else _join_exits(current, self._block(orelse, joined))
            case ast.While(test=test, body=body, orelse=orelse):
                self._inspect(test, current)
                joined = _join_exits(current, self._block(body, current))
                return current if joined is None else _join_exits(current, self._block(orelse, joined))
            case _:
                return self._complex_control_statement(statement, current)

    def _complex_control_statement(self, statement: ast.stmt, current: dict[str, _Origin]) -> dict[str, _Origin] | None:
        match statement:
            case (
                ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
                | ast.TryStar(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)
            ):
                body_exit = self._block(body, current)
                normal = None if body_exit is None else self._block(orelse, body_exit)
                exits: list[dict[str, _Origin] | None] = [normal]
                for handler in handlers:
                    handler_state = dict(current)
                    if handler.name is not None:
                        handler_state.pop(handler.name, None)
                        self._shadowed.add(handler.name)
                    exits.append(self._block(handler.body, handler_state))
                merged = exits[0]
                for exit_state in exits[1:]:
                    merged = _join_exits(merged, exit_state)
                final_exit = self._block(finalbody, merged or current)
                return None if merged is None else final_exit
            case ast.Match(subject=subject, cases=cases):
                self._inspect(subject, current)
                exits = [current]
                for case in cases:
                    case_state = dict(current)
                    pattern_names = _pattern_names(case.pattern)
                    for name in pattern_names:
                        case_state.pop(name, None)
                    self._shadowed.update(pattern_names)
                    if case.guard is not None:
                        self._inspect(case.guard, case_state)
                    exits.append(self._block(case.body, case_state))
                merged: dict[str, _Origin] | None = exits[0]
                for exit_state in exits[1:]:
                    merged = _join_exits(merged, exit_state)
                return merged
            case ast.Return() | ast.Raise():
                self._inspect(statement, current)
                return None
            case ast.Break() | ast.Continue():
                return None
            case _:
                self._inspect(statement, current)
                return current

    def _inspect(self, node: ast.AST, state: dict[str, _Origin]) -> None:
        analyzer = self

        class Visitor(ast.NodeVisitor):
            @override
            def visit_Call(self, node: ast.Call) -> None:
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in _EXECUTE_METHODS
                    and analyzer._expression_origin(node.func.value, state) is _Origin.EXTERNAL
                    and not _is_connection_probe(node)
                ):
                    analyzer._findings.append(node)
                self.generic_visit(node)

            @override
            def visit_ListComp(self, node: ast.ListComp) -> None:
                self._comprehension(node.generators, [node.elt])

            @override
            def visit_SetComp(self, node: ast.SetComp) -> None:
                self._comprehension(node.generators, [node.elt])

            @override
            def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
                self._comprehension(node.generators, [node.elt])

            @override
            def visit_DictComp(self, node: ast.DictComp) -> None:
                self._comprehension(node.generators, [node.key, node.value])

            def _comprehension(self, generators: list[ast.comprehension], results: list[ast.expr]) -> None:
                saved_shadowed = set(analyzer._shadowed)
                saved_state = dict(state)
                for generator in generators:
                    self.visit(generator.iter)
                    names = _target_names(generator.target)
                    analyzer._shadowed.update(names)
                    for name in names:
                        state.pop(name, None)
                    for condition in generator.ifs:
                        self.visit(condition)
                for result in results:
                    self.visit(result)
                analyzer._shadowed = saved_shadowed
                state.clear()
                state.update(saved_state)

            @override
            def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
                self.visit(node.value)
                origin = analyzer._expression_origin(node.value, state)
                analyzer._bind(node.target, origin, state)
                names = _target_names(node.target)
                analyzer._shadowed.update(names)

            @override
            def visit_Lambda(self, node: ast.Lambda) -> None:
                del node

            @override
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                del node

            @override
            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                del node

            @override
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                del node

        Visitor().visit(node)

    def _expression_origin(self, node: ast.expr | None, state: dict[str, _Origin]) -> _Origin | None:
        if isinstance(node, ast.NamedExpr):
            return self._expression_origin(node.value, state)
        if isinstance(node, ast.Name):
            return state.get(node.id) or (_Origin.EXTERNAL if node.id in self._types.globals else None)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            if node.attr in self._ownership.injected:
                return _Origin.INJECTED
            if node.attr in self._ownership.external:
                return _Origin.EXTERNAL
        if isinstance(node, ast.Call) and _database_creator(node, self._types, self._shadowed):
            return _Origin.EXTERNAL
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"connection", "cursor"}
        ):
            return self._expression_origin(node.func.value, state)
        return None

    def _context_origin(self, node: ast.expr, state: dict[str, _Origin]) -> _Origin | None:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return None
        if node.func.attr not in {"connection", "cursor"}:
            return None
        return self._expression_origin(node.func.value, state)

    @staticmethod
    def _bind(target: ast.expr, origin: _Origin | None, state: dict[str, _Origin]) -> None:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store | ast.Del):
                if origin is None:
                    state.pop(child.id, None)
                else:
                    state[child.id] = origin


def _database_creator(node: ast.expr | None, types: _TypeIndex, shadowed: set[str] | None = None) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if shadowed and _root_name(node.func) in shadowed:
        return False
    if _annotation_kind(node.func, types) is not None:
        return True
    if types.imports.resolves(node.func, sources=_CONNECTION_MODULES, symbol="connect"):
        return True
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and _annotation_kind(node.func.value, types) == "connection"
    )


def _arguments(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    args = function.args
    return [
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *(item for item in (args.vararg, args.kwarg) if item is not None),
    ]


def _module_binding_counts(tree: ast.Module) -> dict[str, int]:
    counts: dict[str, int] = {}

    def add(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    class Collector(ast.NodeVisitor):
        @override
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            add(node.name)

        @override
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            add(node.name)

        @override
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            add(node.name)

        @override
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                add(alias.asname or alias.name.split(".", maxsplit=1)[0])

        @override
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                add(alias.asname or alias.name)

        @override
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Store | ast.Del):
                add(node.id)

    Collector().visit(tree)
    return counts


def _target_names(target: ast.expr) -> set[str]:
    return {
        node.id for node in ast.walk(target) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del)
    }


def _scope_nodes(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    pending: list[ast.AST] = list(reversed(scope.body))
    while pending:
        node = pending.pop()
        nodes.append(node)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))
    return nodes


def _pattern_names(pattern: ast.pattern) -> set[str]:
    return {node.name for node in ast.walk(pattern) if isinstance(node, ast.MatchAs) and node.name is not None}


def _join_exits(left: dict[str, _Origin] | None, right: dict[str, _Origin] | None) -> dict[str, _Origin] | None:
    if left is None:
        return right
    if right is None:
        return left
    return _join(left, right)


def _join(left: dict[str, _Origin], right: dict[str, _Origin]) -> dict[str, _Origin]:
    return {name: origin for name, origin in left.items() if right.get(name) is origin}


def _node_is_suppressed(source_lines: list[str], node: ast.AST, code: str) -> bool:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", None) or start
    return any(is_suppressed(source_lines, line, code) for line in range(start, end + 1))


def _tail(node: ast.expr | None) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _root_name(node: ast.expr | None) -> str:
    current = node
    while isinstance(current, ast.Attribute | ast.Subscript):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def _is_operational_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts if part not in {"", ".", "/"}]
    if parts and parts[0] in _OPERATIONAL_ROOTS:
        return True
    if len(parts) >= _LANGUAGE_ROOT_PATH_DEPTH and parts[0] in {"python", "typescript"}:
        return parts[1] in _OPERATIONAL_ROOTS
    return len(parts) >= _PACKAGE_ROOT_PATH_DEPTH and parts[0] == "packages" and parts[2] in _OPERATIONAL_ROOTS


def _is_connection_probe(call: ast.Call) -> bool:
    if not call.args:
        return False
    query = call.args[0]
    return isinstance(query, ast.Constant) and isinstance(query.value, str) and query.value.strip(" ;") == "SELECT 1"
