from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator


_MAX_DEPTH = 12


def control_condition(node: ast.AST, parent: ast.AST) -> tuple[ast.expr, bool] | None:
    match parent:
        case ast.IfExp():
            accepted, rejected = node is parent.body, node is parent.orelse
        case ast.If():
            accepted, rejected = node in parent.body, node in parent.orelse
        case _:
            return None
    return (parent.test, accepted) if accepted or rejected else None


def literal_truth(node: ast.expr, *, depth: int = 0) -> bool | None:
    if depth >= _MAX_DEPTH:
        return None
    match node:
        case ast.Constant(value=None):
            return False
        case ast.Constant(value=(str() | bytes() | bool() | int() | float() | complex()) as value):
            return bool(value)
        case ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items):
            return None if any(isinstance(item, ast.Starred) for item in items) else bool(items)
        case ast.Dict(keys=keys):
            return None if None in keys else bool(keys)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            truth = literal_truth(operand, depth=depth + 1)
            return not truth if truth is not None else None
        case ast.UnaryOp(
            op=ast.UAdd() | ast.USub(), operand=ast.Constant(value=(int() | float() | complex()) as value)
        ):
            return bool(value)
        case ast.BoolOp():
            return _literal_boolean_truth(node, depth=depth)
        case ast.Compare(
            left=ast.Constant(value=left),
            ops=[ast.Eq() | ast.NotEq() as comparison],
            comparators=[ast.Constant(value=right)],
        ):
            equal = left == right
            return equal if isinstance(comparison, ast.Eq) else not equal
        case _:
            return None


def _literal_boolean_truth(node: ast.BoolOp, *, depth: int) -> bool | None:
    truths = [literal_truth(member, depth=depth + 1) for member in node.values]
    decisive = isinstance(node.op, ast.Or)
    if decisive in truths:
        return decisive
    return not decisive if all(truth is not None for truth in truths) else None


def reachable_branch(node: ast.AST, parent: ast.AST) -> bool:
    if isinstance(node, ast.stmt) and any(_stops_suite(sibling) for sibling in previous_statements(node, parent)):
        return False
    match parent:
        case ast.Assert() if node is parent.msg:
            return literal_truth(parent.test) is not True
        case ast.If() | ast.IfExp() if (condition := control_condition(node, parent)) is not None:
            test, positive = condition
            truth = literal_truth(test)
            return truth is None or truth is positive
        case ast.While() if node in parent.body and literal_truth(parent.test) is False:
            return False
        case ast.BoolOp() if isinstance(node, ast.expr) and node in parent.values:
            preceding = parent.values[: parent.values.index(node)]
            decisive = isinstance(parent.op, ast.Or)
            return all(literal_truth(member) is not decisive for member in preceding)
        case _:
            return True


def _stops_suite(node: ast.stmt) -> bool:
    return isinstance(node, ast.Return | ast.Raise | ast.Break | ast.Continue) or (
        isinstance(node, ast.Assert) and literal_truth(node.test) is False
    )


def previous_statements(node: ast.stmt, parent: ast.AST) -> tuple[ast.stmt, ...]:
    for statements in _statement_suites(parent):
        if node in statements:
            return tuple(statements[: statements.index(node)])
    return ()


def _statement_suites(parent: ast.AST) -> Iterator[list[ast.stmt]]:
    match parent:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            yield parent.body
            yield parent.orelse
        case ast.Try() | ast.TryStar():
            yield parent.body
            yield parent.orelse
            yield parent.finalbody
        case (
            ast.Module()
            | ast.Interactive()
            | ast.FunctionDef()
            | ast.AsyncFunctionDef()
            | ast.ClassDef()
            | ast.With()
            | ast.AsyncWith()
            | ast.ExceptHandler()
            | ast.match_case()
        ):
            yield parent.body
        case _:
            return
