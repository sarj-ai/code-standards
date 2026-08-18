from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# Columns that scope a row to a tenant.
_TENANT_COLUMNS = ("organization_id", "org_id", "tenant_id", "account_id", "workspace_id")

# Require a comparison after the tenant column so SELECT-list names do not masquerade as predicates.
_TENANT_PREDICATE_RE = re.compile(
    r"\b(?:\w+\.)?(?:"
    + "|".join(_TENANT_COLUMNS)
    + r")\b\s*(?:(?:=|<>|!=)\s*(?:%s|%\([^)]+\)s|:\w+|\?|\$\d+|\{\}|ANY\s*\()|IN\s*\(|IS\s+(?:NOT\s+)?NULL\b)",
    re.IGNORECASE,
)


class NoOptionalTenantPredicate(Rule):
    id: str = "no-optional-tenant-predicate"
    code: str = "SARJ056"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tenant predicate is added only conditionally, allowing an unscoped query.",
        rationale="Fail-open tenant filtering can expose rows across organizations when a tenant value is absent.",
        remediation=(
            "Require the tenant identifier or seed the query with its tenant predicate unconditionally. "
            "For an audited cross-tenant admin/background query, suppress only the conditional fragment "
            "with `# sarj-noqa: SARJ056` and state why unscoped access is required."
        ),
        category=RuleCategory.SECURITY,
        limitations=(
            "Detection follows SQL fragments inside each function and recognizes configured tenant column names.",
            "Test files and functions containing any unconditional tenant predicate are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="conditional-tenant-clause",
                title="Tenant clause depends on an optional filter",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "def build(args):\n"
                        "    conditions = []\n"
                        "    if args.organization_id:\n"
                        '        conditions.append(SQL("organization_id = %s"))\n'
                        "    return conditions\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="required-tenant-clause",
                title="Tenant clause is unconditional",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        'def build(args):\n    conditions = [SQL("organization_id = %s")]\n    return conditions\n',
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        # Avoid parsing files that cannot contain a tenant predicate.
        lowered = source.lower()
        if not any(column in lowered for column in _TENANT_COLUMNS):
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
                        "list with the tenant predicate unconditionally, require the tenant id, or mark an "
                        "audited cross-tenant fragment with `# sarj-noqa: SARJ056` and a reason."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _iter_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)


def _tenant_fragments(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.expr, bool]]:
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
        if isinstance(node, ast.If):
            # When the complementary arm cannot reach the continuation, a
            # tenant clause in this arm applies on every path that can execute
            # the eventual query.
            for child in node.body:
                visit(child, conditional=conditional or not _block_terminates(node.orelse))
            for child in node.orelse:
                visit(child, conditional=conditional or not _block_terminates(node.body))
            return
        nested = conditional or isinstance(node, ast.IfExp)
        for child in children(node):
            visit(child, conditional=nested)

    for child in children(func):
        visit(child, conditional=False)
    found.sort(key=lambda pair: (pair[0].lineno, pair[0].col_offset))
    return found


def _block_terminates(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    match body[-1]:
        case ast.Raise() | ast.Return():
            return True
        case ast.Assert(test=ast.Constant(value=value)):
            return not value
        case ast.If(body=taken, orelse=other):
            return bool(other) and _block_terminates(taken) and _block_terminates(other)
        case ast.With() | ast.AsyncWith():
            return _block_terminates(body[-1].body)
        case _:
            return False


def _composition_fragments(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.List):
        return list(node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend"}:
        return list(node.args)
    return []


def _mentions_tenant_predicate(node: ast.expr) -> bool:
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and _TENANT_PREDICATE_RE.search(child.value) is not None
        for child in walk(node)
    )
