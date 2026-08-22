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
_BRANCH_NODES = (ast.If, ast.IfExp, ast.Match, ast.Try, ast.TryStar)
_PAIR_SIZE = 2


class _MethodPair(NamedTuple):
    singleton: ast.FunctionDef | ast.AsyncFunctionDef
    bulk: ast.FunctionDef | ast.AsyncFunctionDef


class _BulkResultTypes(NamedTuple):
    key: ast.expr | None
    value: ast.expr


@final
class GetDelegatesToGetMany(Rule):
    id = "get-delegates-to-get-many"
    code = "SARJ421"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Require compatible singleton store reads to delegate to their bulk implementation.",
        rationale=(
            "Independent singleton and bulk queries can drift in filtering, row conversion, authorization, "
            "and missing-row behavior while maintaining two database access paths."
        ),
        remediation=(
            "Implement `get` through the compatible `get_many([key])` or `get_by_ids([key])` method and "
            "project its documented zero-or-one result."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only concrete methods declared together in a production store module are inspected.",
            "The methods must have one typed key, a list result for get_many or dict result for get_by_ids, and the same sync shape.",
            "Branching singleton implementations are excluded because caching, locking, validation, or authorization may differ intentionally.",
        ),
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
                        "        return await self.query_one(user_id)\n\n"
                        "    async def get_many(self, user_ids: list[UserId]) -> list[User]:\n"
                        "        return await self.query_many(user_ids)\n",
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
                        "        rows = await self.get_many([user_id])\n"
                        "        return rows[0] if rows else None\n\n"
                        "    async def get_many(self, user_ids: list[UserId]) -> list[User]:\n"
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
            if _has_branch(singleton) or _calls_method(singleton, bulk.name) or _calls_method(bulk, "get"):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=singleton.lineno,
                    col=singleton.col_offset + 1,
                    code=self.code,
                    message=(
                        f"This store defines compatible `get` and `{bulk.name}` methods; implement `get` through "
                        f"`{bulk.name}([key])` so singleton and bulk reads share one contract, or document why "
                        "their semantics differ."
                    ),
                    severity=Severity.ERROR,
                )
            )
        return diagnostics


def _compatible_pair(
    owner: ast.ClassDef,
) -> _MethodPair | None:
    methods = [node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    singletons = [node for node in methods if node.name == "get" and _is_concrete(node)]
    bulks = [node for node in methods if node.name in _BULK_NAMES and _is_concrete(node)]
    if len(singletons) != 1 or len(bulks) != 1:
        return None
    singleton, bulk = singletons[0], bulks[0]
    if isinstance(singleton, ast.AsyncFunctionDef) is not isinstance(bulk, ast.AsyncFunctionDef):
        return None
    singleton_key = _single_key_annotation(singleton)
    bulk_key = _bulk_key_annotation(bulk)
    singleton_value = _nullable_value(singleton.returns)
    bulk_types = _bulk_result_types(bulk.returns, bulk.name)
    if singleton_key is None or bulk_key is None or singleton_value is None or bulk_types is None:
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
    return not (
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


def _single_key_annotation(method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    if method.args.posonlyargs or method.args.vararg or method.args.kwarg or method.args.kwonlyargs:
        return None
    if len(method.args.args) != _PAIR_SIZE or method.args.defaults:
        return None
    self_arg, key_arg = method.args.args
    if self_arg.arg not in {"self", "cls"}:
        return None
    return key_arg.annotation


def _bulk_key_annotation(method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    annotation = _single_key_annotation(method)
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value) in {
        "List",
        "Sequence",
        "list",
        "typing.List",
        "typing.Sequence",
    }:
        return annotation.slice
    return None


def _nullable_value(annotation: ast.expr | None) -> ast.expr | None:
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value) in {"Optional", "typing.Optional"}:
        return annotation.slice
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        if _is_none_annotation(annotation.left):
            return annotation.right
        if _is_none_annotation(annotation.right):
            return annotation.left
    return None


def _bulk_result_types(annotation: ast.expr | None, name: str) -> _BulkResultTypes | None:
    if not isinstance(annotation, ast.Subscript):
        return None
    base = _qualified_name(annotation.value)
    if name == "get_many" and base in {"List", "list", "typing.List"}:
        return _BulkResultTypes(None, annotation.slice)
    if (
        name == "get_by_ids"
        and base in {"Dict", "dict", "typing.Dict"}
        and isinstance(annotation.slice, ast.Tuple)
        and len(annotation.slice.elts) == _PAIR_SIZE
    ):
        return _BulkResultTypes(annotation.slice.elts[0], annotation.slice.elts[1])
    return None


def _has_branch(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(node, _BRANCH_NODES) for node in _method_nodes(method))


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
