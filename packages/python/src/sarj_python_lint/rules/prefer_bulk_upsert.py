from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._resource_provenance import import_name_for_binding
from sarj_python_lint.rules._store_writes import (
    StoreOwners,
    compatible_collection_pair,
    depends_on_target,
    discarded_call,
    known_single_iteration,
    method_parameters,
    read_pair,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._store_writes import Function


_CONTRACT = "class UserStore:\n    async def upsert(self, user: UserInput) -> User:\n        ...\n    async def upsert_many(self, users: list[UserInput]) -> list[User]:\n        ...\n"
_READ_CONTRACT = "class UserStore:\n    async def get(self, key: str) -> User | None:\n        ...\n    async def get_many(self, keys: list[str]) -> list[User]:\n        ...\n"
_WRITE_PAIRS: Final[Mapping[str, str]] = MappingProxyType(
    {name: name + "_many" for name in ("upsert", "create", "insert", "update", "delete")}
)
_READ_BULK_NAMES = ("get_many", "get_by_ids")


@dataclass(frozen=True, slots=True)
class _BulkCandidate:
    call: ast.Call
    bulk_name: str
    fan_out: bool = False


@dataclass(frozen=True, slots=True)
class _CallShape:
    call: ast.Call
    awaited: bool
    target: ast.expr


@final
class PreferBulkUpsert(ProjectRule):
    id = "prefer-bulk-upsert"
    code = "SARJ516"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use declared compatible bulk APIs for repeated singleton reads and writes.",
        rationale="Serial singleton calls and eager coroutine fan-out can repeat database or remote work. A source-declared compatible bulk API identifies an opportunity to review batching, including bulk implementations that repeat backend singleton calls.",
        remediation="Collect inputs and use the declared bulk API in bounded batches after reviewing missing rows, cardinality, duplicate keys, ordering, failure atomicity, concurrency, cancellation, backpressure, tenant scope, and transaction or snapshot behavior. Preserve deliberately per-row transactions or effects with an exact suppression.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Synchronous for loops require one discarded singleton call. List/dict comprehensions require one synchronous generator and a value consisting solely of the singleton call. Writes use compatible upsert/create/insert/update/delete and corresponding *_many pairs; get uses get_many or get_by_ids. Await mode must match the declared method.",
            "Eager fan-out requires a directly awaited, import-proven stdlib asyncio.gather with one starred list/generator comprehension, a raw async singleton element, no filters, additional calls or keywords, and an async compatible bulk peer. TaskGroup, task factories and opaque scheduling are excluded. Concurrency, failure, cancellation and backpressure require review.",
            "Receivers must resolve to typed parameters or constructor-injected attributes. Signatures require one required input and matching scalar/collection input types. Writes retain matching scalar/collection output types. Read output may be T or T | None/Optional[T] versus list/Sequence[T] or dict/Mapping[K, T], with K matching the input key type. Missing-row placeholders, duplicate keys, cardinality and request order require review.",
            "Annotated first-party imports use the project index; unresolved, inherited, overloaded, decorated, rebound, reassigned and dynamic contracts are excluded, as are explicit metaclasses and class keywords. Unknown backend APIs and dictionary/cache joins do not prove a batch opportunity.",
            "Other result-dependent loops, filtered/nested comprehensions, async streams, loop else clauses, extra effects and per-row exception or transaction blocks are excluded. Batch atomicity and tenant/auth or snapshot behavior require review; this remains a warning without an autofix.",
            "Maintained tests are checked; generated/vendor sources are excluded. A bulk method is not invented when none is declared.",
        ),
        examples=(
            RuleExample(
                example_id="serial-upserts",
                title="Collect writes for an available bulk command",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    for user in users:\n        await store.upsert(user)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-upsert",
                title="Use the existing bulk command",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    await store.upsert_many(users)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="read-comprehension",
                scenario="read-comprehension",
                title="Review repeated reads against an available bulk API",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _READ_CONTRACT
                        + "async def load(store: UserStore, keys: list[str]):\n    return [await store.get(key) for key in keys]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-read",
                scenario="read-comprehension",
                title="Read the batch after reviewing missing rows and ordering",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _READ_CONTRACT
                        + "async def load(store: UserStore, keys: list[str]):\n    return await store.get_many(keys)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="write-comprehension",
                scenario="write-comprehension",
                title="Review a comprehension of singleton writes",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    return [await store.upsert(user) for user in users]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-write-results",
                scenario="write-comprehension",
                title="Return bulk results after reviewing cardinality and failures",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    return await store.upsert_many(users)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="eager-read-fanout",
                scenario="async-fanout",
                title="Concurrency still schedules one operation per input",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "import asyncio\n"
                        + _READ_CONTRACT
                        + "async def load(store: UserStore, keys: list[str]):\n    return await asyncio.gather(*(store.get(key) for key in keys))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-read-without-fanout",
                scenario="async-fanout",
                title="Use bounded bulk reads after reviewing concurrency and failures",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _READ_CONTRACT
                        + "async def load(store: UserStore, keys: list[str]):\n    return await store.get_many(keys)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
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
            or not any(name in context.symbol_source for name in (*_WRITE_PAIRS, "get"))
            or context.tree is None
        ):
            return []
        owners = StoreOwners(context)
        if owners.provenance.dynamic_namespace:
            return []
        findings: list[Diagnostic] = []
        for node in context.nodes(ast.For, ast.ListComp, ast.DictComp, ast.Await):
            candidate = _bulk_candidate(node, owners)
            if candidate is None:
                continue
            call, bulk_name = candidate.call, candidate.bulk_name
            if is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"This {'fan-out' if candidate.fan_out else 'serial'} {call.func.attr if isinstance(call.func, ast.Attribute) else 'singleton call'} has a declared compatible `{bulk_name}`; review bounded batching while preserving missing rows, cardinality, order, duplicate-key, atomicity, concurrency, failure, cancellation, backpressure, tenant, and transaction semantics.",
                )
            )
        return findings


def _bulk_candidate(
    node: ast.For | ast.ListComp | ast.DictComp | ast.Await, owners: StoreOwners
) -> _BulkCandidate | None:
    match node:
        case ast.For():
            candidate = discarded_call(node)
            if candidate is None:
                return None
            call, awaited = candidate
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and (not _isolated_call(node, call) or not _simple_target(node.target))
            ):
                return None
            return _shape_candidate(_CallShape(call, awaited, node.target), owners)
        case ast.Await():
            return _gather_candidate(node, owners)
        case _:
            shape = _comprehension_shape(node)
            return _shape_candidate(shape, owners) if shape is not None else None


def _shape_candidate(shape: _CallShape, owners: StoreOwners, *, fan_out: bool = False) -> _BulkCandidate | None:
    call = shape.call
    if not isinstance(call.func, ast.Attribute):
        return None
    owner = owners.receiver(call.func.value, call)
    if owner is None:
        return None
    names = _READ_BULK_NAMES if call.func.attr == "get" else (_WRITE_PAIRS.get(call.func.attr),)
    for bulk_name in names:
        if bulk_name is None:
            continue
        pair = (
            read_pair(*owner, bulk_name)
            if call.func.attr == "get"
            else compatible_collection_pair(*owner, call.func.attr, bulk_name)
        )
        if pair is None:
            continue
        if fan_out and (has_own_yield(pair.singleton) or has_own_yield(pair.bulk)):
            continue
        if _call_binds(shape, pair.singleton, fan_out=fan_out):
            return _BulkCandidate(call, bulk_name, fan_out)
    return None


def _call_binds(shape: _CallShape, singleton: Function, *, fan_out: bool) -> bool:
    if isinstance(singleton, ast.AsyncFunctionDef) != (shape.awaited or fan_out):
        return False
    parameters = method_parameters(singleton)
    if parameters is None:
        return False
    argument = _command_argument(shape.call, parameters[0].arg)
    return argument is not None and not isinstance(argument, ast.Starred) and depends_on_target(argument, shape.target)


def _comprehension_shape(node: ast.ListComp | ast.DictComp | ast.GeneratorExp) -> _CallShape | None:
    if len(node.generators) != 1:
        return None
    generator = node.generators[0]
    if generator.is_async or generator.ifs or known_single_iteration(generator.iter):
        return None
    value = node.value if isinstance(node, ast.DictComp) else node.elt
    awaited = isinstance(value, ast.Await)
    call = value.value if awaited else value
    if not isinstance(call, ast.Call) or not _isolated_call(node, call):
        return None
    if not _simple_target(generator.target):
        return None
    return _CallShape(call, awaited, generator.target)


def _simple_target(target: ast.expr) -> bool:
    return not any(isinstance(child, ast.Attribute | ast.Subscript) for child in ast.walk(target))


def _isolated_call(node: ast.AST, call: ast.Call) -> bool:
    return not any(
        (isinstance(child, ast.Call) and child is not call)
        or (isinstance(child, ast.Await) and child.value is not call)
        or isinstance(child, ast.NamedExpr | ast.Lambda)
        or (isinstance(child, ast.ListComp | ast.DictComp | ast.SetComp | ast.GeneratorExp) and child is not node)
        for child in ast.walk(node)
    )


def _gather_candidate(node: ast.Await, owners: StoreOwners) -> _BulkCandidate | None:
    call = node.value
    if (
        not isinstance(call, ast.Call)
        or call.keywords
        or len(call.args) != 1
        or not isinstance(call.args[0], ast.Starred)
        or not isinstance(comprehension := call.args[0].value, ast.ListComp | ast.GeneratorExp)
    ):
        return None
    shape = _comprehension_shape(comprehension)
    if shape is None or any(isinstance(child, ast.Await) for child in ast.walk(comprehension)):
        return None
    if not _stdlib_gather(call.func, owners) or not _gather_namespace_untouched(owners):
        return None
    return _shape_candidate(shape, owners, fan_out=True)


def _stdlib_gather(function: ast.expr, owners: StoreOwners) -> bool:
    root = function.value if isinstance(function, ast.Attribute) else function
    if not isinstance(root, ast.Name) or owners.provenance.wildcard:
        return False
    binding = owners.provenance.runtime_binding(root.id, function)
    return (
        isinstance(binding, ast.alias)
        and import_name_for_binding(function, binding, owners.context.parents.get(binding)) == "asyncio.gather"
    )


def _gather_namespace_untouched(owners: StoreOwners) -> bool:
    for node in owners.context.nodes(ast.Name, ast.Attribute):
        parent = owners.context.parents.get(node)
        for qualified in _gather_import_references(node, owners):
            if qualified == "asyncio":
                if isinstance(parent, ast.Attribute) and parent.value is node and not parent.attr.startswith("__"):
                    continue
            elif qualified == "asyncio.gather" and isinstance(parent, ast.Call) and parent.func is node:
                continue
            return False
    return True


def _gather_import_references(node: ast.Name | ast.Attribute, owners: StoreOwners) -> tuple[str, ...]:
    root: ast.expr = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return ()
    provenance = owners.provenance
    bindings = provenance.runtime_bindings.lookup(provenance.scope(root), root.id)
    if bindings is None:
        # Ambiguous/global writes must not conceal a possible imported-module mutation.
        bindings = tuple(binding for names in provenance.bindings.values() for binding in names.get(root.id, ()))
    return tuple(
        qualified
        for binding in bindings
        if isinstance(binding, ast.alias)
        and (qualified := import_name_for_binding(node, binding, owners.context.parents.get(binding)))
        in {"asyncio", "asyncio.gather"}
    )


def _command_argument(call: ast.Call, parameter: str) -> ast.expr | None:
    if len(call.args) == 1 and not call.keywords:
        return call.args[0]
    if not call.args and len(call.keywords) == 1 and call.keywords[0].arg == parameter:
        return call.keywords[0].value
    return None
