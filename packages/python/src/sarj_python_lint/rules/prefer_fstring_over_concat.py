"""SARJ068 — Build a string with an f-string, not `"literal" + expression`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_fstring_over_concat.py
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Method names that make a logger-receiver call a logging call.

# An uppercase SQL suffix marks a query fragment whose concatenation is intentional.
_SQL_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WHERE|FROM|JOIN|ORDER\s+BY|GROUP\s+BY|VALUES|SET)\b\s*$"
)

# Calls returning a lazy translation proxy or an escape-aware SafeString.
_LAZY_CALLS = frozenset(
    {
        "_",
        "lazy",
        "format_lazy",
        "gettext",
        "gettext_lazy",
        "ngettext",
        "ngettext_lazy",
        "pgettext",
        "pgettext_lazy",
        "npgettext",
        "npgettext_lazy",
        "ugettext",
        "ugettext_lazy",
        "mark_safe",
        "format_html",
    }
)

# Preserve percent-format templates instead of mixing formatting styles.
_PCT_FORMAT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})(?:\([^)]*\))?[-#0+]?[0-9*.]*[hlL]?[diouxXeEfFgGcrsa%]")

# Constructors that build an ORM / SQL *expression object*, not a string.
_ORM_CALLS = frozenset({"F", "Value", "literal", "literal_column", "Concat", "RawSQL", "bindparam"})

# Roots whose attribute calls are SQLAlchemy expression constructors
# (`func.coalesce(...)`, `expression.cast(...)`, `sa.func.lower(...)`).
_ORM_ROOTS = frozenset({"func", "expression", "sa", "sqla", "sqlalchemy"})

# Past this many operands an f-string is a wall of placeholders and `"".join`
# (or a template) is usually the better answer; the message says so.
_JOIN_RECOMMENDATION_OPERANDS = 5

# A `<expr> + "<whitespace>"` pair is a terminator, not string building.
_TERMINATOR_OPERANDS = 2


class PreferFstringOverConcat(Rule):
    id: str = "prefer-fstring-over-concat"
    code: str = "SARJ068"
    description: str = (
        "String built with `+` from a literal and a runtime expression — an f-string needs no "
        "`str()` coercion and keeps the literal's spacing visible."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag `+` string building that an f-string expresses better."""
        if "+" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        # One walk collects everything: the candidate chains, the inner links of
        # each chain (so a 4-operand chain reports once), and the chains sitting
        # in a context whose rewrite would be wrong.
        inner: set[int] = set()
        excluded: set[int] = set()
        adds: list[ast.BinOp] = []
        for node in nodes(tree, ast.BinOp, ast.Call):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                adds.append(node)
                for side in (node.left, node.right):
                    if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add):
                        inner.add(id(side))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                # `("%0" + width + "d") % args` builds a format template.
                excluded.add(id(node.left))
            elif isinstance(node, ast.Call) and _is_logging_call(node):
                arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
                excluded.update(id(sub) for arg in arguments for sub in walk(arg))

        diags: list[Diagnostic] = []
        comment_lines: frozenset[int] | None = None
        for node in adds:
            if id(node) in inner or id(node) in excluded:
                continue
            message = _verdict(node)
            if message is None:
                continue
            if node.end_lineno is not None and node.end_lineno > node.lineno:
                # Tokenizing is the one thing here that costs real time, and it
                # can only ever REJECT, so it is deferred until a multi-line
                # chain has already earned a diagnostic.
                if comment_lines is None:
                    comment_lines = _comment_lines(source)
                if any(node.lineno <= line <= node.end_lineno for line in comment_lines):
                    continue
            diags.append(
                Diagnostic(path=path, line=node.lineno, col=node.col_offset + 1, code=self.code, message=message)
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _comment_lines(source: str) -> frozenset[int]:
    """Collect the 1-based line numbers carrying a `#` comment."""
    try:
        return frozenset(
            token.start[0]
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        )
    except tokenize.TokenError, IndentationError, SyntaxError:  # pragma: no cover — parse already succeeded
        return frozenset()


def _is_logging_call(node: ast.Call) -> bool:
    """Report whether `node` is a logging call, using SARJ017's receiver resolver."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)


def _flatten(node: ast.expr) -> list[ast.expr]:
    """Flatten a nested `+` chain into its operands."""
    operands: list[ast.expr] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.BinOp) and isinstance(current.op, ast.Add):
            # Push right first so the left spine is popped first and the
            # operands come out in source order.
            stack.extend((current.right, current.left))
        else:
            operands.append(current)
    return operands


def _verdict(node: ast.BinOp) -> str | None:
    """Judge one outermost `+` chain and build its message."""
    literals: list[str] = []
    dynamic: list[ast.expr] = []
    operands = _flatten(node)
    for operand in operands:
        if isinstance(operand, ast.Constant):
            if not isinstance(operand.value, str):
                # A bytes/int/float literal is positive evidence this `+` is not
                # string concatenation at all.
                return None
            literals.append(operand.value)
        else:
            dynamic.append(operand)
    if not literals or not dynamic:
        return None
    if any("{" in text or "}" in text for text in literals):
        return None
    if any(_SQL_RE.search(text) for text in literals):
        return None
    if any(_PCT_FORMAT_RE.search(text) for text in literals):
        return None
    if any(
        _is_join_call(expr) or _is_string_repetition(expr) or _is_lazy_call(expr) or _is_orm_expression(expr)
        for expr in dynamic
    ):
        return None
    if any(isinstance(expr, ast.IfExp | ast.BoolOp) for expr in dynamic):
        return None
    if len(operands) == _TERMINATOR_OPERANDS and all(not text.strip() for text in literals):
        return None
    if _is_blob_glue(operands, dynamic):
        return None

    message = (
        "string built with `+` from a literal and a runtime value — write it as one f-string, "
        "which keeps the literal's spacing visible and needs no `str()` coercion"
    )
    if any(_is_str_call(expr) for expr in dynamic):
        message += "; the `str(...)` wrapper disappears"
    if len(operands) >= _JOIN_RECOMMENDATION_OPERANDS:
        message += f"; at {len(operands)} operands `''.join(...)` may read better still"
    return message


def _is_join_call(expr: ast.expr) -> bool:
    """Report whether `expr` is a `<sep>.join(...)` call."""
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "join"


def _root_name(expr: ast.expr) -> str:
    """Walk an attribute/subscript spine down to its leftmost `Name`."""
    while isinstance(expr, ast.Attribute | ast.Subscript):
        expr = expr.value
    return expr.id if isinstance(expr, ast.Name) else ""


def _is_orm_expression(expr: ast.expr) -> bool:
    """Report whether `expr` builds an ORM/SQL expression object rather than a string."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name) and func.id in _ORM_CALLS:
        return True
    return isinstance(func, ast.Attribute) and _root_name(func) in _ORM_ROOTS


def _template_text(operands: list[ast.expr]) -> list[str]:
    """Collect every literal text fragment in the chain, f-string parts included."""
    text: list[str] = []
    for operand in operands:
        if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
            text.append(operand.value)
        elif isinstance(operand, ast.JoinedStr):
            text += [
                val for part in operand.values if isinstance(part, ast.Constant) and isinstance(val := part.value, str)
            ]
    return text


def _has_string_literal_argument(expr: ast.expr) -> bool:
    """Report whether `expr` is a call carrying a string literal in its arguments."""
    if not isinstance(expr, ast.Call):
        return False
    arguments: list[ast.expr] = [*expr.args, *(kw.value for kw in expr.keywords)]
    return any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in arguments)


def _is_blob_glue(operands: list[ast.expr], dynamic: list[ast.expr]) -> bool:
    """Report whether the chain only glues opaque blobs together with whitespace."""
    text = _template_text(operands)
    if not text or any(fragment.strip() for fragment in text):
        return False
    return any(_has_string_literal_argument(expr) for expr in dynamic)


def _is_lazy_call(expr: ast.expr) -> bool:
    """Report whether `expr` yields a lazy translation proxy or a SafeString."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    return name in _LAZY_CALLS


def _is_str_call(expr: ast.expr) -> bool:
    """Report whether `expr` is a `str(...)` coercion the f-string would delete."""
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "str"


def _is_string_repetition(expr: ast.expr) -> bool:
    """Report whether `expr` is a `"x" * n` padding/separator construction."""
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, ast.Mult):
        return False
    return any(isinstance(side, ast.Constant) and isinstance(side.value, str) for side in (expr.left, expr.right))
