"""SARJ080 — Prefer match/case over control-flow try/raise and sequential type guards.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_match_type_dispatch.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ080.md
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_GENERIC_EXCEPTIONS = frozenset({"Exception", "BaseException"})
_MIN_SENTINEL_COUNT = 2

# A try body longer than this is a fault barrier, not a dispatch. Measured:
# the fault-barrier population had a median span of 39 lines and a p90 of 220,
# while the idiom this rule targets fits in three.
_MAX_TRY_BODY_LINES = 20


def _handler_exception_names(handler: ast.ExceptHandler) -> set[str] | None:
    """Extract the exception class names one handler catches.

    Returns:
        A set of exception class names, or None for a bare `except:`.

    """
    if handler.type is None:
        return None
    caught: set[str] = set()
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for node in types:
        if isinstance(node, ast.Name):
            caught.add(node.id)
        elif isinstance(node, ast.Attribute):
            caught.add(node.attr)
            caught.add(ast.unparse(node))
    return caught


def _first_matching_handler(try_node: ast.Try | ast.TryStar, exc_name: str) -> ast.ExceptHandler | None:
    """Find the handler that would actually receive `exc_name`.

    Handlers are tried in source order, so an earlier `except Exception` shadows
    a later exact one — the same order the interpreter uses.

    Returns:
        The receiving handler, or None if the exception escapes this try.

    """
    for handler in try_node.handlers:
        names = _handler_exception_names(handler)
        if names is None or exc_name in names or bool(names & _GENERIC_EXCEPTIONS):
            return handler
    return None


def _raised_exception_name(raise_node: ast.Raise) -> str | None:
    """Extract exception class name from `raise Exc()` or `raise Exc`."""
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


def _is_docstring(stmt: ast.stmt) -> bool:
    """Report whether `stmt` is a bare string expression.

    Returns:
        True when the statement is a docstring or a string used as a comment.

    """
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _always_raises(body: list[ast.stmt]) -> bool:
    """Report whether every terminal path through `body` ends in a `raise`.

    A handler like this does not consume the exception — it propagates it to the
    caller — so the `raise` that reached it was never a jump to a local label.
    Deliberately conservative: an `if` without an `else`, or any terminal
    statement this cannot prove, counts as "does not always raise", which keeps
    the finding.

    Returns:
        True when control cannot leave `body` normally.

    """
    stmts = [stmt for stmt in body if not _is_docstring(stmt)]
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.If):
        return bool(last.orelse) and _always_raises(last.body) and _always_raises(last.orelse)
    if isinstance(last, (ast.With, ast.AsyncWith)):
        return _always_raises(last.body)
    if isinstance(last, (ast.Try, ast.TryStar)):
        protected = last.orelse or last.body
        return _always_raises(protected) and all(_always_raises(h.body) for h in last.handlers)
    return False


def _try_body_span(try_node: ast.Try | ast.TryStar) -> int:
    """Measure the try body in source lines.

    Returns:
        Lines between the `try:` keyword and the end of its last statement.

    """
    end = max((stmt.end_lineno or stmt.lineno) for stmt in try_node.body)
    return end - try_node.lineno


def _is_bare_raise_body(try_node: ast.Try | ast.TryStar) -> bool:
    """Report whether the try body is nothing but a single `raise`.

    Returns:
        True for the `try: raise X()` / `except X: <capture>` scaffolding shape.

    """
    return len(try_node.body) == 1 and isinstance(try_node.body[0], ast.Raise)


def _is_type_check_call(test: ast.expr, var: str) -> bool:
    """Report whether `test` is `isinstance(var, ...)` or `issubclass(var, ...)`.

    Returns:
        True when the test translates directly into a `case T():` class pattern.

    """
    if not isinstance(test, ast.Call) or not isinstance(test.func, ast.Name):
        return False
    if test.func.id not in {"isinstance", "issubclass"} or not test.args:
        return False
    first = test.args[0]
    return isinstance(first, ast.Name) and first.id == var


def _is_none_identity_test(test: ast.expr, var: str) -> bool:
    """Report whether `test` is `var is None` or `var is not None`.

    `None` is the one comparator that translates into a `case None:` literal
    pattern. Any other bare `Name` comparator would become a *capture* pattern,
    which matches every value — see the module docstring.

    Returns:
        True when the test translates directly into a `case None:` pattern.

    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], (ast.Is, ast.IsNot)):
        return False
    if not isinstance(test.left, ast.Name) or test.left.id != var:
        return False
    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value is None


def _passthrough_guard_var(stmt: ast.stmt) -> str | None:
    """Extract the variable of a sentinel *passthrough* guard.

    The shape is `if <test on x>: return x` — the guard returns the very value
    it tested, unchanged — and the test must translate directly into a match
    pattern: `isinstance(x, T)`, `issubclass(x, T)`, `x is None`, `x is not
    None`. A bare-`Name` comparator is refused: `case NAME:` is a capture
    pattern that matches everything, so suggesting match/case there would change
    behaviour.

    Returns:
        The guarded variable name, or None if `stmt` is not such a guard.

    """
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1:
        return None
    returned = stmt.body[0]
    if not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Name):
        return None
    var = returned.value.id

    if _is_type_check_call(stmt.test, var) or _is_none_identity_test(stmt.test, var):
        return var
    return None


def _check_sequential_type_guards(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path, code: str
) -> list[Diagnostic]:
    """Check for 2+ sequential sentinel passthrough guards on the SAME variable.

    Returns:
        List of Diagnostics if sequential type guards are found.

    """
    body = func_node.body
    if not body:
        return []

    start_idx = 1 if len(body) > 1 and _is_docstring(body[0]) else 0
    stmts = body[start_idx:]
    if len(stmts) < _MIN_SENTINEL_COUNT:
        return []

    target_var: str | None = None
    sentinel_count = 0
    for stmt in stmts:
        var = _passthrough_guard_var(stmt)
        if var is None or (target_var is not None and var != target_var):
            break
        target_var = var
        sentinel_count += 1

    if sentinel_count < _MIN_SENTINEL_COUNT:
        return []

    first_if = stmts[0]
    return [
        Diagnostic(
            path=path,
            line=getattr(first_if, "lineno", func_node.lineno),
            col=first_if.col_offset + 1,
            code=code,
            message=(
                f"Sequential sentinel/type guards ({sentinel_count} checks on '{target_var}') "
                f"in function '{func_node.name}' — refactor into Python 3.10+ match/case pattern matching "
                f"(e.g., 'case None | Unset():')."
            ),
        )
    ]


@final
class _TypeDispatchVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, code: str, *, report_control_flow_raise: bool) -> None:
        self.path: Path = path
        self.code: str = code
        self.report_control_flow_raise: bool = report_control_flow_raise
        self.diags: list[Diagnostic] = []
        self.try_stack: list[ast.Try | ast.TryStar] = []

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        self.try_stack.append(node)
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
        if self.report_control_flow_raise:
            self._check_control_flow_raise(node)
        self.generic_visit(node)

    def _check_control_flow_raise(self, node: ast.Raise) -> None:
        exc_name = _raised_exception_name(node)
        if exc_name is None:
            return

        # Only the innermost try that would catch this exception can see it;
        # anything further out never runs, so the search stops there.
        target: tuple[ast.Try | ast.TryStar, ast.ExceptHandler] | None = None
        for try_node in reversed(self.try_stack):
            handler = _first_matching_handler(try_node, exc_name)
            if handler is not None:
                target = (try_node, handler)
                break
        if target is None:
            return
        try_node, handler = target

        names = _handler_exception_names(handler)
        if names is None or exc_name not in names:
            return
        if _always_raises(handler.body):
            return
        if _try_body_span(try_node) > _MAX_TRY_BODY_LINES:
            return
        if _is_bare_raise_body(try_node):
            return

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
    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ080"
    has_evidence: bool = True
    description: str = (
        "Control-flow raise in try block or sequential type guards — prefer Python 3.10+ match/case pattern matching."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _TypeDispatchVisitor(path, self.code, report_control_flow_raise=not is_test_path(path))
        visitor.visit(tree)
        visitor.diags.sort(key=lambda d: (d.line, d.col))
        return visitor.diags
