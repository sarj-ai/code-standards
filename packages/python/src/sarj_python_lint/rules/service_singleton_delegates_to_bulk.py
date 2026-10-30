from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeIs, final, override

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
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._store_writes import decorator_name, instance_member_bindings, methods
from sarj_python_lint.rules.require_port_for_service import is_data_type


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


type _Method = ast.FunctionDef | ast.AsyncFunctionDef
type _Base = ast.ClassDef | str
_OPERATIONS = frozenset({"get", "create", "insert", "upsert", "update", "delete"})
_BULK_OPERATIONS = frozenset({*(f"{name}_many" for name in _OPERATIONS), "get_by_ids"})
_ROLES = ("Service", "Store", "Repository")
_AGGREGATE_MODEL_BASES = frozenset(
    {
        "pydantic.BaseModel",
        "pydantic.RootModel",
        "typing.NamedTuple",
        "typing.TypedDict",
        "typing_extensions.NamedTuple",
        "typing_extensions.TypedDict",
    }
)
_NEUTRAL_DECORATORS = frozenset(
    {"typing.override", "typing_extensions.override", "typing.final", "typing_extensions.final"}
)
_ABSTRACT_DECORATORS = frozenset({"abc.abstractmethod", "typing.overload", "typing_extensions.overload"})
_NEUTRAL_BASES = frozenset(
    {"abc.ABC", "typing.Generic", "typing_extensions.Generic", "typing.Protocol", "typing_extensions.Protocol"}
)
_MAX_STATES = 64
_MAX_CLASS_STATES = 64
_MAX_MRO_STEPS = _MAX_CLASS_STATES**2
_IMMUTABLE_SCALAR_TYPES = frozenset(
    {"builtins.str", "builtins.bytes", "builtins.int", "builtins.bool", "builtins.float", "builtins.complex"}
)
_COLLECTION_TYPES = frozenset(
    {
        "builtins.list",
        "builtins.tuple",
        "builtins.set",
        "builtins.frozenset",
        "typing.List",
        "typing.Tuple",
        "typing.Set",
        "typing.FrozenSet",
        "typing.Sequence",
        "typing.Collection",
        "typing.Iterable",
        "collections.abc.Sequence",
        "collections.abc.Collection",
        "collections.abc.Iterable",
        "collections.abc.Set",
    }
)


@dataclass(frozen=True, slots=True)
class _Symbol:
    origin: str = "?"
    item: _Symbol | None = None
    allocation: ast.expr | None = None
    immutable: bool = False


_UNKNOWN = _Symbol()
_SELF = _Symbol(origin="receiver:self")


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
            "Checks concrete instance CRUD methods declared on stable module-level Service, Store and Repository classes and their same-file implementations, with at least one input; inherited singleton declarations and arbitrary domain verbs are not inferred. Existing get_by_ids bulk reads are accepted alongside get_many.",
            "Tests, fakes, generated/vendor code, stubs, data classes, protocols, static/class methods, abstract/overload declarations and rewriting decorators are excluded.",
            "Missing-bulk update checks defer an implicit-resource ambiguity when an own stable concrete parameterless get and update explicitly return the same earlier, stable same-file data model and no CRUD bulk peer is declared or uncertain. This bounded source shape reduces recall; it does not prove that the resource is global or that existing bulk adapters are safe.",
            "Same-file inherited methods use a local C3 order across at most 64 earlier, uniquely bound, undecorated or neutral-decorated classes without explicit metaclasses, with a 4096-entry merge budget. Known data-model descendants and larger role/ancestry graphs are excluded. Unknown or inconsistent MROs defer inherited evidence; missing bulk methods are not inferred through unknown external bases. Aliases declared as class members, rebound, overloaded, descriptor and decorated bulk members are deferred. Direct instance member writes and source-proven literal builtin setattr/delattr calls in visible local ancestors remain uncertain across method overrides; known receiver __class__ writes defer the whole API. Constructor chaining and opaque mutation calls are not inferred. Dynamic dispatch and imported inheritance remain type-checker and review concerns.",
            "Adapters use straight-line calls, scalar and one-item list/tuple/set aliases, stable local aliases of bound self methods, and private instance helpers, with a bounded 64-state walk. Local callable aliases must retain the original self binding and be called without rebinding or escape. Bulk async generators defer adapter consumption proof, including anext and awaitability; known reverse calls remain errors. Complex control flow requires an exact exception or a simple adapter helper.",
            "Requires the original item and shared parameters to reach the bulk call and rejects original-receiver reverse calls through at most 64 visible same-class methods. Reverse scans stop each statement list after a direct return or raise and prune literal Boolean branches and certainly short-circuited Boolean operands. Unknown flow, active comprehensions and potentially consumed generators retain potential reverse edges; no general control-flow or consumption proof is attempted. It does not prove database batching, result projection, authorization, atomicity or arbitrary external side effects.",
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
        if context.static_resource_provenance.dynamic_namespace:
            return []
        classes = _stable_classes(tree, context.module_imports)
        diagnostics: list[Diagnostic] = []
        for owner in classes.values():
            ancestors = _local_ancestors(owner, classes)
            if (
                ancestors is None
                or not any(candidate.name.endswith(_ROLES) for candidate in ancestors)
                or any(is_data_type(candidate) for candidate in ancestors)
                or any(
                    context.module_imports.resolves(
                        base.value if isinstance(base, ast.Subscript) else base,
                        sources=TYPING_SOURCES,
                        symbol="Protocol",
                    )
                    for base in owner.bases
                )
            ):
                continue
            diagnostics.extend(_owner_diagnostics(owner, classes, ancestors, context, self.code))
        return diagnostics


def _stable_classes(tree: ast.Module, imports: ImportIndex) -> dict[str, ast.ClassDef]:
    bindings = Counter(name for statement in tree.body for name in scope_bound_names([statement]))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and bindings[node.name] == 1
        and not node.keywords
        and all(decorator_name(d, node, tree, imports) in _NEUTRAL_DECORATORS for d in node.decorator_list)
    }


def _local_ancestors(owner: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> tuple[ast.ClassDef, ...] | None:
    pending = [owner]
    seen: set[ast.ClassDef] = set()
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        if len(seen) >= _MAX_CLASS_STATES:
            return None
        seen.add(candidate)
        for base in candidate.bases:
            target = base.value if isinstance(base, ast.Subscript) else base
            parent = classes.get(target.id) if isinstance(target, ast.Name) else None
            if parent is not None and parent.lineno < candidate.lineno:
                pending.append(parent)
    return tuple(sorted(seen, key=lambda candidate: candidate.lineno))


@dataclass(frozen=True, slots=True)
class _Surface:
    methods: dict[str, _Method]
    uncertain: frozenset[str]
    unknown_base: bool


@dataclass(frozen=True, slots=True)
class _Call:
    name: str
    bindings: dict[str, _Symbol]
    await_result: bool = False


def _owner_diagnostics(
    owner: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    ancestors: tuple[ast.ClassDef, ...],
    context: PythonFileContext,
    code: str,
) -> list[Diagnostic]:
    surface = _inherited_methods(owner, classes, context, ancestors)
    if "__class__" in surface.uncertain:
        return []
    diagnostics: list[Diagnostic] = []
    for name, singleton in methods(owner).items():
        if name not in _OPERATIONS or name in surface.uncertain or not _concrete_instance(singleton, context):
            continue
        if _bound_resource_update(singleton, surface, classes, context):
            continue
        problem = _operation_problem(singleton, surface, context)
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


def _concrete_instance(method: _Method, context: PythonFileContext) -> bool:
    return bool(_parameters(method)) and _stable_instance_body(method, context)


def _stable_instance_body(method: _Method, context: PythonFileContext) -> bool:
    if method.args.vararg or method.args.kwarg:
        return False
    if any(_decorator_name(d, method, context) not in _NEUTRAL_DECORATORS for d in method.decorator_list):
        return False
    body = [
        s
        for s in method.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]
    return bool(body) and not all(_stub(statement) for statement in body)


def _bound_resource_update(
    singleton: _Method, surface: _Surface, classes: dict[str, ast.ClassDef], context: PythonFileContext
) -> bool:
    if singleton.name != "update" or surface.unknown_base or has_own_yield(singleton):
        return False
    owner = context.parents.get(singleton)
    if not isinstance(owner, ast.ClassDef):
        return False
    ancestors = _local_ancestors(owner, classes)
    if ancestors is None or _BULK_OPERATIONS & surface.uncertain:
        return False
    if any(_BULK_OPERATIONS & scope_bound_names(candidate.body) for candidate in ancestors):
        return False
    getter = methods(owner).get("get")
    if getter is None or "get" in surface.uncertain or getter is not surface.methods.get("get"):
        return False
    positional = [*getter.args.posonlyargs, *getter.args.args]
    if len(positional) != 1 or positional[0].arg != "self" or getter.args.kwonlyargs or getter.args.defaults:
        return False
    if has_own_yield(getter) or not _stable_instance_body(getter, context):
        return False
    model = _local_aggregate_return(getter, owner, classes, context)
    return model is not None and model is _local_aggregate_return(singleton, owner, classes, context)


def _local_aggregate_return(
    method: _Method, owner: ast.ClassDef, classes: dict[str, ast.ClassDef], context: PythonFileContext
) -> ast.ClassDef | None:
    annotation = context.annotation_semantics.parse(method.returns)
    if not isinstance(annotation, ast.Name):
        return None
    if any(
        isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple) and parameter.name == annotation.id
        for scope in (owner, method)
        for parameter in scope.type_params
    ):
        return None
    model = classes.get(annotation.id)
    if model is None or model.lineno >= owner.lineno:
        return None
    proof = context.static_resource_provenance
    if proof.wildcard or proof.binding(annotation.id, method) is not model:
        return None
    if proof.runtime_binding(annotation.id, model) is not model:
        return None
    return model if _known_aggregate_model(model, context) else None


def _known_aggregate_model(model: ast.ClassDef, context: PythonFileContext) -> bool:
    for base in model.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        qualified = context.module_imports.resolved_qualified_name(target)
        if qualified in _AGGREGATE_MODEL_BASES and context.static_resource_provenance.imported(target, qualified):
            return True
    return False


def _decorator_name(expression: ast.expr, method: _Method, context: PythonFileContext) -> str | None:
    owner = context.parents.get(method)
    if not isinstance(owner, ast.ClassDef) or context.tree is None:
        return None
    # Class decorators and method decorators execute in distinct namespaces.
    name = decorator_name(expression, owner, context.tree, context.module_imports)
    return decorator_name(expression, method, owner, context.module_imports) if name is not None else None


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
    owner: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    context: PythonFileContext,
    ancestors: tuple[ast.ClassDef, ...],
) -> _Surface:
    order = _local_mro(owner, classes, context.module_imports, ancestors)
    result: dict[str, _Method] = {}
    uncertain: set[str] = set()
    instance_bound = {name for candidate in ancestors for name in instance_member_bindings(candidate, context)}
    # An unresolved MRO cannot prove inherited dispatch; own bindings remain evidence.
    for candidate in reversed(order if order is not None else (owner,)):
        declared = methods(candidate)
        writes = instance_member_bindings(candidate, context)
        instance_bound.update(writes)
        bound = scope_bound_names(candidate.body) | writes
        for name in bound:
            result.pop(name, None)
        result.update(declared)
        uncertain.difference_update(bound)
        uncertain.update(bound - declared.keys() - _literal_members(candidate))
    return _Surface(result, frozenset(uncertain | instance_bound), unknown_base=order is None)


def _local_mro(
    owner: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    imports: ImportIndex,
    ancestors: tuple[ast.ClassDef, ...],
) -> tuple[ast.ClassDef, ...] | None:
    linearizations: dict[_Base, tuple[_Base, ...]] = {"builtins.object": ("builtins.object",)}
    for qualified in _NEUTRAL_BASES:
        name = qualified.replace("typing_extensions.", "typing.")
        linearizations[name] = (
            (name, "typing.Generic", "builtins.object") if name == "typing.Protocol" else (name, "builtins.object")
        )
    steps = 0
    for candidate in ancestors:
        bases = _mro_bases(candidate, classes, imports)
        if bases is None:
            return None
        merged = _c3_merge([list(linearizations[base]) for base in bases] + [list(bases)])
        if merged is None:
            return None
        steps += len(merged)
        if steps > _MAX_MRO_STEPS:
            return None
        linearizations[candidate] = (candidate, *merged)
    return tuple(candidate for candidate in linearizations[owner] if isinstance(candidate, ast.ClassDef))


def _mro_bases(owner: ast.ClassDef, classes: dict[str, ast.ClassDef], imports: ImportIndex) -> list[_Base] | None:
    bases: list[_Base] = []
    for base in owner.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        parent = _mro_base(target, owner, classes, imports)
        if parent is None:
            return None
        bases.append(parent)
    if len(bases) != len(set(bases)) or len(bases) > _MAX_CLASS_STATES:
        return None
    return bases or ["builtins.object"]


def _mro_base(
    target: ast.expr, owner: ast.ClassDef, classes: dict[str, ast.ClassDef], imports: ImportIndex
) -> _Base | None:
    parent = classes.get(target.id) if isinstance(target, ast.Name) else None
    if parent is not None and parent.lineno < owner.lineno:
        return parent
    qualified = imports.resolved_qualified_name(target)
    if qualified in _NEUTRAL_BASES:
        return qualified.replace("typing_extensions.", "typing.")
    if isinstance(target, ast.Name) and target.id == "object" and imports.builtin_is_unshadowed("object"):
        return "builtins.object"
    return None


def _c3_merge(sequences: list[list[_Base]]) -> tuple[_Base, ...] | None:
    merged: list[_Base] = []
    while sequences:
        head = _c3_head(sequences)
        if head is None:
            return None
        merged.append(head)
        sequences = [sequence[1:] if sequence[0] == head else sequence for sequence in sequences]
        sequences = [sequence for sequence in sequences if sequence]
    return tuple(merged)


def _c3_head(sequences: list[list[_Base]]) -> _Base | None:
    for sequence in sequences:
        head = sequence[0]
        if not any(head in tail[1:] for tail in sequences):
            return head
    return None


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


def _operation_problem(singleton: _Method, surface: _Surface, context: PythonFileContext) -> str | None:
    bulk_name = f"{singleton.name}_many"
    names = (bulk_name, "get_by_ids") if singleton.name == "get" else (bulk_name,)
    if any(candidate in surface.uncertain for candidate in names):
        return None
    bulks = [surface.methods[candidate] for candidate in names if candidate in surface.methods]
    if not bulks:
        return None if surface.unknown_base else "has no declared bulk operation."
    if any(not _supported_bulk(bulk, context) for bulk in bulks):
        return None
    if any(_reaches(bulk.name, singleton.name, surface.methods, context) for bulk in bulks):
        return "has a bulk operation that calls back through the singleton."
    problems = [_adapter_problem(singleton, bulk, surface.methods, context) for bulk in bulks]
    return None if None in problems else problems[0]


def _supported_bulk(bulk: _Method, context: PythonFileContext) -> bool:
    return (
        not bulk.args.vararg
        and not bulk.args.kwarg
        and all(
            _decorator_name(d, bulk, context) in _NEUTRAL_DECORATORS | _ABSTRACT_DECORATORS for d in bulk.decorator_list
        )
    )


def _adapter_problem(
    singleton: _Method, bulk: _Method, available: dict[str, _Method], context: PythonFileContext
) -> str | None:
    # Async generators are consumed rather than awaited; defer after checking known reverse calls.
    if isinstance(bulk, ast.AsyncFunctionDef) and has_own_yield(bulk):
        return None
    if not _parameters(bulk):
        return "has no instance bulk operation accepting items."
    if not _concrete_instance(bulk, context) and not any(
        _decorator_name(d, bulk, context) == "abc.abstractmethod" for d in bulk.decorator_list
    ):
        return "has only an unimplemented bulk stub."
    bindings = {
        p.arg: _Symbol(origin=f"input:{p.arg}", immutable=_annotation_type(p, context) in _IMMUTABLE_SCALAR_TYPES)
        for p in _parameters(singleton)
    }
    if not _delegates(singleton, bulk, available, bindings, context):
        return "does not delegate its original item and shared context to the bulk operation."
    return None


def _annotation_type(parameter: ast.arg, context: PythonFileContext) -> str | None:
    annotation = context.annotation_semantics.parse(parameter.annotation)
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    root = target
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return None
    owner = context.parents.get(parameter)
    while owner is not None:
        if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and any(
            isinstance(p, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple) and p.name == root.id
            for p in owner.type_params
        ):
            return None
        owner = context.parents.get(owner)
    imports = context.imports
    qualified = imports.resolved_qualified_name(target) if target is not None else None
    if (
        qualified is not None
        and target is not None
        and not context.static_resource_provenance.imported(target, qualified)
    ):
        qualified = None
    if (
        isinstance(target, ast.Name)
        and imports.builtin_is_unshadowed(target.id)
        and context.static_resource_provenance.builtin_namespace_untouched
    ):
        qualified = f"builtins.{target.id}"
    if isinstance(annotation, ast.Subscript) and qualified not in _COLLECTION_TYPES:
        return None
    return qualified


def _reaches(start: str, target: str, available: dict[str, _Method], context: PythonFileContext) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending and len(seen) < _MAX_STATES:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for node in _reverse_nodes(available[name]):
            if not isinstance(node, ast.Call):
                continue
            called = _called_method(node, available[name], context, allow_escaped=True)
            if called is None:
                continue
            if called == target:
                return True
            if called in available:
                pending.append(called)
    return False


def _reverse_nodes(method: _Method) -> Iterator[ast.AST]:
    pending: list[ast.AST] = [method]
    while pending:
        node = pending.pop()
        if node is not method and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield node
        pending.extend(reversed(list(_reverse_children(node))))


def _reverse_children(node: ast.AST) -> Iterator[ast.AST]:
    if (
        isinstance(node, ast.If | ast.IfExp)
        and isinstance(node.test, ast.Constant)
        and isinstance(node.test.value, bool)
    ):
        yield node.test
        branch = node.body if node.test.value else node.orelse
        if isinstance(branch, list):
            yield from _reverse_sequence(branch)
        else:
            yield branch
        return
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            yield value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, bool)
                and value.value is isinstance(node.op, ast.Or)
            ):
                break
        return
    yield from _reverse_field_nodes(node)


def _reverse_field_nodes(node: ast.AST) -> Iterator[ast.AST]:
    fields: Iterator[tuple[str, object]] = ast.iter_fields(node)
    for _, field in fields:
        match field:
            case ast.AST():
                yield field
            case _ if _is_field_list(field):
                yield from _reverse_sequence(child for child in field if isinstance(child, ast.AST))
            case _:
                pass


def _is_field_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _reverse_sequence(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    for node in nodes:
        yield node
        if isinstance(node, ast.Return | ast.Raise):
            break


def _called_method(
    call: ast.Call, method: _Method, context: PythonFileContext, *, allow_escaped: bool = False
) -> str | None:
    direct = _self_call(call)
    if direct is not None or not isinstance(call.func, ast.Name):
        if (
            allow_escaped
            and isinstance(call.func, ast.Attribute)
            and not _original_self(call.func.value, method, context)
        ):
            return None
        return direct
    proof = context.static_resource_provenance
    binding = proof.binding(call.func.id, call)
    if not isinstance(binding, ast.Name) or proof.scope(binding) is not method:
        return None
    if proof.runtime_binding(binding.id, binding) is not binding:
        return None
    value = proof.assignment_value(binding, call)
    if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name) or value.value.id != "self":
        return None
    if not _original_self(value.value, method, context):
        return None
    # An escape cannot prove delegation, but cannot erase an explicit reverse call either.
    if not allow_escaped and not all(
        _local_invocation(read, method, context) for read in proof.binding_reads(binding.id, binding)
    ):
        return None
    return value.attr


def _original_self(receiver: ast.AST, method: _Method, context: PythonFileContext) -> bool:
    positional = [*method.args.posonlyargs, *method.args.args]
    # Comprehension scopes retain lexical receiver proof; any local rebinding makes it uncertain.
    return (
        bool(positional)
        and positional[0].arg == "self"
        and (context.static_resource_provenance.binding("self", receiver) is positional[0])
    )


def _self_call(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
        return call.func.attr
    return None


def _local_invocation(read: ast.Name, method: _Method, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    if not isinstance(parent, ast.Call) or parent.func is not read:
        return False
    owner: ast.AST = parent
    while owner is not method:
        if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            return False
        ancestor = context.parents.get(owner)
        if ancestor is None:
            return False
        owner = ancestor
    return True


def _symbol(value: ast.expr, symbols: dict[str, _Symbol]) -> _Symbol:
    match value:
        case ast.Name(id=name):
            return symbols.get(name, _UNKNOWN)
        case ast.List() | ast.Tuple() | ast.Set():
            items = _collection_symbols(value, symbols)
            if items is None or len(items) != 1:
                return _UNKNOWN
            item = items[0]
            return _Symbol(item=item, allocation=value) if item != _UNKNOWN else _UNKNOWN
        case _:
            return _UNKNOWN


def _collection_symbols(value: ast.List | ast.Tuple | ast.Set, symbols: dict[str, _Symbol]) -> list[_Symbol] | None:
    items: list[_Symbol] = []
    for element in value.elts:
        if not isinstance(element, ast.Starred):
            item = _symbol(element, symbols)
        else:
            expanded = element.value
            if isinstance(expanded, ast.List | ast.Tuple | ast.Set) and not expanded.elts:
                continue
            symbol = _symbol(expanded, symbols)
            if symbol.item is None:
                return None
            item = symbol.item
        if not (isinstance(value, ast.Set) and item.immutable and item in items):
            items.append(item)
    return items


def _delegates(
    singleton: _Method,
    bulk: _Method,
    available: dict[str, _Method],
    initial: dict[str, _Symbol],
    context: PythonFileContext,
) -> bool:
    pending = [_Call(singleton.name, initial)]
    seen: set[tuple[str, tuple[tuple[str, _Symbol], ...], bool]] = set()
    inputs = frozenset(initial.values())
    collection_parameters = [p.arg for p in _parameters(bulk) if _annotation_type(p, context) in _COLLECTION_TYPES]
    collection_parameter = collection_parameters[0] if len(collection_parameters) == 1 else None
    while pending and len(seen) < _MAX_STATES:
        candidate = pending.pop()
        state = candidate.name, tuple(sorted(candidate.bindings.items())), candidate.await_result
        if state in seen:
            continue
        seen.add(state)
        for call in _method_calls(
            available[candidate.name], available, candidate.bindings, context, await_result=candidate.await_result
        ):
            if call.name == bulk.name and _matches(call.bindings, inputs, collection_parameter):
                return True
            if call.name.startswith("_"):
                pending.append(call)
    return False


def _matches(bindings: dict[str, _Symbol], inputs: frozenset[_Symbol], collection_parameter: str | None) -> bool:
    wrapped = [name for name, value in bindings.items() if value.item is not None]
    if len(wrapped) != 1 or (collection_parameter is not None and wrapped[0] != collection_parameter):
        return False
    item = bindings[wrapped[0]].item
    if item is None or item not in inputs:
        return False
    for value in inputs - {item}:
        name = value.origin.removeprefix("input:")
        if value not in bindings.values():
            return False
        if name in bindings and bindings[name] != value:
            return False
    return True


def _method_calls(
    method: _Method,
    available: dict[str, _Method],
    bindings: dict[str, _Symbol],
    context: PythonFileContext,
    *,
    await_result: bool = False,
) -> list[_Call]:
    calls: list[_Call] = []
    symbols = {**bindings, "self": _SELF}
    # Only a synchronous, eager helper can forward its caller's await to a returned coroutine.
    await_result = await_result and isinstance(method, ast.FunctionDef) and not has_own_yield(method)
    for statement in method.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if not isinstance(statement, ast.Assign | ast.AnnAssign | ast.Expr | ast.Return | ast.Raise | ast.Pass):
            break
        nodes = _eager_nodes(statement)
        awaited = {id(node.value) for node in nodes if isinstance(node, ast.Await)}
        if await_result and isinstance(statement, ast.Return):
            awaited.add(id(statement.value))
        calls.extend(_bound_calls(nodes, method, available, symbols, context, awaited=awaited))
        _assignment(statement, symbols)
        if isinstance(statement, ast.Return | ast.Raise):
            break
    return calls


def _bound_calls(
    nodes: list[ast.AST],
    method: _Method,
    available: dict[str, _Method],
    symbols: dict[str, _Symbol],
    context: PythonFileContext,
    *,
    awaited: set[int],
) -> list[_Call]:
    calls: list[_Call] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        called = _called_method(node, method, context)
        if called is None:
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and not symbols.get(node.func.value.id, _UNKNOWN).immutable
            ):
                _invalidate(node.func.value, symbols)
            continue
        if symbols.get("self") != _SELF:
            continue
        target = available.get(called)
        if target is None or (isinstance(target, ast.AsyncFunctionDef) and id(node) not in awaited):
            continue
        bindings = _bind(node, target, symbols)
        if bindings is not None:
            calls.append(
                _Call(called, bindings, await_result=id(node) in awaited and isinstance(target, ast.FunctionDef))
            )
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


def _bind(call: ast.Call, method: _Method, symbols: dict[str, _Symbol]) -> dict[str, _Symbol] | None:
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


def _invalidate(target: ast.expr, symbols: dict[str, _Symbol]) -> None:
    if isinstance(target, ast.Subscript):
        target = target.value
    if not isinstance(target, ast.Name):
        return
    value = symbols.get(target.id, _UNKNOWN)
    for name, symbol in tuple(symbols.items()):
        if symbol == value:
            symbols[name] = _UNKNOWN


def _assignment(statement: ast.stmt, symbols: dict[str, _Symbol]) -> None:
    if not isinstance(statement, ast.Assign | ast.AnnAssign) or statement.value is None:
        return
    value = _symbol(statement.value, symbols)
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    for target in targets:
        if isinstance(target, ast.Name):
            symbols[target.id] = value
        else:
            _invalidate(target, symbols)
