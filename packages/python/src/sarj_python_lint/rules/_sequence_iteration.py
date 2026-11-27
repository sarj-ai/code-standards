from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._binding_inventory import binding_names


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence


_NESTED_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def stable_iteration_nodes(body: Sequence[ast.AST], sequence: ast.expr, index: str) -> tuple[ast.AST, ...] | None:
    root = sequence_root(sequence)
    if root is None:
        return None
    nodes = tuple(node for statement in body for node in ast.walk(statement))
    if any(_captures_index(node, index) for node in nodes):
        return None
    if any(name in {root, index} for node in nodes for name in binding_names(node)):
        return None
    if any(
        isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del) and sequence_root(node) == root
        for node in nodes
    ):
        return None
    return nodes


def sequence_root(sequence: ast.expr) -> str | None:
    while isinstance(sequence, ast.Attribute):
        sequence = sequence.value
    return sequence.id if isinstance(sequence, ast.Name) else None


def only_index_reads(nodes: Sequence[ast.AST], index: str, allowed: Collection[ast.Name]) -> bool:
    return all(
        node in allowed
        for node in nodes
        if isinstance(node, ast.Name) and node.id == index and isinstance(node.ctx, ast.Load)
    )


def _captures_index(node: ast.AST, index: str) -> bool:
    if not isinstance(node, _NESTED_SCOPES):
        return False
    return any(isinstance(child, ast.Name) and child.id == index for child in ast.walk(node))
