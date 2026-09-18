from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module


if TYPE_CHECKING:
    from pathlib import Path


_BULK_NAMES = frozenset({"get_by_ids", "get_many"})
_COLLECTION_TYPES = frozenset(
    {
        "Collection",
        "Iterable",
        "List",
        "Sequence",
        "Set",
        "list",
        "set",
        "typing.Collection",
        "typing.Iterable",
        "typing.List",
        "typing.Sequence",
        "typing.Set",
        "collections.abc.Collection",
        "collections.abc.Iterable",
        "collections.abc.Sequence",
    }
)
_PAIR_SIZE = 2
_DISTINCT_ACCESS_MARKERS = frozenset(
    {
        "authorization",
        "authorize",
        "cache",
        "cached",
        "consistency",
        "lock",
        "locked",
        "mutex",
        "permission",
        "replica",
        "semaphore",
        "transaction",
        "transactional",
    }
)
_LOCKING_SQL = ("FOR UPDATE", "FOR SHARE", "SKIP LOCKED")
_NEUTRAL_DECORATORS = frozenset({"abstractmethod", "overload", "override"})


class _MethodPair(NamedTuple):
    singleton: ast.FunctionDef | ast.AsyncFunctionDef
    bulk: ast.FunctionDef | ast.AsyncFunctionDef


class _BulkResultTypes(NamedTuple):
    key: ast.expr | None
    value: ast.expr


class _KeyContract(NamedTuple):
    shared: tuple[tuple[str, ast.expr], ...]
    key_name: str
    key: ast.expr


class _WriteExpectation(NamedTuple):
    bulk_key: ast.arg
    expected_key: str
    status_parameter: ast.arg | None
    expected_status: str | None


@final
class StoreGetDelegatesToBulkRead(Rule):
    id = "store-get-delegates-to-bulk-read"
    code = "SARJ421"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A store singleton operation should reuse its equivalent bulk implementation.",
        rationale=(
            "Independent singleton and bulk queries can drift in filtering, mutation semantics, row conversion, "
            "authorization, timestamps, and missing-row behavior while maintaining two database access paths."
        ),
        remediation=(
            "Delegate only when tenant, authorization, consistency, cache, lock, transaction, conversion, and missing-row "
            "semantics match. Otherwise add an exact SARJ421 suppression naming the concrete semantic difference."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Concrete wrappers declared with a canonical bulk method in a production Store class are inspected; the canonical method may be abstract.",
            "Reads retain the strict get/get_many contract. Writes require a typed collection key, compatible context and result types, and a recognizable many-method name.",
            "The canonical write topology is the exact set_many_to_status(..., status) shape, with wrappers binding the matching status enum member.",
            "Wrappers with try/finally or other unsupported compound control flow are not diagnosed.",
            "Singleton implementations with explicit cache or lock identifiers are excluded because their access path differs intentionally.",
            "Signature compatibility is advisory: dynamic helpers and behavior not visible in the two method bodies require review.",
        ),
        aliases=("get-delegates-to-get-many",),
        examples=(
            RuleExample(
                example_id="duplicate-singleton-query",
                title="Do not maintain a second singleton query path",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/user_store.py",
                        "class UserStore:\n"
                        "    async def get(self, user_id: UserId) -> User | None:\n"
                        "        return await self.fetchrow('SELECT * FROM users WHERE id = %s', user_id)\n\n"
                        "    async def get_many(self, user_ids: list[UserId]) -> list[User]:\n"
                        "        return await self.fetch('SELECT * FROM users WHERE id = ANY(%s)', user_ids)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="singleton-delegates",
                title="Delegate the singleton read to the bulk implementation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/user_store.py",
                        "class UserStore:\n"
                        "    async def get(self, user_id: UserId) -> User | None:\n"
                        "        rows = await self.get_by_ids([user_id])\n"
                        "        return rows.get(user_id)\n\n"
                        "    async def get_by_ids(self, user_ids: list[UserId]) -> dict[UserId, User]:\n"
                        "        return await self.query_many(user_ids)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="duplicate-singleton-write",
                scenario="write",
                title="Do not maintain a second singleton mutation path",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "class TaskStore:\n"
                        "    async def set_to_failed(self, task_id: str) -> Task:\n"
                        "        return await self._update_status(task_id, TaskStatus.FAILED)\n\n"
                        "    async def set_many_to_status(\n"
                        "        self, task_ids: Collection[str], status: TaskStatus\n"
                        "    ) -> list[Task]:\n"
                        "        return await self._update_many(task_ids, status)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="singleton-write-delegates",
                scenario="write",
                title="Route singleton mutations through the bulk primitive",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "class TaskStore:\n"
                        "    async def set_to_failed(self, task_id: str) -> Task:\n"
                        "        rows = await self.set_many_to_status([task_id], TaskStatus.FAILED)\n"
                        "        return rows[0]\n\n"
                        "    async def set_many_to_status(\n"
                        "        self, task_ids: Collection[str], status: TaskStatus\n"
                        "    ) -> list[Task]:\n"
                        "        return await self._update_many(task_ids, status)\n",
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
        if not is_store_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for statement in tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            methods = _methods_by_name(statement)
            read_pair = _compatible_pair(statement)
            pairs = ([] if read_pair is None else [read_pair]) + _compatible_write_pairs(statement)
            for singleton, bulk in pairs:
                is_read = singleton.name == "get"
                if _already_canonical(singleton, bulk, methods, is_read=is_read):
                    continue
                operation = "keyed read" if is_read else "store operation"
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=singleton.lineno,
                        col=singleton.col_offset + 1,
                        code=self.code,
                        message=(
                            f"Annotated signatures suggest that `{statement.name}.{singleton.name}` and `{bulk.name}` "
                            f"expose the same {operation} through separate paths. Route the singleton through the bulk "
                            "implementation when observable semantics match; otherwise suppress SARJ421 with the "
                            "concrete difference."
                        ),
                        severity=Severity.WARNING,
                    )
                )
        return diagnostics


def _already_canonical(
    singleton: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    *,
    is_read: bool,
) -> bool:
    if _has_distinct_access_semantics(singleton, bulk):
        return True
    if is_read:
        return (
            _calls_method(singleton, bulk.name) or _shares_private_helper(singleton, bulk) or _calls_method(bulk, "get")
        )
    return _has_unsupported_write_control_flow(singleton) or _valid_write_delegation(singleton, bulk, methods)


def _has_unsupported_write_control_flow(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(statement, (ast.Try, ast.TryStar)) for statement in method.body)


def _methods_by_name(owner: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {node.name: node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _compatible_write_pairs(owner: ast.ClassDef) -> list[_MethodPair]:
    if not owner.name.endswith("Store"):
        return []
    declared_methods = [node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = [
        node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_concrete(node)
    ]
    status_bulks = [method for method in declared_methods if _status_bulk_contract(method) is not None]
    if status_bulks:
        return _status_write_pairs(methods, status_bulks)

    # Before a parameterized status primitive exists, still catch the common
    # inverted shape where set_many_to_failed loops over set_to_failed.
    return _specialized_status_pairs(methods)


def _status_write_pairs(
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef],
    status_bulks: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[_MethodPair]:
    pairs: list[_MethodPair] = []
    for bulk in status_bulks:
        pairs.extend(
            _MethodPair(wrapper, bulk)
            for wrapper in methods
            if wrapper is not bulk and _compatible_status_wrapper(wrapper, bulk)
        )
    return pairs


def _specialized_status_pairs(methods: list[ast.FunctionDef | ast.AsyncFunctionDef]) -> list[_MethodPair]:
    singletons = [method for method in methods if method.name.startswith("set_to_")]
    bulks = [method for method in methods if method.name.startswith("set_many_to_")]
    pairs: list[_MethodPair] = []
    for singleton in singletons:
        pairs.extend(
            _MethodPair(singleton, bulk)
            for bulk in bulks
            if _same_operation_name(singleton.name, bulk.name) and _compatible_write_contracts(singleton, bulk)
        )
    return pairs


def _status_bulk_contract(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.arg, ast.expr, ast.arg] | None:
    if method.name != "set_many_to_status":
        return None
    parameters = _typed_parameters(method)
    if parameters is None:
        return None
    collection_parameters = [
        (parameter, item_type)
        for parameter in parameters
        if (item_type := _collection_item_type(parameter.annotation)) is not None
    ]
    discriminators = [parameter for parameter in parameters if parameter.arg == "status"]
    if len(collection_parameters) != 1 or len(discriminators) != 1:
        return None
    key, item_type = collection_parameters[0]
    discriminator = discriminators[0]
    return key, item_type, discriminator


def _compatible_status_wrapper(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if isinstance(wrapper, ast.AsyncFunctionDef) is not isinstance(bulk, ast.AsyncFunctionDef):
        return False
    member = _status_wrapper_member(wrapper.name)
    contract = _status_bulk_contract(bulk)
    if member is None or contract is None:
        return False
    bulk_key, item_type, discriminator = contract
    wrapper_parameters = _typed_parameters(wrapper)
    bulk_parameters = _typed_parameters(bulk)
    if wrapper_parameters is None or bulk_parameters is None or discriminator.annotation is None:
        return False
    wrapper_key = _status_wrapper_key(wrapper, wrapper_parameters, bulk_key, item_type)
    if wrapper_key is None:
        return False
    wrapper_context = [parameter for parameter in wrapper_parameters if parameter is not wrapper_key]
    bulk_context = [parameter for parameter in bulk_parameters if parameter not in {bulk_key, discriminator}]
    if not _same_parameter_contracts(wrapper_context, bulk_context):
        return False
    return _status_wrapper_result_compatible(wrapper, bulk)


def _status_wrapper_key(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    parameters: list[ast.arg],
    bulk_key: ast.arg,
    item_type: ast.expr,
) -> ast.arg | None:
    if wrapper.name.startswith("set_many_to_"):
        matches = [parameter for parameter in parameters if _collection_key_matches(parameter, bulk_key, item_type)]
    else:
        matches = [parameter for parameter in parameters if _scalar_key_matches(parameter, bulk_key, item_type)]
    return matches[0] if len(matches) == 1 else None


def _collection_key_matches(parameter: ast.arg, bulk_key: ast.arg, item_type: ast.expr) -> bool:
    wrapper_item = _collection_item_type(parameter.annotation)
    return (
        wrapper_item is not None
        and _same_annotation(wrapper_item, item_type)
        and _normalized_key_name(parameter.arg) == _normalized_key_name(bulk_key.arg)
    )


def _scalar_key_matches(parameter: ast.arg, bulk_key: ast.arg, item_type: ast.expr) -> bool:
    return (
        parameter.annotation is not None
        and _same_annotation(parameter.annotation, item_type)
        and _normalized_key_name(parameter.arg) == _normalized_key_name(bulk_key.arg)
    )


def _status_wrapper_result_compatible(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if wrapper.name.startswith("set_many_to_"):
        return wrapper.returns is not None and (
            _is_none_annotation(wrapper.returns)
            or (bulk.returns is not None and _same_annotation(wrapper.returns, bulk.returns))
        )
    return _compatible_write_results(wrapper.returns, bulk.returns)


def _status_wrapper_member(name: str) -> str | None:
    for prefix in ("set_to_", "set_many_to_"):
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return None


def _compatible_write_contracts(
    singleton: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if isinstance(singleton, ast.AsyncFunctionDef) is not isinstance(bulk, ast.AsyncFunctionDef):
        return False
    bulk_parameters = _typed_parameters(bulk)
    singleton_parameters = _typed_parameters(singleton)
    if bulk_parameters is None or singleton_parameters is None:
        return False
    collection_parameters = [
        (parameter, item_type)
        for parameter in bulk_parameters
        if (item_type := _collection_item_type(parameter.annotation)) is not None
    ]
    if len(collection_parameters) != 1:
        return False
    bulk_key, key_type = collection_parameters[0]
    singleton_keys = [
        parameter
        for parameter in singleton_parameters
        if parameter.annotation is not None
        and _same_annotation(parameter.annotation, key_type)
        and _normalized_key_name(parameter.arg) == _normalized_key_name(bulk_key.arg)
    ]
    if len(singleton_keys) != 1:
        return False
    singleton_key = singleton_keys[0]
    singleton_context = [parameter for parameter in singleton_parameters if parameter is not singleton_key]
    bulk_context = [parameter for parameter in bulk_parameters if parameter is not bulk_key]
    if not _same_parameter_contracts(
        singleton_context,
        bulk_context,
    ):
        return False
    if not _same_operation_name(singleton.name, bulk.name):
        return False
    return _compatible_write_results(singleton.returns, bulk.returns)


def _typed_parameters(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg] | None:
    if method.args.vararg or method.args.kwarg:
        return None
    parameters = [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]
    if not parameters or parameters[0].arg not in {"self", "cls"}:
        return None
    typed = parameters[1:]
    return typed if typed and all(parameter.annotation is not None for parameter in typed) else None


def _collection_item_type(annotation: ast.expr | None) -> ast.expr | None:
    if not isinstance(annotation, ast.Subscript) or _qualified_name(annotation.value) not in _COLLECTION_TYPES:
        return None
    return annotation.slice


def _same_parameter_contracts(left: list[ast.arg], right: list[ast.arg]) -> bool:
    return len(left) == len(right) and all(
        left_parameter.arg == right_parameter.arg
        and left_parameter.annotation is not None
        and right_parameter.annotation is not None
        and _same_annotation(left_parameter.annotation, right_parameter.annotation)
        for left_parameter, right_parameter in zip(left, right, strict=True)
    )


def _same_annotation(left: ast.expr, right: ast.expr) -> bool:
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def _same_operation_name(singleton_name: str, bulk_name: str) -> bool:
    return [part for part in singleton_name.split("_") if part not in {"bulk", "many"}] == [
        part for part in bulk_name.split("_") if part not in {"bulk", "many"}
    ]


def _compatible_write_results(singleton: ast.expr | None, bulk: ast.expr | None) -> bool:
    if singleton is None or bulk is None:
        return False
    if _is_none_annotation(bulk):
        return True
    bulk_types = _bulk_result_types(bulk)
    return bulk_types is not None and _same_annotation(singleton, bulk_types.value)


def _valid_write_delegation(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> bool:
    expectation = _write_expectation(wrapper, bulk)
    if expectation is None:
        return False
    wrapper_parameters = _typed_parameters(wrapper)
    if wrapper_parameters is None:
        return False
    initial_bindings = {parameter.arg: f"name:{parameter.arg}" for parameter in wrapper_parameters}
    pending = [(wrapper.name, initial_bindings)]
    visited: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    while pending:
        current, bindings = pending.pop()
        state = current, tuple(sorted(bindings.items()))
        if state in visited:
            continue
        visited.add(state)
        method = methods.get(current)
        if method is None:
            continue
        reached_bulk, next_states = _delegation_targets(method, bulk, methods, bindings, expectation)
        if reached_bulk:
            return True
        pending.extend(next_states)
    return False


def _delegation_targets(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    bindings: dict[str, str],
    expectation: _WriteExpectation,
) -> tuple[bool, list[tuple[str, dict[str, str]]]]:
    next_states: list[tuple[str, dict[str, str]]] = []
    for call, awaited in _delegation_calls(method):
        resolved = _resolve_delegation_call(call, methods, bindings, awaited=awaited)
        if resolved is None:
            continue
        called, called_bindings = resolved
        if called == bulk.name:
            return _matches_write_expectation(called_bindings, expectation), next_states
        next_states.append((called, called_bindings))
    return False, next_states


def _resolve_delegation_call(
    call: ast.Call,
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    bindings: dict[str, str],
    *,
    awaited: bool,
) -> tuple[str, dict[str, str]] | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    called = call.func.attr
    called_method = methods.get(called)
    if called_method is None or (isinstance(called_method, ast.AsyncFunctionDef) and not awaited):
        return None
    called_bindings = _bind_call(call, called_method, bindings)
    return None if called_bindings is None else (called, called_bindings)


def _matches_write_expectation(bindings: dict[str, str], expectation: _WriteExpectation) -> bool:
    if bindings.get(expectation.bulk_key.arg) != expectation.expected_key:
        return False
    return expectation.status_parameter is None or (
        bindings.get(expectation.status_parameter.arg) == expectation.expected_status
    )


def _write_expectation(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _WriteExpectation | None:
    wrapper_parameters = _typed_parameters(wrapper)
    bulk_parameters = _typed_parameters(bulk)
    if wrapper_parameters is None or bulk_parameters is None:
        return None
    bulk_keys = [parameter for parameter in bulk_parameters if _collection_item_type(parameter.annotation) is not None]
    if len(bulk_keys) != 1:
        return None
    bulk_key = bulk_keys[0]
    expected_key = _expected_wrapper_key(wrapper_parameters, bulk_key)
    if expected_key is None:
        return None
    return _expectation_with_status(wrapper, bulk, bulk_key, expected_key)


def _expected_wrapper_key(wrapper_parameters: list[ast.arg], bulk_key: ast.arg) -> str | None:
    wrapper_collection_keys = [
        parameter for parameter in wrapper_parameters if _collection_item_type(parameter.annotation) is not None
    ]
    if wrapper_collection_keys:
        return f"name:{wrapper_collection_keys[0].arg}"
    item_type = _collection_item_type(bulk_key.annotation)
    if item_type is None:
        return None
    wrapper_keys = [
        parameter for parameter in wrapper_parameters if _scalar_key_matches(parameter, bulk_key, item_type)
    ]
    return f"one:name:{wrapper_keys[0].arg}" if len(wrapper_keys) == 1 else None


def _expectation_with_status(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk_key: ast.arg,
    expected_key: str,
) -> _WriteExpectation | None:
    status_contract = _status_bulk_contract(bulk)
    if status_contract is None:
        return _WriteExpectation(bulk_key, expected_key, None, None)
    status_parameter = status_contract[2]
    member = _status_wrapper_member(wrapper.name)
    if status_parameter.annotation is None or member is None:
        return None
    expected_status = f"attr:{_qualified_name(status_parameter.annotation)}.{member.upper()}"
    return _WriteExpectation(bulk_key, expected_key, status_parameter, expected_status)


def _delegation_calls(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.Call, bool]]:
    calls: list[tuple[ast.Call, bool]] = []
    for statement in method.body:
        candidate = _statement_delegation_call(statement)
        if candidate is not None:
            if _call_count(statement) != 1:
                return []
            calls.append(candidate)
        elif not isinstance(statement, ast.Raise) and _call_count(statement):
            return []
        if isinstance(statement, (ast.Return, ast.Raise)):
            break
    return calls if len(calls) == 1 else []


def _statement_delegation_call(statement: ast.stmt) -> tuple[ast.Call, bool] | None:
    expression: ast.expr | None = None
    if isinstance(statement, (ast.Return, ast.Expr, ast.Assign, ast.AnnAssign)):
        expression = statement.value
    elif isinstance(statement, ast.If):
        expression = statement.test
    if isinstance(expression, ast.NamedExpr):
        expression = expression.value
    if isinstance(expression, ast.Subscript):
        expression = expression.value
    awaited = isinstance(expression, ast.Await)
    if awaited:
        expression = expression.value
    if (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and isinstance(expression.func.value, ast.Name)
        and expression.func.value.id in {"self", "cls"}
    ):
        return expression, awaited
    return None


def _call_count(node: ast.AST) -> int:
    return sum(isinstance(child, ast.Call) for child in ast.walk(node))


def _bind_call(
    call: ast.Call,
    called: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: dict[str, str],
) -> dict[str, str] | None:
    parameters = _typed_parameters(called)
    if parameters is None or len(call.args) > len(parameters):
        return None
    result = {
        parameter.arg: _symbol(argument, bindings) for parameter, argument in zip(parameters, call.args, strict=False)
    }
    parameter_names = {parameter.arg for parameter in parameters}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in parameter_names or keyword.arg in result:
            return None
        result[keyword.arg] = _symbol(keyword.value, bindings)
    return result if len(result) == len(parameters) else None


def _symbol(expression: ast.expr, bindings: dict[str, str]) -> str:
    if isinstance(expression, ast.Name):
        return bindings.get(expression.id, f"unknown:{expression.id}")
    if isinstance(expression, ast.Attribute):
        return f"attr:{_qualified_name(expression)}"
    if isinstance(expression, (ast.List, ast.Tuple, ast.Set)) and len(expression.elts) == 1:
        return f"one:{_symbol(expression.elts[0], bindings)}"
    if (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id in {"list", "set", "tuple"}
        and len(expression.args) == 1
        and not expression.keywords
    ):
        return _symbol(expression.args[0], bindings)
    return f"unknown:{ast.dump(expression, include_attributes=False)}"


def _compatible_pair(
    owner: ast.ClassDef,
) -> _MethodPair | None:
    if not owner.name.endswith("Store"):
        return None
    methods = [node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    singletons = [node for node in methods if node.name == "get" and _is_concrete(node)]
    bulks = [node for node in methods if node.name in _BULK_NAMES and _is_concrete(node)]
    if len(singletons) != 1 or len(bulks) != 1:
        return None
    singleton, bulk = singletons[0], bulks[0]
    if isinstance(singleton, ast.AsyncFunctionDef) is not isinstance(bulk, ast.AsyncFunctionDef):
        return None
    return _compatible_method_contracts(singleton, bulk)


def _compatible_method_contracts(
    singleton: ast.FunctionDef | ast.AsyncFunctionDef, bulk: ast.FunctionDef | ast.AsyncFunctionDef
) -> _MethodPair | None:
    singleton_contract = _singleton_key_contract(singleton)
    bulk_contract = _bulk_key_contract(bulk)
    singleton_value = _nullable_value(singleton.returns)
    bulk_types = _bulk_result_types(bulk.returns)
    if singleton_contract is None or bulk_contract is None or singleton_value is None or bulk_types is None:
        return None
    singleton_key = singleton_contract.key
    bulk_key = bulk_contract.key
    if not _same_shared_contract(singleton_contract.shared, bulk_contract.shared):
        return None
    if _normalized_key_name(singleton_contract.key_name) != _normalized_key_name(bulk_contract.key_name):
        return None
    result_key, result_value = bulk_types
    if ast.dump(singleton_key, include_attributes=False) != ast.dump(bulk_key, include_attributes=False):
        return None
    if result_key is not None and ast.dump(singleton_key, include_attributes=False) != ast.dump(
        result_key, include_attributes=False
    ):
        return None
    if ast.dump(singleton_value, include_attributes=False) != ast.dump(result_value, include_attributes=False):
        return None
    return _MethodPair(singleton, bulk)


def _is_concrete(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(
        _qualified_name(decorator).split(".")[-1] in {"abstractmethod", "overload"}
        for decorator in method.decorator_list
    ):
        return False
    return not _raises_not_implemented(method) and not (
        len(method.body) == 1
        and (
            isinstance(method.body[0], ast.Pass)
            or (
                isinstance(method.body[0], ast.Expr)
                and isinstance(method.body[0].value, ast.Constant)
                and method.body[0].value.value is Ellipsis
            )
            or isinstance(method.body[0], ast.Raise)
        )
    )


def _raises_not_implemented(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    final_statement = method.body[-1]
    if not isinstance(final_statement, ast.Raise) or final_statement.exc is None:
        return False
    exception = final_statement.exc.func if isinstance(final_statement.exc, ast.Call) else final_statement.exc
    return _qualified_name(exception).split(".")[-1] == "NotImplementedError"


def _positional_contract(method: ast.FunctionDef | ast.AsyncFunctionDef) -> _KeyContract | None:
    if method.args.posonlyargs or method.args.vararg or method.args.kwarg or method.args.kwonlyargs:
        return None
    if len(method.args.args) < _PAIR_SIZE or method.args.defaults:
        return None
    self_arg, *parameters = method.args.args
    if self_arg.arg not in {"self", "cls"}:
        return None
    *shared, key_arg = parameters
    if key_arg.annotation is None:
        return None
    shared_contract: list[tuple[str, ast.expr]] = []
    for parameter in shared:
        if parameter.annotation is None:
            return None
        shared_contract.append((parameter.arg, parameter.annotation))
    return _KeyContract(tuple(shared_contract), key_arg.arg, key_arg.annotation)


def _singleton_key_contract(method: ast.FunctionDef | ast.AsyncFunctionDef) -> _KeyContract | None:
    return _positional_contract(method)


def _bulk_key_contract(method: ast.FunctionDef | ast.AsyncFunctionDef) -> _KeyContract | None:
    contract = _positional_contract(method)
    if contract is None:
        return None
    annotation = contract.key
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value) in {
        "List",
        "Sequence",
        "list",
        "typing.List",
        "typing.Sequence",
    }:
        return _KeyContract(contract.shared, contract.key_name, annotation.slice)
    return None


def _normalized_key_name(name: str) -> str:
    normalized = name.rstrip("_")
    if normalized.endswith("es"):
        return normalized[:-2]
    if normalized.endswith("s"):
        return normalized[:-1]
    return normalized


def _same_shared_contract(singleton: tuple[tuple[str, ast.expr], ...], bulk: tuple[tuple[str, ast.expr], ...]) -> bool:
    return len(singleton) == len(bulk) and all(
        singleton_name == bulk_name
        and ast.dump(singleton_type, include_attributes=False) == ast.dump(bulk_type, include_attributes=False)
        for (singleton_name, singleton_type), (bulk_name, bulk_type) in zip(singleton, bulk, strict=True)
    )


def _nullable_value(annotation: ast.expr | None) -> ast.expr | None:
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value) in {"Optional", "typing.Optional"}:
        return annotation.slice
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        if _is_none_annotation(annotation.left):
            return annotation.right
        if _is_none_annotation(annotation.right):
            return annotation.left
    return None


def _bulk_result_types(annotation: ast.expr | None) -> _BulkResultTypes | None:
    if not isinstance(annotation, ast.Subscript):
        return None
    base = _qualified_name(annotation.value)
    if base in {"List", "list", "typing.List"}:
        return _BulkResultTypes(None, annotation.slice)
    if (
        base in {"Dict", "Mapping", "dict", "typing.Dict", "typing.Mapping"}
        and isinstance(annotation.slice, ast.Tuple)
        and len(annotation.slice.elts) == _PAIR_SIZE
    ):
        return _BulkResultTypes(annotation.slice.elts[0], annotation.slice.elts[1])
    return None


def _has_distinct_access_semantics(
    singleton: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return _behavior_signals(singleton) != _behavior_signals(bulk) or _decorators(singleton) != _decorators(bulk)


def _behavior_signals(method: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    signals: set[str] = set()
    for node in _method_nodes(method):
        _record_behavior_signals(node, signals)
    return frozenset(signals)


def _decorators(method: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        name
        for decorator in method.decorator_list
        if (name := _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator).split(".")[-1])
        and name not in _NEUTRAL_DECORATORS
    )


def _shares_private_helper(
    singleton: ast.FunctionDef | ast.AsyncFunctionDef,
    bulk: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return bool(_private_method_calls(singleton) & _private_method_calls(bulk))


def _private_method_calls(method: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        node.func.attr
        for node in _method_nodes(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"self", "cls"}
        and node.func.attr.startswith("_")
        and not node.func.attr.startswith("__")
    )


def _calls_method(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    called_name: str,
) -> bool:
    for node in _method_nodes(method):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            not isinstance(node.func.value, ast.Name)
            or node.func.value.id not in {"cls", "self"}
            or node.func.attr != called_name
        ):
            continue
        return True
    return False


def _method_nodes(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = [*reversed(method.body)]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        nodes.append(node)
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return nodes


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_none_annotation(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _record_behavior_signals(node: ast.AST, signals: set[str]) -> None:
    for name in _identifier_parts(node):
        signals.update(part for part in name.lower().split("_") if part in _DISTINCT_ACCESS_MARKERS)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        signals.update(marker for marker in _LOCKING_SQL if marker in node.value.upper())
    if isinstance(node, ast.keyword) and node.arg in {"for_update", "prepare", "read_only"}:
        signals.add(f"{node.arg}={ast.dump(node.value, include_attributes=False)}")


def _identifier_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    return ()
