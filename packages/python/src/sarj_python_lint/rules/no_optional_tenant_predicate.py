"""SARJ056 — A tenant predicate that only appears inside a conditional branch.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_optional_tenant_predicate.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# Columns that scope a row to a tenant. `org_id` is included because some
# first-party legacy stores use it; `tenant_id`/`account_id`/`workspace_id` are the common
# names the same pattern takes in other multi-tenant codebases.
_TENANT_COLUMNS = ("organization_id", "org_id", "tenant_id", "account_id", "workspace_id")

# A fragment is a predicate (not a bare column name in a SELECT list) when the
# tenant column is followed by a comparison. `= %s`, `= ANY(...)`, `IN (...)`,
# `= {}` (psycopg SQL.format) and `<>` all count.
_TENANT_PREDICATE_RE = re.compile(
    r"\b(?:\w+\.)?(?:" + "|".join(_TENANT_COLUMNS) + r")\b\s*(?:=|<>|!=|\bIN\b|\bIS\b)",
    re.IGNORECASE,
)

_CONDITIONAL_NODES = (ast.If, ast.IfExp)


class NoOptionalTenantPredicate(Rule):
    id: str = "no-optional-tenant-predicate"
    code: str = "SARJ056"
    description: str = (
        "A tenant predicate reachable only inside a conditional makes tenant scoping fail open — "
        "the query still runs, unscoped, when the filter is absent."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        # A file with no tenant column anywhere cannot produce a finding, and
        # that is the overwhelming majority of files. Skipping the AST walk
        # here keeps the rule off the critical path of every unrelated file.
        if not any(column in source for column in _TENANT_COLUMNS):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for func in _iter_functions(tree):
            fragments = _tenant_fragments(func)
            if not fragments:
                continue
            if any(not conditional for _, conditional in fragments):
                # At least one unconditional tenant predicate — scoping always applies.
                continue
            node = fragments[0][0]
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"tenant predicate in `{func.name}` is only added inside a conditional, so the "
                        "query runs unscoped when the filter is empty or missing. Seed the condition "
                        "list with the tenant predicate unconditionally, or require the tenant id."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _iter_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect every function and method in the module."""
    return nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)


def _tenant_fragments(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.expr, bool]]:
    """Find WHERE-fragments in `func` that carry a tenant predicate."""
    found: list[tuple[ast.expr, bool]] = []

    def visit(node: ast.AST, *, conditional: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        # An `IfExp` fragment guards the predicate inside itself:
        # `c.append(SQL("organization_id = %s") if org else SQL("TRUE"))`.
        found.extend(
            (fragment, conditional or isinstance(fragment, ast.IfExp))
            for fragment in _composition_fragments(node)
            if _mentions_tenant_predicate(fragment)
        )
        nested = conditional or isinstance(node, _CONDITIONAL_NODES)
        for child in children(node):
            visit(child, conditional=nested)

    for child in children(func):
        visit(child, conditional=False)
    found.sort(key=lambda pair: (pair[0].lineno, pair[0].col_offset))
    return found


def _composition_fragments(node: ast.AST) -> list[ast.expr]:
    """Yield the expressions `node` itself accumulates into a WHERE-fragment list."""
    if isinstance(node, ast.List):
        return list(node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend"}:
        return list(node.args)
    return []


def _mentions_tenant_predicate(node: ast.expr) -> bool:
    """Report whether `node`'s subtree contains a tenant-column predicate string."""
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and _TENANT_PREDICATE_RE.search(child.value) is not None
        for child in walk(node)
    )
