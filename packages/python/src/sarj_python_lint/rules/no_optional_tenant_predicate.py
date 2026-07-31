"""SARJ056: a tenant predicate that only appears inside a conditional branch.

Multi-tenant stores compose a WHERE clause by accumulating fragments in a list::

    where_conditions: list[Composable] = []
    if args.organization_ids:
        where_conditions.append(SQL("organization_id = ANY(%s::uuid[])"))
    if args.status:
        where_conditions.append(SQL("status = ANY(%s)"))
    where_clause = SQL(" AND ").join(where_conditions) if where_conditions else SQL("1=1")

When the tenant fragment is the *only* thing standing between a caller and every
other tenant's rows, guarding it with `if` makes the scoping **fail open**: the
query still executes, just without the predicate. A caller that passes an empty
or missing organization list silently reads the whole table.

This is not hypothetical. In one first-party service,
`PsqlOrderStore._build_filter_conditions` had exactly this shape, and
`POST /v1/orders/list` reached it with `organization_ids=[]` for any user whose
`organization_id` was NULL — composing `SELECT ... FROM orders WHERE 1=1`, i.e.
every tenant's rows.

The rule fires when, within a single function, *every* WHERE-fragment that
mentions a tenant column is nested inside a conditional. The safe idiom seeds
the fragment list with the tenant predicate unconditionally::

    conditions: list[Composable] = [SQL("organization_id = %s")]   # always applied

so that form never fires. A function with no tenant fragment at all does not
fire either — an intentionally cross-tenant admin query is not this rule's
business; only *attempted-but-optional* scoping is.

Scope note: only fragments participating in list composition (a list literal, or
an argument to `.append()` / `.extend()`) are considered, so an unrelated inline
`WHERE organization_id = %s` elsewhere in the same function neither triggers nor
masks a finding.
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
    """Tenant scoping that disappears when a filter is absent."""

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
    """Collect every function and method in the module.

    Returns:
        All `FunctionDef`/`AsyncFunctionDef` nodes, outermost first.

    """
    return nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)


def _tenant_fragments(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.expr, bool]]:
    """Find WHERE-fragments in `func` that carry a tenant predicate.

    Only fragments taking part in list composition count: elements of a list
    literal, or arguments to `.append()` / `.extend()`. Each is paired with
    whether it sits inside a conditional *within this function*.

    One recursive pass carries the "am I under an `If`/`IfExp`?" flag down the
    tree, so the cost is linear in the function's node count.

    Returns:
        `(node, is_conditional)` pairs in source order.

    """
    found: list[tuple[ast.expr, bool]] = []

    def visit(node: ast.AST, *, conditional: bool) -> None:
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
    """Yield the expressions `node` itself accumulates into a WHERE-fragment list.

    Shallow by design — the caller recurses — so each node is inspected once.

    Returns:
        List-literal elements, or `.append()`/`.extend()` arguments.

    """
    if isinstance(node, ast.List):
        return list(node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend"}:
        return list(node.args)
    return []


def _mentions_tenant_predicate(node: ast.expr) -> bool:
    """Report whether `node`'s subtree contains a tenant-column predicate string.

    Walking the subtree catches `SQL("organization_id = %s")` and the
    `SQL("...").format(...)` form alike.

    Returns:
        True when a tenant predicate literal appears in the subtree.

    """
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and _TENANT_PREDICATE_RE.search(child.value) is not None
        for child in walk(node)
    )
