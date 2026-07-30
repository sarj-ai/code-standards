"""SARJ080: prefer match/case over sequential sentinel/type guards.

Parsers and field deserializers often contain hideous type-dispatch idioms:
sequential `if x is None: return x` / `if isinstance(x, Unset): return x` guards
walking a value through one shape at a time, where a single `match` states the
whole dispatch at once.

DELIBERATELY NOT FLAGGED: `raise` inside a `try` block
------------------------------------------------------

This rule used to carry a second detector for the other half of that idiom —
raising inside a `try` purely to jump into its own `except` handler, i.e. using
`raise` as a goto. That detector was removed because ruff already reports it and
our shipped config already enables it.

`ruff.strict.toml` selects `ALL` and does not ignore `TRY`, so `TRY301`
(`raise-within-try`, "Abstract `raise` to an inner function") is live in every
consumer. Measured across 21 corpora, the removed arm produced 1,756 findings of
which 1,649 (93.9%) sat on a line ruff already flagged, and construction
confirms the columns match exactly, not merely the line:

    try:
        if not isinstance(x, str):
            raise TypeError        # ruff TRY301 at 13:13, old SARJ080 at 13:13

The 107 positions TRY301 structurally misses are `raise`s inside an `except`
body caught by an *outer* `try`. That is a real gap, but not one worth 1,649
double reports — and 5 of those positions already carry an explicit
`# noqa: TRY301`, a decision the team made that a second code would quietly
re-open.

The surviving sequential-guard detector has NO ruff counterpart: the same sweep
found 0 of its 476 positions shared with TRY301, and `RET505` is the closest
thing ruff has, firing only on `elif`-after-`return` rather than on separate
`if ...: return` statements.

Preferred Python 3.10+ match/case patterns:
- For `None`: `case None:`
- For singleton classes: `case Unset():`
- For singleton instances: `case _ if data is UNSET:`
- For builtins (`int`, `str`, `list`, `dict`): `case int():`, `case str():`, etc.
- For combined conditions: `case None | Unset():`

Example refactoring:
    match data:
        case None | Unset():
            return data
        case str():
            try:
                return datetime.datetime.fromisoformat(data)
            except ValueError:
                pass
        case dict():
            return parse_dict(data)
    return cast(..., data)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SENTINEL_COUNT = 2


def _guard_target_var_name(stmt: ast.stmt) -> str | None:
    """Extract target variable name if statement is `if x is None: return ...` or `if isinstance(x, ...): return ...`.

    Returns:
        Target variable name, or None if not a sentinel guard.

    """
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1 or not isinstance(stmt.body[0], ast.Return):
        return None
    test = stmt.test
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq))
        and isinstance(test.left, ast.Name)
    ):
        return test.left.id
    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id in {"isinstance", "issubclass"}
        and test.args
        and isinstance(test.args[0], ast.Name)
    ):
        return test.args[0].id
    return None


def _check_sequential_type_guards(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path, code: str
) -> list[Diagnostic]:
    """Check for 2+ sequential sentinel return guards targeting the SAME variable in a function body.

    Returns:
        List of Diagnostics if sequential type guards are found.

    """
    body = func_node.body
    if not body:
        return []

    start_idx = 0
    if (
        len(body) > 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        start_idx = 1

    stmts = body[start_idx:]
    if len(stmts) < _MIN_SENTINEL_COUNT:
        return []

    target_var: str | None = None
    sentinel_count = 0
    for stmt in stmts:
        var = _guard_target_var_name(stmt)
        if var is not None:
            if target_var is None:
                target_var = var
                sentinel_count += 1
            elif var == target_var:
                sentinel_count += 1
            else:
                break
        else:
            break

    if sentinel_count >= _MIN_SENTINEL_COUNT:
        first_if = stmts[0]
        line = getattr(first_if, "lineno", func_node.lineno)
        return [
            Diagnostic(
                path=path,
                line=line,
                col=first_if.col_offset + 1,
                code=code,
                message=(
                    f"Sequential sentinel/type guards ({sentinel_count} checks on '{target_var}') "
                    f"in function '{func_node.name}' — refactor into Python 3.10+ match/case pattern matching "
                    f"(e.g., 'case None | Unset():')."
                ),
            )
        ]
    return []


@final
class _TypeDispatchVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, code: str) -> None:
        self.path: Path = path
        self.code: str = code
        self.diags: list[Diagnostic] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.generic_visit(node)


class PreferMatchTypeDispatch(Rule):
    """Prefer match/case over sequential sentinel/type guards."""

    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ080"
    description: str = "Sequential sentinel/type guards — prefer Python 3.10+ match/case pattern matching."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _TypeDispatchVisitor(path, self.code)
        visitor.visit(tree)
        visitor.diags.sort(key=lambda d: (d.line, d.col))
        return visitor.diags
