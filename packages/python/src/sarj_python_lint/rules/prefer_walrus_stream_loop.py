"""SARJ077 — Prefer walrus operator in `while` loop conditions for stream/chunk reading.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_walrus_stream_loop.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path

_MIN_BODY_LEN = 2


def _is_constant_true(node: ast.AST) -> bool:
    """Check if node represents the constant True."""
    return (isinstance(node, ast.Constant) and node.value is True) or (isinstance(node, ast.Name) and node.id == "True")


def _is_falsy_break_check(test_node: ast.AST, var_name: str) -> bool:
    """Check if test_node is `not var_name` or `var_name is None`."""
    if (
        isinstance(test_node, ast.UnaryOp)
        and isinstance(test_node.op, ast.Not)
        and isinstance(test_node.operand, ast.Name)
        and test_node.operand.id == var_name
    ):
        return True
    if (
        isinstance(test_node, ast.Compare)
        and isinstance(test_node.left, ast.Name)
        and test_node.left.id == var_name
        and len(test_node.ops) == 1
        and isinstance(test_node.ops[0], ast.Is)
    ):
        right = test_node.comparators[0]
        if isinstance(right, ast.Constant) and right.value is None:
            return True
    return False


class PreferWalrusStreamLoop(Rule):
    id: str = "prefer-walrus-stream-loop"
    code: str = "SARJ077"
    description: str = (
        "stream read loop using `while True:` with assignment and break — combine "
        "into `while (chunk := stream.read(...)):`."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        for node in nodes(tree, ast.While):
            if not _is_constant_true(node.test) or node.orelse or len(node.body) < _MIN_BODY_LEN:
                continue

            first_stmt = node.body[0]
            second_stmt = node.body[1]

            if (
                not isinstance(first_stmt, ast.Assign)
                or len(first_stmt.targets) != 1
                or not isinstance(first_stmt.targets[0], ast.Name)
            ):
                continue
            var_name = first_stmt.targets[0].id

            if (
                isinstance(second_stmt, ast.If)
                and len(second_stmt.body) == 1
                and isinstance(second_stmt.body[0], ast.Break)
                and _is_falsy_break_check(second_stmt.test, var_name)
            ):
                line = first_stmt.lineno
                col = first_stmt.col_offset + 1
                if not is_suppressed(source_lines, line, self.code):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=line,
                            col=col,
                            code=self.code,
                            message=(
                                f"Use `while ({var_name} := ...)` loop condition instead of `while True:` "
                                f"with an explicit `break`."
                            ),
                        )
                    )

        return sorted(diags, key=lambda d: (d.line, d.col))
