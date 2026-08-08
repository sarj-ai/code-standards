"""SARJ007 — `try` block with more than 3 top-level statements that can raise.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_fat_try_blocks.py
"""

from __future__ import annotations

import ast
import enum
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._logging import is_logger_expr
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_MAX_TRY_BODY_STATEMENTS = 3


#: Terminal method names of the metrics/tracing recorders.
_OBSERVABILITY_METHODS = frozenset(
    {
        "inc",
        "dec",
        "observe",
        "set_to_current_time",
        "labels",
        "increment",
        "decrement",
        "gauge",
        "timing",
        "histogram",
        "record_exception",
        "add_event",
        "set_attribute",
        "set_attributes",
        "set_status",
    }
)

#: Clock reads.
_CLOCK_ROOTS = frozenset({"time", "datetime", "date"})
_CLOCK_METHODS = frozenset(
    {
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "time",
        "time_ns",
        "now",
        "utcnow",
    }
)

#: Value-shaping builtins.
_INERT_BUILTINS = frozenset(
    {
        "abs",
        "bool",
        "float",
        "format",
        "id",
        "int",
        "len",
        "list",
        "repr",
        "round",
        "str",
        "tuple",
        "type",
    }
)


def _can_raise(stmt: ast.stmt) -> bool:
    """Report whether the statement can plausibly raise when the `try` runs."""
    calls = [n for n in _walk_same_scope(stmt) if isinstance(n, (ast.Call, ast.Await))]
    if not calls:
        return False
    return not all(isinstance(n, ast.Call) and _is_observability_call(n) for n in calls)


def _walk_same_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Walk `node` without descending into nested `def` / `async def` / `lambda` bodies."""
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        yield current
        skipped_body = _nested_scope_body_ids(current)
        stack.extend(child for child in children(current) if id(child) not in skipped_body)


def _nested_scope_body_ids(node: ast.AST) -> frozenset[int]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return frozenset(id(stmt) for stmt in node.body)
    if isinstance(node, ast.Lambda):
        return frozenset({id(node.body)})
    return frozenset()


def _is_observability_call(call: ast.Call) -> bool:
    """Report whether `call` is instrumentation — logging, metrics/tracing, or a clock read."""
    func = call.func
    if is_logger_expr(func):
        return True
    if isinstance(func, ast.Name):
        return func.id in _INERT_BUILTINS
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _CLOCK_METHODS and _attr_root(func) in _CLOCK_ROOTS:
        return True
    # A metrics/tracing recorder — including `counter.labels(...).inc()`, whose
    # receiver is itself an observability call.
    if func.attr in _OBSERVABILITY_METHODS:
        receiver = func.value
        return not isinstance(receiver, ast.Call) or _is_observability_call(receiver)
    return False


def _attr_root(expr: ast.expr) -> str | None:
    """Find the leftmost identifier of an attribute chain (`a.b.c` -> `a`)."""
    current = expr
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


class _Exit(enum.Enum):
    RAISE = enum.auto()
    SWALLOW = enum.auto()
    FALL = enum.auto()


def _stmt_exits(stmt: ast.stmt) -> set[_Exit]:
    """Compute the set of ways control can leave `stmt`."""
    match stmt:
        case ast.Raise():
            return {_Exit.RAISE}
        case ast.Return() | ast.Break() | ast.Continue():
            return {_Exit.SWALLOW}
        case ast.If(body=body, orelse=orelse):
            else_exits = _body_exits(orelse) if orelse else {_Exit.FALL}
            return _body_exits(body) | else_exits
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _body_exits(body)
        case _:
            return {_Exit.FALL}


def _body_exits(stmts: list[ast.stmt]) -> set[_Exit]:
    exits: set[_Exit] = set()
    for stmt in stmts:
        stmt_exits = _stmt_exits(stmt)
        exits |= stmt_exits - {_Exit.FALL}
        if _Exit.FALL not in stmt_exits:
            return exits
    exits.add(_Exit.FALL)
    return exits


def _all_handlers_reraise(handlers: list[ast.ExceptHandler]) -> bool:
    """Report whether every `except` handler is guaranteed to re-raise on all paths."""
    return bool(handlers) and all(_body_exits(h.body) == {_Exit.RAISE} for h in handlers)


class NoFatTryBlocks(Rule):
    id: str = "no-fat-try-blocks"
    code: str = "SARJ007"
    description: str = "Try block has too many throwing statements — keep try blocks skinny."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Try, ast.TryStar):
            # An `else`/`finally` clause is a deliberate success/cleanup contract
            # that couples the body to the handler — don't fight it on length.
            if node.orelse or node.finalbody:
                continue
            # When every `except` re-raises, the wide body is a deliberate
            # error-context/metric wrapper, not an over-broad swallow — exempt.
            if _all_handlers_reraise(node.handlers):
                continue
            throwing = sum(_can_raise(stmt) for stmt in node.body)
            if throwing <= _MAX_TRY_BODY_STATEMENTS:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"try block has {throwing} statements that can raise "
                        f"(max {_MAX_TRY_BODY_STATEMENTS}) — try blocks should "
                        "isolate the throwing statement(s); move non-throwing "
                        "work outside the try."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
