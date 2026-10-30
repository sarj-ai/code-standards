from __future__ import annotations

import ast
from dataclasses import dataclass
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
)
from sarj_python_lint.rules._annotation_semantics import scope_bound_names
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._store_writes import methods, own_nodes
from sarj_python_lint.rules.require_port_for_service import is_data_type


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


type _Method = ast.FunctionDef | ast.AsyncFunctionDef
_OPERATIONS = frozenset({"get", "create", "insert", "upsert", "update", "delete"})
_ROLES = ("Service", "Store", "Repository")
_NEUTRAL_DECORATORS = frozenset(
    {"typing.override", "typing_extensions.override", "typing.final", "typing_extensions.final"}
)
_ABSTRACT_DECORATORS = frozenset({"abc.abstractmethod", "typing.overload", "typing_extensions.overload"})
_NEUTRAL_BASES = frozenset({"abc.ABC", "typing.Generic", "typing_extensions.Generic"})
_MAX_STATES = 64
_UNKNOWN = "?"


@final
class ServiceSingletonDelegatesToBulk(Rule):
    id = "service-singleton-delegates-to-bulk"
    code = "SARJ556"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Service singleton CRUD operations must delegate to a bulk primitive.",
        rationale=(
            "A singleton-only API forces callers into serial operations. Separate singleton and bulk implementations "
            "duplicate filtering, validation and mutation behavior; making bulk loop through singleton preserves that "
            "cost and can recurse when the singleton is later made an adapter."
        ),
        remediation=(
            "Implement get_many, create_many, insert_many, upsert_many, update_many or delete_many as the primitive. "
            "Delegate the matching singleton through a one-item collection, forwarding shared context and awaiting "
            "async operations. Preserve result projection, missing-item, authorization and transaction semantics; "
            "use a reasoned exact-code suppression for a boundary that cannot support batching."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks module-level Service, Store and Repository classes with concrete instance CRUD methods and at least one input; arbitrary domain verbs are not inferred. Existing get_by_ids bulk reads are accepted alongside get_many.",
            "Tests, fakes, generated/vendor code, stubs, data classes, protocols, static/class methods, abstract/overload declarations and rewriting decorators are excluded.",
            "Same-file inherited methods are resolved. Missing bulk methods are not inferred through unknown external bases. Aliased, rebound, overloaded, descriptor and decorated bulk members are deferred; dynamic dispatch and imported inheritance remain type-checker and review concerns.",
            "Adapters use straight-line calls, scalar and one-item list/tuple/set aliases, and private instance helpers, with a bounded 64-state walk. Complex control flow requires an exact exception or a simple adapter helper.",
            "Requires the original item and shared parameters to reach the bulk call and rejects visible reverse calls through same-class methods. It does not prove database batching, result projection, authorization, atomicity or arbitrary external side effects.",
        ),
        examples=(
            RuleExample(
                example_id="missing-bulk-api",
                title="A singleton operation needs a bulk primitive",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/users.py",
                        "class UserService:\n    async def get(self, key: str):\n        return await self.store.get(key)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/users.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-first-adapter",
                title="Implement singleton access as a one-item bulk operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/users.py",
                        "class UserService:\n    async def get(self, key: str):\n        rows = await self.get_many([key])\n        return rows[0] if rows else None\n    async def get_many(self, keys: list[str]):\n        return await self.store.get_many(keys)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/users.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="inverted-bulk-write",
                scenario="write",
                title="Bulk writes must not call back through the singleton",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/users.py",
                        "class UserService:\n    def upsert(self, user):\n        return self.upsert_many([user])[0]\n    def upsert_many(self, users):\n        return [self.upsert(user) for user in users]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/users.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-first-write",
                scenario="write",
                title="Write through the bulk primitive",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/users.py",
                        "class UserService:\n    def upsert(self, user):\n        return self.upsert_many([user])[0]\n    def upsert_many(self, users):\n        return self.store.upsert_many(users)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/users.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
            or context.path.suffix == ".pyi"
        ):
            return []
        tree = context.tree
        if tree is None:
            return []
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        return [
            diagnostic
            for owner in classes.values()
            if owner.name.endswith(_ROLES)
            and all(
                context.module_imports.resolved_qualified_name(d) in _NEUTRAL_DECORATORS for d in owner.decorator_list
            )
            and not is_data_type(owner)
            and not any(
                context.module_imports.resolves(
                    base.value if isinstance(base, ast.Subscript) else base, sources=TYPING_SOURCES, symbol="Protocol"
                )
                for base in owner.bases
            )
            for diagnostic in _owner_diagnostics(owner, classes, context, self.code)
        ]


@dataclass(frozen=True, slots=True)
class _Surface:
    methods: dict[str, _Method]
    uncertain: frozenset[str]
    unknown_base: bool


@dataclass(frozen=True, slots=True)
class _Call:
    name: str
    bindings: dict[str, str]


def _owner_diagnostics(
    owner: ast.ClassDef, classes: dict[str, ast.ClassDef], context: PythonFileContext, code: str
) -> list[Diagnostic]:
    surface = _inherited_methods(owner, classes, context.module_imports, frozenset())
    diagnostics: list[Diagnostic] = []
    for name, singleton in methods(owner).items():
        if name not in _OPERATIONS or not _concrete_instance(singleton, context.module_imports):
            continue
        problem = _operation_problem(singleton, surface, context.module_imports)
        if problem is not None:
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=singleton.lineno,
                    col=singleton.col_offset + 1,
                    code=code,
                    severity=Severity.ERROR,
                    message=f"`{owner.name}.{name}` {problem} Implement `{name}_many` as the bulk primitive and delegate `{name}` with one item and the same context.",
                )
            )
    return diagnostics


def _concrete_instance(method: _Method, imports: ImportIndex) -> bool:
    parameters = _parameters(method)
    if not parameters or method.args.vararg or method.args.kwarg:
        return False
    if any(imports.resolved_qualified_name(d) not in _NEUTRAL_DECORATORS for d in method.decorator_list):
        return False
    body = [
        s
        for s in method.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]
    return bool(body) and not all(_stub(statement) for statement in body)


def _parameters(method: _Method) -> list[ast.arg]:
    positional = [*method.args.posonlyargs, *method.args.args]
    if not positional or positional[0].arg != "self":
        return []
    return [*positional[1:], *method.args.kwonlyargs]


def _stub(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return statement.value.value is Ellipsis
    if isinstance(statement, ast.Raise):
        value = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc
        return isinstance(value, ast.Name) and value.id == "NotImplementedError"
    return False


def _inherited_methods(
    owner: ast.ClassDef, classes: dict[str, ast.ClassDef], imports: ImportIndex, seen: frozenset[str]
) -> _Surface:
    if owner.name in seen:
        return _Surface({}, frozenset(), unknown_base=True)
    result: dict[str, _Method] = {}
    uncertain: set[str] = set()
    unknown = False
    for base in reversed(owner.bases):
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name) and target.id in classes:
            inherited = _inherited_methods(classes[target.id], classes, imports, seen | {owner.name})
            for name in inherited.uncertain:
                result.pop(name, None)
            result.update(inherited.methods)
            uncertain.difference_update(inherited.methods)
            uncertain.update(inherited.uncertain)
            unknown |= inherited.unknown_base
        elif imports.resolved_qualified_name(target) not in _NEUTRAL_BASES and not (
            isinstance(target, ast.Name) and target.id == "object" and imports.builtin_is_unshadowed("object")
        ):
            unknown = True
    declared = methods(owner)
    bound = _member_bindings(owner)
    for name in bound:
        result.pop(name, None)
    result.update(declared)
    uncertain.difference_update(bound)
    uncertain.update(bound - declared.keys() - _literal_members(owner))
    return _Surface(result, frozenset(uncertain), unknown)


def _member_bindings(owner: ast.ClassDef) -> set[str]:
    bound = scope_bound_names(owner.body)
    bound.update(
        node.attr
        for method in owner.body
        if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in own_nodes(method)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store | ast.Del)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )
    return bound


def _literal_members(owner: ast.ClassDef) -> set[str]:
    literals: set[str] = set()
    for statement in owner.body:
        literals.difference_update(scope_bound_names([statement]))
        if not isinstance(statement, ast.Assign | ast.AnnAssign) or not isinstance(
            statement.value, ast.Constant | ast.List | ast.Tuple | ast.Set | ast.Dict
        ):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        literals.update(target.id for target in targets if isinstance(target, ast.Name))
    return literals


def _operation_problem(singleton: _Method, surface: _Surface, imports: ImportIndex) -> str | None:
    bulk_name = f"{singleton.name}_many"
    names = (bulk_name, "get_by_ids") if singleton.name == "get" else (bulk_name,)
    if any(candidate in surface.uncertain for candidate in names):
        return None
    bulks = [surface.methods[candidate] for candidate in names if candidate in surface.methods]
    if not bulks:
        return None if surface.unknown_base else "has no declared bulk operation."
    if any(not _supported_bulk(bulk, imports) for bulk in bulks):
        return None
    if any(_reaches(bulk.name, singleton.name, surface.methods) for bulk in bulks):
        return "has a bulk operation that calls back through the singleton."
    problems = [_adapter_problem(singleton, bulk, surface.methods, imports) for bulk in bulks]
    return None if None in problems else problems[0]


def _supported_bulk(bulk: _Method, imports: ImportIndex) -> bool:
    return (
        not bulk.args.vararg
        and not bulk.args.kwarg
        and all(
            imports.resolved_qualified_name(d) in _NEUTRAL_DECORATORS | _ABSTRACT_DECORATORS
            for d in bulk.decorator_list
        )
    )


def _adapter_problem(
    singleton: _Method, bulk: _Method, available: dict[str, _Method], imports: ImportIndex
) -> str | None:
    if not _parameters(bulk):
        return "has no instance bulk operation accepting items."
    if not _concrete_instance(bulk, imports) and not any(
        imports.resolved_qualified_name(d) == "abc.abstractmethod" for d in bulk.decorator_list
    ):
        return "has only an unimplemented bulk stub."
    bindings = {p.arg: f"input:{p.arg}" for p in _parameters(singleton)}
    if not _delegates(singleton, bulk, available, bindings):
        return "does not delegate its original item and shared context to the bulk operation."
    return None


def _reaches(start: str, target: str, available: dict[str, _Method]) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for node in own_nodes(available[name]):
            if not isinstance(node, ast.Call):
                continue
            called = _self_call(node)
            if called is None:
                continue
            if called == target:
                return True
            if called in available:
                pending.append(called)
    return False


def _self_call(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
        return call.func.attr
    return None


def _symbol(value: ast.expr, symbols: dict[str, str]) -> str:
    match value:
        case ast.Name(id=name):
            return symbols.get(name, _UNKNOWN)
        case ast.List() | ast.Tuple() | ast.Set():
            items = _collection_symbols(value, symbols)
            if items is None or len(items) != 1:
                return _UNKNOWN
            item = items[0]
            return f"one:{item}" if item != _UNKNOWN else _UNKNOWN
        case _:
            return _UNKNOWN


def _collection_symbols(value: ast.List | ast.Tuple | ast.Set, symbols: dict[str, str]) -> list[str] | None:
    items: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Starred):
            items.append(_symbol(element, symbols))
            continue
        expanded = element.value
        if isinstance(expanded, ast.List | ast.Tuple | ast.Set) and not expanded.elts:
            continue
        symbol = _symbol(expanded, symbols)
        if not symbol.startswith("one:"):
            return None
        items.append(symbol.removeprefix("one:"))
    return items


def _delegates(singleton: _Method, bulk: _Method, available: dict[str, _Method], initial: dict[str, str]) -> bool:
    pending = [_Call(singleton.name, initial)]
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    inputs = frozenset(initial.values())
    while pending and len(seen) < _MAX_STATES:
        candidate = pending.pop()
        state = candidate.name, tuple(sorted(candidate.bindings.items()))
        if state in seen:
            continue
        seen.add(state)
        for call in _method_calls(available[candidate.name], available, candidate.bindings):
            if call.name == bulk.name and _matches(call.bindings, inputs):
                return True
            if call.name.startswith("_"):
                pending.append(call)
    return False


def _matches(bindings: dict[str, str], inputs: frozenset[str]) -> bool:
    wrapped = [value.removeprefix("one:") for value in bindings.values() if value.startswith("one:")]
    if len(wrapped) != 1 or wrapped[0] not in inputs:
        return False
    for value in inputs - {wrapped[0]}:
        name = value.removeprefix("input:")
        if value not in bindings.values():
            return False
        if name in bindings and bindings[name] != value:
            return False
    return True


def _method_calls(method: _Method, available: dict[str, _Method], bindings: dict[str, str]) -> list[_Call]:
    calls: list[_Call] = []
    symbols = {**bindings, "self": "receiver:self"}
    for statement in method.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if not isinstance(statement, ast.Assign | ast.AnnAssign | ast.Expr | ast.Return | ast.Raise | ast.Pass):
            break
        calls.extend(_bound_calls(statement, available, symbols))
        _assignment(statement, symbols)
        if isinstance(statement, ast.Return | ast.Raise):
            break
    return calls


def _bound_calls(statement: ast.stmt, available: dict[str, _Method], symbols: dict[str, str]) -> list[_Call]:
    nodes = _eager_nodes(statement)
    awaited = {id(n.value) for n in nodes if isinstance(n, ast.Await)}
    calls: list[_Call] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        called = _self_call(node)
        if called is None:
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                _invalidate(node.func.value, symbols)
            continue
        if symbols.get("self") != "receiver:self":
            continue
        target = available.get(called)
        if target is None or (isinstance(target, ast.AsyncFunctionDef) and id(node) not in awaited):
            continue
        bindings = _bind(node, target, symbols)
        if bindings is not None:
            calls.append(_Call(called, bindings))
    return calls


def _eager_nodes(statement: ast.stmt) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    pending: list[ast.AST] = [statement]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Lambda | ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp | ast.IfExp):
            continue
        nodes.append(node)
        children = [node.values[0]] if isinstance(node, ast.BoolOp) else list(ast.iter_child_nodes(node))
        pending.extend(reversed(children))
    return nodes


def _bind(call: ast.Call, method: _Method, symbols: dict[str, str]) -> dict[str, str] | None:
    positional = [*method.args.posonlyargs, *method.args.args][1:]
    parameters = _parameters(method)
    if len(call.args) > len(positional) or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    result = {p.arg: _symbol(arg, symbols) for p, arg in zip(positional, call.args, strict=False)}
    names = {p.arg for p in parameters}
    positional_only = {p.arg for p in method.args.posonlyargs}
    for keyword in call.keywords:
        name = keyword.arg
        if name is None or name not in names or name in result or name in positional_only:
            return None
        result[name] = _symbol(keyword.value, symbols)
    required = positional[: -len(method.args.defaults)] if method.args.defaults else positional
    required += [
        p for p, default in zip(method.args.kwonlyargs, method.args.kw_defaults, strict=True) if default is None
    ]
    if any(p.arg not in result for p in required):
        return None
    return result


def _invalidate(target: ast.expr, symbols: dict[str, str]) -> None:
    if isinstance(target, ast.Subscript):
        target = target.value
    if not isinstance(target, ast.Name):
        return
    value = symbols.get(target.id, _UNKNOWN)
    for name, symbol in tuple(symbols.items()):
        if symbol == value:
            symbols[name] = _UNKNOWN


def _assignment(statement: ast.stmt, symbols: dict[str, str]) -> None:
    if not isinstance(statement, ast.Assign | ast.AnnAssign) or statement.value is None:
        return
    value = _symbol(statement.value, symbols)
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    for target in targets:
        if isinstance(target, ast.Name):
            symbols[target.id] = value
        else:
            _invalidate(target, symbols)
