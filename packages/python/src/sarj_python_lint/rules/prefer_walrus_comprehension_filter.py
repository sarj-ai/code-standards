"""SARJ076 — Prefer walrus operator in comprehension filters to avoid duplicate function evaluation

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_walrus_comprehension_filter.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, is_suppressed, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


def _nodes_equal(node1: ast.AST, node2: ast.AST) -> bool:
    return ast.dump(node1) == ast.dump(node2)


def _check_comprehension_node(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    source_lines: list[str],
    code: str,
    path: Path,
) -> list[Diagnostic]:
    """Check a single comprehension node for duplicate calls in filter and element."""
    if len(node.generators) != 1:
        return []

    gen = node.generators[0]
    if not gen.ifs:
        return []

    elt_nodes = (
        [node.elt] if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp) else [node.key, node.value]
    )
    diags: list[Diagnostic] = []

    for if_clause in gen.ifs:
        if any(isinstance(n, ast.NamedExpr) for n in walk(if_clause)):
            continue
        calls_in_if = [n for n in walk(if_clause) if isinstance(n, ast.Call | ast.Attribute)]
        for call_node in calls_in_if:
            if (
                isinstance(call_node, ast.Attribute)
                and isinstance(call_node.value, ast.Name)
                and call_node.value.id in {"ast", "typing", "sys", "os", "re", "types"}
            ):
                continue
            if (
                isinstance(call_node, ast.Call)
                and isinstance(call_node.func, ast.Name)
                and call_node.func.id in {"isinstance", "issubclass", "hasattr", "getattr"}
            ):
                continue
            for elt in elt_nodes:
                if any(isinstance(n, ast.Lambda) for n in walk(elt)):
                    continue
                calls_in_elt = [n for n in walk(elt) if isinstance(n, ast.Call | ast.Attribute)]
                if any(_nodes_equal(call_node, elt_call) for elt_call in calls_in_elt):
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
                                    "Repeated expression in comprehension filter and element — "
                                    "use assignment expression `(val := ...)` to evaluate once."
                                ),
                            )
                        )
                    break

    return diags


class PreferWalrusComprehensionFilter(Rule):
    id: str = "prefer-walrus-comprehension-filter"
    code: str = "SARJ076"
    description: str = "repeated expression in comprehension filter and element — use `(val := ...)` to evaluate once."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        for node in nodes(tree, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp):
            diags.extend(_check_comprehension_node(node, source_lines, self.code, path))

        seen: set[tuple[int, int]] = set()
        unique_diags: list[Diagnostic] = []
        for d in diags:
            if (d.line, d.col) not in seen:
                seen.add((d.line, d.col))
                unique_diags.append(d)

        return sorted(unique_diags, key=lambda d: (d.line, d.col))
