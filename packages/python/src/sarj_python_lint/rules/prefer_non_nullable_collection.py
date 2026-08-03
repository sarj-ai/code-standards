"""SARJ082 — Prefer non-null list fields in declared data shapes

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_non_nullable_collection.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_UNION_NAMES = frozenset({"Optional", "Union"})


class PreferNonNullableCollection(Rule):
    id: str = "prefer-non-nullable-collection"
    code: str = "SARJ082"
    description: str = (
        "List fields should use a non-null list and an empty default instead of two equivalent empty states."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for cls in (node for node in walk(tree) if isinstance(node, ast.ClassDef)):
            for statement in cls.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if not isinstance(statement.target, ast.Name):
                    continue
                if not _is_nullable_list(statement.annotation):
                    continue
                name = statement.target.id
                diags.append(
                    Diagnostic(
                        path=path,
                        line=statement.lineno,
                        col=statement.col_offset + 1,
                        code=self.code,
                        message=(
                            f"`{name}` is a nullable list field, so `None` and `[]` "
                            "represent the same empty collection; use a non-null list "
                            "with `Field(default_factory=list)` / "
                            "`field(default_factory=list)` (or make it required)."
                        ),
                    )
                )
        return diags


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _qualified_name(node.value)
    return ""


def _is_nullable_list(annotation: ast.expr) -> bool:
    members = _union_members(annotation)
    if members is None:
        return False
    non_none = [member for member in members if not _is_none_type(member)]
    return len(non_none) > 0 and len(non_none) < len(members) and all(_is_list_type(member) for member in non_none)


def _union_members(annotation: ast.expr) -> list[ast.expr] | None:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left = _union_members(annotation.left) or [annotation.left]
        right = _union_members(annotation.right) or [annotation.right]
        return [*left, *right]
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value).split(".")[-1] in _UNION_NAMES:
        if _qualified_name(annotation.value).endswith("Optional"):
            return [annotation.slice, ast.Constant(value=None)]
        if isinstance(annotation.slice, ast.Tuple):
            return list(annotation.slice.elts)
        return [annotation.slice]
    return None


def _is_none_type(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _is_list_type(node: ast.expr) -> bool:
    return isinstance(node, ast.Subscript) and _qualified_name(node.value).split(".")[-1] in {
        "List",
        "list",
    }
