"""SARJ024 — A structured string literal repeated across functions — extract a named constant.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_repeated_string_literal.py
"""

from __future__ import annotations

import ast
from collections import defaultdict
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LENGTH = 40
_MIN_DISTINCT_SCOPES = 2
_PREVIEW_LENGTH = 40

_SCAFFOLDING_KWARGS = frozenset({"examples", "description", "title", "summary"})

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|VALUES|ON CONFLICT|RETURNING|GROUP BY|ORDER BY)\b"
)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")

_MODULE_SCOPE = -1


class NoRepeatedStringLiteral(Rule):
    id: str = "no-repeated-string-literal"
    code: str = "SARJ024"
    description: str = "Structured string literal repeated across functions — extract a module-level constant."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if _is_skipped_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        occurrences: dict[str, list[ast.Constant]] = defaultdict(list)
        scope_of: dict[int, int] = {}
        excluded: set[int] = set()

        def visit(node: ast.AST, scope: int) -> None:
            for annotation in _annotation_exprs(node):
                excluded.update(id(child) for child in walk(annotation) if isinstance(child, ast.Constant))
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    excluded.add(id(body[0].value))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = id(node)
            elif isinstance(node, ast.JoinedStr):
                excluded.update(id(value) for value in node.values)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _SCAFFOLDING_KWARGS:
                        excluded.update(id(child) for child in walk(kw.value) if isinstance(child, ast.Constant))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) >= _MIN_LENGTH
                and id(node) not in excluded
                and _is_structured(node.value)
            ):
                occurrences[node.value].append(node)
                scope_of[id(node)] = scope
            for child in children(node):
                visit(child, scope)

        visit(tree, _MODULE_SCOPE)

        diags: list[Diagnostic] = []
        for value, nodes in occurrences.items():
            function_scopes = {scope for n in nodes if (scope := scope_of.get(id(n), _MODULE_SCOPE)) != _MODULE_SCOPE}
            if len(function_scopes) < _MIN_DISTINCT_SCOPES:
                continue
            nodes.sort(key=lambda n: (n.lineno, n.col_offset))
            first, *repeats = nodes
            diags.extend(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"structured string literal {_preview(value)} is repeated across "
                        f"functions (first use at line {first.lineno}) — extract a "
                        f"module-level constant so the copies cannot drift."
                    ),
                )
                for node in repeats
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _annotation_exprs(node: ast.AST) -> list[ast.expr]:
    """Find the sub-expressions of `node` that are type annotations, not runtime values."""
    if isinstance(node, ast.arg):
        return [node.annotation] if node.annotation is not None else []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.returns] if node.returns is not None else []
    if isinstance(node, ast.AnnAssign):
        return [node.annotation]
    if isinstance(node, ast.Subscript) and _is_annotated(node.value):
        return [node.slice]
    return []


def _is_annotated(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "Annotated"
    return isinstance(expr, ast.Attribute) and expr.attr == "Annotated"


def _is_structured(value: str) -> bool:
    return "\n" in value or _SQL_KEYWORD_RE.search(value) is not None or _IDENTIFIER_RE.match(value) is not None


def _preview(value: str) -> str:
    if len(value) <= _PREVIEW_LENGTH:
        return repr(value)
    return repr(value[:_PREVIEW_LENGTH] + "…")


def _is_skipped_path(path: Path) -> bool:
    if path.name == "conftest.py":
        return True
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts
