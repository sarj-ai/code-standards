"""SARJ076 — Prefer walrus operator in comprehension filters to avoid duplicate function evaluation.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_walrus_comprehension_filter.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


def _check_comprehension_node(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    source_lines: list[str],
    code: str,
    path: Path,
    parents: dict[ast.AST, ast.AST],
) -> list[Diagnostic]:
    """Check a callable-scoped comprehension for duplicate calls."""
    if len(node.generators) != 1 or not _has_callable_scope(node, parents):
        return []

    gen = node.generators[0]
    if not gen.ifs:
        return []

    elt_nodes = (
        [node.elt] if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp) else [node.key, node.value]
    )
    calls_in_elts = [
        candidate
        for elt in elt_nodes
        if not any(isinstance(n, ast.Lambda) for n in walk(elt))
        for candidate in walk(elt)
        if isinstance(candidate, ast.Call)
    ]
    diags: list[Diagnostic] = []

    for if_clause in gen.ifs:
        if any(isinstance(n, ast.NamedExpr) for n in walk(if_clause)):
            continue
        calls_in_if = [n for n in walk(if_clause) if isinstance(n, ast.Call)]
        repeated = any(
            not (isinstance(call.func, ast.Name) and call.func.id in {"isinstance", "issubclass", "hasattr", "getattr"})
            and any(ast.compare(call, candidate) for candidate in calls_in_elts)
            for call in calls_in_if
        )
        if not repeated:
            continue
        line = getattr(if_clause, "lineno", 1)
        col = getattr(if_clause, "col_offset", 0) + 1
        if not is_suppressed(source_lines, line, code):
            diags.append(
                Diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    code=code,
                    message=(
                        "Repeated function call in comprehension filter and element — "
                        "bind it once in the filter with a fresh, meaningful name."
                    ),
                )
            )

    return diags


def _has_callable_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Require the expression to execute inside a function or lambda body."""
    child = node
    while (parent := parents.get(child)) is not None:
        if isinstance(parent, ast.TypeAlias | ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple):
            return False
        if isinstance(parent, ast.arg | ast.AnnAssign) and child is parent.annotation:
            return False
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            if child is parent.returns:
                return False
            if child in parent.body:
                return True
        elif isinstance(parent, ast.Lambda):
            if child is parent.body:
                return True
        elif isinstance(parent, ast.ClassDef):
            if child in parent.body:
                return False
        elif isinstance(parent, ast.Module):
            return False
        child = parent
    return False


class PreferWalrusComprehensionFilter(Rule):
    id: str = "prefer-walrus-comprehension-filter"
    code: str = "SARJ076"
    description: str = (
        "repeated function call in comprehension filter and element — bind it once with a named expression."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        comprehensions = nodes(tree, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        if not comprehensions:
            return []
        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        parents = {child: parent for parent in nodes(tree, ast.AST) for child in children(parent)}

        for node in comprehensions:
            diags.extend(_check_comprehension_node(node, source_lines, self.code, path, parents))

        return sorted(diags, key=lambda d: (d.line, d.col))
