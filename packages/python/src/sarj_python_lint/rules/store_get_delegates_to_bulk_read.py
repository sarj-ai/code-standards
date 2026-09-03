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
_NEUTRAL_DECORATORS = frozenset({"override"})


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


@final
class StoreGetDelegatesToBulkRead(Rule):
    id = "store-get-delegates-to-bulk-read"
    code = "SARJ421"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Store `get` should reuse an equivalent `get_many` or `get_by_ids` read path.",
        rationale=(
            "Independent singleton and bulk queries can drift in filtering, row conversion, authorization, "
            "and missing-row behavior while maintaining two database access paths."
        ),
        remediation=(
            "Delegate only when tenant, authorization, consistency, cache, lock, transaction, conversion, and missing-row "
            "semantics match. Otherwise add an exact SARJ421 suppression naming the concrete semantic difference."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only concrete methods declared together in a production store module are inspected.",
            "The methods must have matching typed context parameters, compatible key/result types, and the same sync shape.",
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
            pair = _compatible_pair(statement)
            if pair is None:
                continue
            singleton, bulk = pair
            if (
                _has_distinct_access_semantics(singleton, bulk)
                or _shares_private_read_helper(singleton, bulk)
                or _calls_method(singleton, bulk.name)
                or _calls_method(bulk, "get")
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=singleton.lineno,
                    col=singleton.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Annotated signatures suggest that `{statement.name}.get` and `{bulk.name}` expose the same "
                        "keyed read through separate paths. Share one implementation only when their observable "
                        "semantics match; otherwise suppress SARJ421 with the concrete difference."
                    ),
                    severity=Severity.WARNING,
                )
            )
        return diagnostics


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
        for name in _identifier_parts(node):
            signals.update(part for part in name.lower().split("_") if part in _DISTINCT_ACCESS_MARKERS)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            signals.update(marker for marker in _LOCKING_SQL if marker in node.value.upper())
        if isinstance(node, ast.keyword) and node.arg in {"for_update", "prepare", "read_only"}:
            signals.add(f"{node.arg}={ast.dump(node.value, include_attributes=False)}")
    return frozenset(signals)


def _decorators(method: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        name
        for decorator in method.decorator_list
        if (name := _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator).split(".")[-1])
        and name not in _NEUTRAL_DECORATORS
    )


def _shares_private_read_helper(
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


def _identifier_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    return ()


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
