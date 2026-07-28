"""SARJ074: prefer match/case over control-flow try/raise and sequential type guards.

Parsers and field deserializers often contain hideous type-dispatch idioms:
sequential `if x is None: return x` / `if isinstance(x, Unset): return x` guards,
followed by a `try` block containing `if not isinstance(x, T): raise TypeError()`
to artificially jump control flow into an `except (TypeError, ...): pass` block.

Raising an exception inside a `try` block solely to trigger that block's `except`
handler is using `raise` as a goto (control flow via exceptions).

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
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


_GENERIC_EXCEPTIONS = frozenset({"Exception", "BaseException"})
_MIN_SENTINEL_COUNT = 2


def _get_caught_exception_names(handlers: list[ast.ExceptHandler]) -> set[str] | None:
    """Extract caught exception class names.

    Returns:
        A set of exception class names, or None if a catch-all handler (bare `except:`) is present.

    """
    caught: set[str] = set()
    for h in handlers:
        if h.type is None:
            return None
        if isinstance(h.type, ast.Name):
            caught.add(h.type.id)
        elif isinstance(h.type, ast.Tuple):
            for elt in h.type.elts:
                if isinstance(elt, ast.Name):
                    caught.add(elt.id)
                elif isinstance(elt, ast.Attribute):
                    caught.add(elt.attr)
                    caught.add(ast.unparse(elt))
        elif isinstance(h.type, ast.Attribute):
            caught.add(h.type.attr)
            caught.add(ast.unparse(h.type))
    return caught


def _raised_exception_name(raise_node: ast.Raise) -> str | None:
    """Extract exception class name from `raise Exc()` or `raise Exc`.

    Returns:
        The exception class name, or None if no exception is specified.

    """
    exc = raise_node.exc
    if exc is None:
        return None
    if isinstance(exc, ast.Call):
        func = exc.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    elif isinstance(exc, ast.Name):
        return exc.id
    elif isinstance(exc, ast.Attribute):
        return exc.attr
    return None


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


class _TypeDispatchVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, code: str) -> None:
        self.path = path
        self.code = code
        self.diags: list[Diagnostic] = []
        self.try_stack: list[set[str] | None] = []

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        caught = _get_caught_exception_names(node.handlers)
        self.try_stack.append(caught)
        for stmt in node.body:
            self.visit(stmt)
        self.try_stack.pop()
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    @override
    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if self.try_stack:
            exc_name = _raised_exception_name(node)
            if exc_name is not None:
                # Search outward through active try scopes
                for caught in reversed(self.try_stack):
                    is_caught = caught is None or exc_name in caught or bool(caught & _GENERIC_EXCEPTIONS)
                    if is_caught:
                        self.diags.append(
                            Diagnostic(
                                path=self.path,
                                line=node.lineno,
                                col=node.col_offset + 1,
                                code=self.code,
                                message=(
                                    f"Control-flow raise in try block — 'raise {exc_name}()' "
                                    f"jumps directly to local except handler. Refactor to 'match/case' "
                                    f"(e.g., 'case str():') to handle types directly."
                                ),
                            )
                        )
                        break
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        saved_stack = self.try_stack
        self.try_stack = []
        self.generic_visit(node)
        self.try_stack = saved_stack

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        saved_stack = self.try_stack
        self.try_stack = []
        self.generic_visit(node)
        self.try_stack = saved_stack

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.generic_visit(node)


class PreferMatchTypeDispatch(Rule):
    """Prefer match/case over try/raise control flow and sequential type guards."""

    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ074"
    description: str = (
        "Control-flow raise in try block or sequential type guards — prefer Python 3.10+ match/case pattern matching."
    )

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
