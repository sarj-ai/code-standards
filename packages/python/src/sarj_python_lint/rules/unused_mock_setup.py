"""SARJ067 — Mock setup the test can never exercise is a lie about what is covered.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_unused_mock_setup.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ067.md
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, NamedTuple, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# The two attributes that *configure* what a mock does when called. Assigning
# either is arrange, never act.
_CONFIG_ATTRS = frozenset({"return_value", "side_effect"})

# Assertions that the mock was never reached. If one of these passes, every
# configuration of that path is provably unobserved.
_NOT_CALLED_ASSERTIONS = frozenset({"assert_not_called", "assert_not_awaited"})

# Reads of the call record. Their presence means the test *does* care whether
# the path was called, so an `assert_not_called` elsewhere is a checkpoint
# rather than the final word.
_INTROSPECTION_ATTRS = frozenset(
    {
        "await_args",
        "await_args_list",
        "await_count",
        "call_args",
        "call_args_list",
        "call_count",
        "called",
        "method_calls",
        "mock_calls",
        "reset_mock",
    }
)

_ASSERT_PREFIX = "assert"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Bodies that belong to a different scope: they are visited when that scope is
# itself processed as a function.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Expression nodes that can run arbitrary user code, so a statement containing
# one may have observed a mock configuration written above it.
_EFFECTFUL_NODES = (
    ast.Attribute,
    ast.Await,
    ast.Call,
    ast.NamedExpr,
    ast.Subscript,
    ast.Yield,
    ast.YieldFrom,
)


class _Finding(NamedTuple):
    """One dead configuration statement and why it is dead."""

    node: ast.stmt
    message: str


class UnusedMockSetup(Rule):
    id: str = "unused-mock-setup"
    code: str = "SARJ067"
    has_evidence: bool = True
    description: str = "Mock setup the test can never exercise — overwritten before use, or asserted never called."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag mock configuration statements that nothing in the test can observe."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        seen: set[tuple[int, int]] = set()
        diags: list[Diagnostic] = []
        for fn in nodes(tree, *_FUNC_NODES):
            for finding in _dead_setups(fn):
                position = (finding.node.lineno, finding.node.col_offset + 1)
                if position in seen:
                    continue
                seen.add(position)
                diags.append(
                    Diagnostic(
                        path=path,
                        line=position[0],
                        col=position[1],
                        code=self.code,
                        message=finding.message,
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _dead_setups(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    yield from _overwritten_before_use(fn)
    yield from _asserted_never_called(fn)


def _overwritten_before_use(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    """Find configurations reassigned before anything could read them."""
    for block in _blocks(fn):
        pending: dict[str, ast.stmt] = {}
        for stmt in block:
            target = _config_target(stmt)
            if target is None:
                if not _is_inert(stmt):
                    pending.clear()
                continue
            previous = pending.get(target)
            if previous is not None:
                yield _Finding(
                    previous,
                    (
                        f"`{target}` is set here and overwritten on line {stmt.lineno} with nothing in "
                        "between that could call the mock, so this value is never used. Delete the dead "
                        "setup, or move the code under test between the two configurations"
                    ),
                )
            pending[target] = stmt


def _asserted_never_called(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[_Finding]:
    """Find configurations of a path the test then asserts was never called."""
    not_called = _not_called_assertions(fn)
    if not not_called:
        return
    introspected = _introspected_paths(fn)
    last_effect = _last_effectful_line(fn)
    for stmt in _scope_statements(fn):
        target = _config_target(stmt)
        if target is None:
            continue
        configured = target.rsplit(".", 1)[0]
        if any(_touches(configured, other) for other in introspected):
            continue
        for asserted, line in not_called.items():
            if line > stmt.lineno and _is_prefix(asserted, configured) and last_effect <= line:
                yield _Finding(
                    stmt,
                    (
                        f"`{target}` is configured here, but the test asserts `{asserted}` was never "
                        "called and nothing runs after that assertion — the configured value can never "
                        "be observed. Delete the setup, or assert on the call it was written for"
                    ),
                )
                break


def _blocks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[list[ast.stmt]]:
    """Walk the statement blocks belonging to this function's own scope."""
    stack: list[ast.AST] = [fn]
    while stack:
        node = stack.pop()
        for block in _child_blocks(node):
            yield block
            stack.extend(stmt for stmt in block if not isinstance(stmt, _NESTED_SCOPES))


def _child_blocks(node: ast.AST) -> list[list[ast.stmt]]:
    """List the statement blocks a compound statement owns."""
    blocks: list[list[ast.stmt]] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        blocks.append(node.body)
    elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        blocks.extend((node.body, node.orelse))
    elif isinstance(node, (ast.With, ast.AsyncWith, ast.ExceptHandler)):
        blocks.append(node.body)
    elif isinstance(node, (ast.Try, ast.TryStar)):
        blocks.extend((node.body, node.orelse, node.finalbody))
        blocks.extend(handler.body for handler in node.handlers)
    elif isinstance(node, ast.Match):
        blocks.extend(case.body for case in node.cases)
    return [block for block in blocks if block]


def _scope_statements(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.stmt]:
    """Walk every statement in the function's own scope."""
    for block in _blocks(fn):
        yield from block


def _own_expressions(stmt: ast.stmt) -> Iterator[ast.AST]:
    """Walk the expressions a statement owns, without descending into other statements."""
    for child in children(stmt):
        if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
            continue
        yield from walk(child)


def _config_target(stmt: ast.stmt) -> str | None:
    """Read the dotted target of a mock configuration assignment."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr not in _CONFIG_ATTRS:
        return None
    return _dotted(target)


def _dotted(node: ast.expr) -> str | None:
    """Render a `Name`-rooted attribute chain as a dotted string."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _is_inert(stmt: ast.stmt) -> bool:
    """Report whether a statement provably cannot execute user code."""
    if isinstance(stmt, (ast.Pass, ast.Import, ast.ImportFrom)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if not isinstance(stmt, ast.Assign):
        return False
    if not all(isinstance(target, ast.Name) for target in stmt.targets):
        # `obj.attr = 1` can hit a property setter, `d[k] = 1` a `__setitem__`.
        return False
    return not any(isinstance(node, _EFFECTFUL_NODES) for node in walk(stmt.value))


def _not_called_assertions(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    """Collect `x.y.assert_not_called()` calls made in this function's scope."""
    found: dict[str, int] = {}
    for stmt in _scope_statements(fn):
        for node in _own_expressions(stmt):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _NOT_CALLED_ASSERTIONS:
                continue
            asserted = _dotted(node.func.value)
            if asserted is not None:
                found[asserted] = max(found.get(asserted, 0), node.lineno)
    return found


def _introspected_paths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect every path the function reads the call record of."""
    found: set[str] = set()
    for node in walk(fn):
        if not isinstance(node, ast.Attribute) or not _is_introspection(node.attr):
            continue
        path = _dotted(node.value)
        if path is not None:
            found.add(path)
    return found


def _is_introspection(attr: str) -> bool:
    if attr in _NOT_CALLED_ASSERTIONS:
        return False
    return attr in _INTROSPECTION_ATTRS or attr.startswith(_ASSERT_PREFIX)


def _last_effectful_line(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Find the last line of the function that can invoke a mock."""
    last = 0
    for node in walk(fn):
        if isinstance(node, ast.Call) and not _is_assertion_call(node):
            last = max(last, node.lineno)
    return last


def _is_assertion_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or not node.func.attr.startswith(_ASSERT_PREFIX):
        return False
    return not any(isinstance(child, ast.Call) for arg in (*node.args, *node.keywords) for child in walk(arg))


def _is_prefix(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}.")


def _touches(path: str, other: str) -> bool:
    return _is_prefix(path, other) or _is_prefix(other, path)
