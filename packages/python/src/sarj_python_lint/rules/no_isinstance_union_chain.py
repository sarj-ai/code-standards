"""SARJ003 — `if/elif isinstance(...)` chains that dispatch over a *local* closed union.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_isinstance_union_chain.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path


# A dispatch chain needs at least this many `isinstance` arms to be flagged.
_MIN_CHAIN_LENGTH = 2

# `isinstance(x, T)` takes exactly two positional arguments.
_ISINSTANCE_ARG_COUNT = 2

# Exclude builtins and ABCs even when a same-named local class shadows them.
_EXCLUDED_TYPE_NAMES = frozenset(
    {
        "dict",
        "str",
        "list",
        "tuple",
        "set",
        "frozenset",
        "int",
        "float",
        "bool",
        "complex",
        "bytes",
        "bytearray",
        "type",
        "object",
        "Exception",
        "BaseException",
        "NoneType",
        "Unset",
        "datetime",
        "date",
        "time",
        "timedelta",
        "Mapping",
        "MutableMapping",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Container",
        "Set",
        "Hashable",
        "Callable",
    }
)


class NoIsinstanceUnionChain(Rule):
    id: str = "no-isinstance-union-chain"
    code: str = "SARJ003"
    description: str = (
        "if/elif isinstance chain over locally-defined classes with an exhaustive "
        "terminal — prefer match/case with assert_never for compile-time exhaustiveness."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        local_classes = frozenset(node.name for node in nodes(tree, ast.ClassDef))
        elif_nodes: set[int] = set()
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.If):
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                elif_nodes.add(id(node.orelse[0]))
            if id(node) in elif_nodes:
                continue
            count = _qualifying_chain_length(node, local_classes)
            if count >= _MIN_CHAIN_LENGTH:
                diags.append(
                    Diagnostic(
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        message=(
                            f"if/elif isinstance chain over {count} local classes — prefer "
                            "match/case with assert_never for exhaustiveness."
                        ),
                    )
                )
        return diags


def _qualifying_chain_length(head: ast.If, local_classes: frozenset[str]) -> int:
    """Count the arms if `head` is a local-closed-union dispatch chain, else 0."""
    first_target: ast.expr | None = None
    count = 0
    current: ast.If | None = head
    while current is not None:
        parsed = _isinstance_single_type(current.test)
        if parsed is None:
            return 0
        target, type_node = parsed
        if not isinstance(type_node, ast.Name):
            return 0
        type_name = type_node.id
        if type_name in _EXCLUDED_TYPE_NAMES or type_name not in local_classes:
            return 0
        if first_target is None:
            first_target = target
        elif not _ast_equal(target, first_target):
            return 0
        count += 1
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
        else:
            if not _is_exhaustive_terminal(orelse):
                return 0
            current = None
    return count


def _is_exhaustive_terminal(orelse: list[ast.stmt]) -> bool:
    """Report whether the trailing `else` block terminates instead of falling through."""
    if not orelse:
        return False
    return any(_stmt_terminates(stmt) for stmt in orelse)


def _stmt_terminates(stmt: ast.stmt) -> bool:
    match stmt:
        case ast.Raise() | ast.Return() | ast.Assert():
            return True
        case ast.Expr(value=ast.Call(func=func)):
            return _is_assert_never(func)
        case _:
            return False


def _is_assert_never(func: ast.expr) -> bool:
    match func:
        case ast.Name(id="assert_never"):
            return True
        case ast.Attribute(attr="assert_never"):
            return True
        case _:
            return False


def _ast_equal(a: ast.expr, b: ast.expr) -> bool:
    """Compare `a` and `b` structurally, ignoring source positions."""
    return ast.dump(a) == ast.dump(b)


def _isinstance_single_type(test: ast.expr) -> tuple[ast.expr, ast.expr] | None:
    """Parse `test` as `isinstance(x, T)` with a single (non-tuple) type argument."""
    if not isinstance(test, ast.Call):
        return None
    if not (isinstance(test.func, ast.Name) and test.func.id == "isinstance"):
        return None
    if len(test.args) != _ISINSTANCE_ARG_COUNT or test.keywords:
        return None
    target, type_node = test.args
    return target, type_node
