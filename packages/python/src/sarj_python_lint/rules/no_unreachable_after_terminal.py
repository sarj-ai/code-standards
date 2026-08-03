"""SARJ010 — Unreachable code after a terminal statement

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_unreachable_after_terminal.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children


if TYPE_CHECKING:
    from pathlib import Path


# Fields on AST nodes that hold a list of statements (a block body).
_BLOCK_FIELDS = ("body", "orelse", "finalbody")

_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)

# The node kinds whose own `body` runs in a different context than they do.
_CONTEXT_NODES = (*_FUNCTIONS, *_LOOPS, ast.ClassDef)

# The node kinds whose subtree can contain a statement, and so the only ones
_STATEMENT_BEARING = (ast.stmt, ast.ExceptHandler, ast.match_case, ast.mod)


def _block(node: ast.AST, field: str) -> list[ast.stmt]:
    """Read a node's `body` / `orelse` / `finalbody` statement list."""
    raw = getattr(node, field, None)
    if not isinstance(raw, list):
        return []
    # `getattr` over a dynamic field name yields `Any`; the block fields only
    # ever hold statements, so narrowing to `ast.stmt` recovers a well-typed
    # `list[ast.stmt]`.
    return [
        stmt
        for stmt in raw  # pyright: ignore[reportUnknownVariableType] -- stmt iterates a list[Any] from getattr; narrowed to ast.stmt by the filter
        if isinstance(stmt, ast.stmt)
    ]


def _is_terminal(stmt: ast.stmt, *, in_function: bool, in_loop: bool) -> bool:
    """Report whether `stmt` ends control flow for its block IN THIS CONTEXT."""
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Return):
        return in_function
    return isinstance(stmt, (ast.Break, ast.Continue)) and in_loop


def _child_context(node: ast.AST, field: str, *, in_function: bool, in_loop: bool) -> tuple[bool, bool]:
    """Compute the `(in_function, in_loop)` context for a node's child field."""
    if isinstance(node, _FUNCTIONS):
        return (True, False) if field == "body" else (in_function, in_loop)
    if isinstance(node, ast.ClassDef):
        return (False, False) if field == "body" else (in_function, in_loop)
    if isinstance(node, _LOOPS) and field == "body":
        return in_function, True
    return in_function, in_loop


def _is_generator_marker(stmt: ast.stmt) -> bool:
    # `yield` / `yield from` after a terminal is the idiom that forces a
    match stmt:
        case ast.Expr(value=value) | ast.Assign(value=value) | ast.AugAssign(value=value) | ast.AnnAssign(value=value):
            return isinstance(value, (ast.Yield, ast.YieldFrom))
        case _:
            return False


class NoUnreachableAfterTerminal(Rule):
    id: str = "no-unreachable-after-terminal"
    code: str = "SARJ010"
    description: str = "Unreachable code after a terminal statement (`return`/`raise`/`break`/`continue`)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._visit(tree, path, in_function=False, in_loop=False, diags=diags)
        diags.sort(key=lambda d: (d.line, d.col))
        return diags

    def _visit(self, node: ast.AST, path: Path, *, in_function: bool, in_loop: bool, diags: list[Diagnostic]) -> None:
        for field in _BLOCK_FIELDS:
            child_function, child_loop = _child_context(node, field, in_function=in_function, in_loop=in_loop)
            self._flag_block(_block(node, field), path, in_function=child_function, in_loop=child_loop, diags=diags)
        # Only a function / class / loop changes the context, and then only for
        # the statements in its own `body`; every other child inherits.
        body_ids: set[int] = {id(stmt) for stmt in _block(node, "body")} if isinstance(node, _CONTEXT_NODES) else set()
        for child in children(node):
            # Recurse only where a statement block can still be found.
            if not isinstance(child, _STATEMENT_BEARING):
                continue
            field = "body" if id(child) in body_ids else ""
            child_function, child_loop = _child_context(node, field, in_function=in_function, in_loop=in_loop)
            self._visit(child, path, in_function=child_function, in_loop=child_loop, diags=diags)

    def _flag_block(
        self, stmts: list[ast.stmt], path: Path, *, in_function: bool, in_loop: bool, diags: list[Diagnostic]
    ) -> None:
        # Find the first terminal that is not the last element.
        for i in range(len(stmts) - 1):
            if not _is_terminal(stmts[i], in_function=in_function, in_loop=in_loop):
                continue
            for unreachable in stmts[i + 1 :]:
                if _is_generator_marker(unreachable):
                    continue
                diags.append(
                    Diagnostic(
                        path=path,
                        line=unreachable.lineno,
                        col=unreachable.col_offset + 1,
                        code=self.code,
                        message=(
                            "Unreachable code — this statement follows a "
                            "`return`/`raise`/`break`/`continue` and can "
                            "never execute."
                        ),
                    )
                )
                break
            break  # one diag per statement list (the first terminal)
