"""SARJ057 — An assertion whose outcome is decided by the literal it was handed.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_tautological_expect.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._pytest import has_benchmark_marker, uses_benchmark_fixture


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# `pytest.fail(...)` / `self.fail(...)` — an arm that calls it cannot pass.
_FAIL = "fail"

# unittest methods whose single argument fixes the outcome on its own.
_TRUTHY_ARG_METHODS = frozenset({"assertTrue"})
_FALSY_ARG_METHODS = frozenset({"assertFalse"})

# unittest methods that compare two operands for sameness.
_EQUALITY_METHODS = frozenset({"assertEqual", "assertEquals", "assertIs"})

# unittest's failure-text parameter — present or not, the outcome is the same.
_UNITTEST_MSG_KWARG = "msg"

# `assertEqual(first, second)` and friends: the two operands compared.
_EQUALITY_ARITY = 2

# Comparison operators whose two-identical-literals form is a tautology.
_SAMENESS_OPS = (ast.Eq, ast.Is)

# Enough of the operand to identify it in the message without pasting a screenful.
_OPERAND_PREVIEW_CHARS = 40

_CONTAINER_KINDS: dict[type[ast.expr], str] = {
    ast.List: "list",
    ast.Set: "set",
    ast.Dict: "dict",
    ast.Tuple: "tuple",
}


class NoTautologicalExpect(Rule):
    id: str = "no-tautological-expect"
    code: str = "SARJ057"
    description: str = "Assertion whose operands are all literals — its outcome is fixed before the code runs."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag assertions whose truth is decided by their own literals."""
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        exempt = _exempt_nodes(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_message(node, reason),
            )
            for node, reason in _tautologies(tree, exempt)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _exempt_nodes(tree: ast.Module) -> set[ast.AST]:
    """Collect the nodes the carve-outs put out of reach."""
    exempt: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES) and (uses_benchmark_fixture(node) or has_benchmark_marker(node)):
            exempt.update(ast.walk(node))
        elif isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Assert):
            exempt.add(node.body[0])
        elif isinstance(node, ast.Match):
            exempt.update(_match_arm_markers(node))
    return exempt


def _match_arm_markers(node: ast.Match) -> set[ast.AST]:
    """Collect `assert <constant>` statements marking which arm of a `match` ran."""
    if not any(all(_always_fails(stmt) for stmt in case.body) for case in node.cases):
        return set()
    return {
        stmt for case in node.cases for stmt in case.body if isinstance(stmt, ast.Assert) and not _always_fails(stmt)
    }


def _always_fails(stmt: ast.stmt) -> bool:
    """Report whether `stmt` cannot complete without failing the test."""
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Assert):
        return _is_always_falsy_literal(stmt.test)
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _called_method(stmt.value) == _FAIL


def _tautologies(tree: ast.Module, exempt: set[ast.AST]) -> list[tuple[ast.Assert | ast.Call, str]]:
    """Find every assertion in `tree` whose outcome its own literals decide."""
    found: list[tuple[ast.Assert | ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assert, ast.Call)) or node in exempt:
            continue
        reason = _fixed_truth_reason(node.test) if isinstance(node, ast.Assert) else _unittest_reason(node)
        if reason is not None:
            found.append((node, reason))
    return found


def _unittest_reason(node: ast.Call) -> str | None:
    """Describe why a `unittest` assertion call cannot fail, if it cannot."""
    name = _called_method(node)
    # `msg=` is unittest's failure text and changes nothing about the outcome;
    # any other keyword means this is not the method we think it is.
    if name is None or any(kw.arg != _UNITTEST_MSG_KWARG for kw in node.keywords):
        return None
    args = node.args
    if name in _EQUALITY_METHODS and len(args) >= _EQUALITY_ARITY and _is_same_literal(args[0], args[1]):
        return f"`{_preview(args[0])}` is compared with an identical literal"
    if len(args) < 1:
        return None
    if name in _TRUTHY_ARG_METHODS:
        return _fixed_truth_reason(args[0])
    if name in _FALSY_ARG_METHODS and _is_always_falsy_literal(args[0]):
        return f"`{_preview(args[0])}` is a literal that is always falsy"
    return None


def _fixed_truth_reason(test: ast.expr) -> str | None:
    """Describe why `test` is always truthy, if it is."""
    if _constant_truth(test) is True:
        return f"`{_preview(test)}` is a constant truthy value"
    kind = _nonempty_container_kind(test)
    if kind is not None:
        return f"a non-empty {kind} display is truthy whatever it contains"
    if _is_identical_literal_comparison(test):
        return f"`{_preview(test)}` compares a literal with an identical literal"
    return None


def _constant_truth(node: ast.expr) -> bool | None:
    """Evaluate the truthiness of a scalar constant, `-1`, `+0` and `not 0` included."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            return _constant_truth(node.operand)
        if isinstance(node.op, ast.Not):
            operand_truth = _constant_truth(node.operand)
            return None if operand_truth is None else not operand_truth
    return None


def _nonempty_container_kind(node: ast.expr) -> str | None:
    """Name the container display kind when `node` is a provably non-empty one."""
    if isinstance(node, ast.Dict):
        if not node.keys or any(key is None for key in node.keys):
            return None
        return _CONTAINER_KINDS[ast.Dict]
    if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return None
    if not node.elts or any(isinstance(elt, ast.Starred) for elt in node.elts):
        return None
    return _CONTAINER_KINDS[type(node)]


def _is_identical_literal_comparison(node: ast.expr) -> bool:
    """Report whether `node` compares one literal with a textually identical one."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return False
    if not isinstance(node.ops[0], _SAMENESS_OPS):
        return False
    return _is_same_literal(node.left, node.comparators[0])


def _is_same_literal(left: ast.expr, right: ast.expr) -> bool:
    """Report whether both operands are literals with identical syntax."""
    return _is_literal(left) and _is_literal(right) and ast.dump(left) == ast.dump(right)


def _is_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal built entirely from constants."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        # `-1` is a negation of a constant, not a constant; without this,
        # `assertEqual(-1, -1)` would slip through.
        return isinstance(node.op, (ast.USub, ast.UAdd)) and _is_literal(node.operand)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_is_literal(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and _is_literal(key) for key in node.keys) and all(
            _is_literal(value) for value in node.values
        )
    return False


def _is_always_falsy_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal that is always falsy."""
    if _constant_truth(node) is False:
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _called_method(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _preview(node: ast.expr) -> str:
    """Render `node` back to source, truncated so the message stays one line."""
    text = " ".join(ast.unparse(node).split())
    if len(text) > _OPERAND_PREVIEW_CHARS:
        return f"{text[:_OPERAND_PREVIEW_CHARS]}…"
    return text


def _message(node: ast.Assert | ast.Call, reason: str) -> str:
    """Compose the diagnostic, adding the message-slot hint where it applies."""
    slid_into_message_slot = isinstance(node, ast.Assert) and node.msg is not None
    hint = (
        " The expression you meant to assert on is sitting in the assertion-message slot — move it into the condition."
        if slid_into_message_slot
        else " Assert on a value the code produced, or delete the test."
    )
    return f"This assertion can never fail: {reason}.{hint}"
