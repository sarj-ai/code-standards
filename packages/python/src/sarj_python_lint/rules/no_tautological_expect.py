from __future__ import annotations

import ast
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

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
from sarj_python_lint.rules._pytest import has_benchmark_marker, uses_benchmark_fixture


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class _Tautology(NamedTuple):
    node: ast.Assert | ast.Call
    reason: str


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

_CONTAINER_KINDS = MappingProxyType(
    {
        ast.List: "list",
        ast.Set: "set",
        ast.Dict: "dict",
        ast.Tuple: "tuple",
    }
)


class NoTautologicalExpect(Rule):
    id: str = "no-tautological-expect"
    code: str = "SARJ057"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Assertion outcome is fixed entirely by literal values.",
        rationale="An always-passing assertion cannot verify runtime behavior and can hide a missing comparison.",
        remediation="Assert against a value produced by the code under test.",
        category=RuleCategory.TESTING,
        limitations=(
            "Detection covers truthy literal asserts and supported unittest methods with literal-only operands.",
            "Always-failing markers, benchmark tests, deliberate match-arm markers, and runtime-value comparisons are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="literal-only-assertion",
                title="Assertion always passes",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/test_service.py", "def test_service():\n    assert True\n"),),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="runtime-value-assertion",
                title="Assertion checks runtime output",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "def test_service(result):\n    assert result == 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
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
    if not any(all(_always_fails(stmt) for stmt in case.body) for case in node.cases):
        return set()
    return {
        stmt for case in node.cases for stmt in case.body if isinstance(stmt, ast.Assert) and not _always_fails(stmt)
    }


def _always_fails(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Assert):
        return _is_always_falsy_literal(stmt.test)
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _called_method(stmt.value) == _FAIL


def _tautologies(tree: ast.Module, exempt: set[ast.AST]) -> list[_Tautology]:
    found: list[_Tautology] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assert, ast.Call)) or node in exempt:
            continue
        reason = _fixed_truth_reason(node.test) if isinstance(node, ast.Assert) else _unittest_reason(node)
        if reason is not None:
            found.append(_Tautology(node, reason))
    return found


def _unittest_reason(node: ast.Call) -> str | None:
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
    if _constant_truth(test) is True:
        return f"`{_preview(test)}` is a constant truthy value"
    kind = _nonempty_container_kind(test)
    if kind is not None:
        return f"a non-empty {kind} display is truthy whatever it contains"
    if _is_identical_literal_comparison(test):
        return f"`{_preview(test)}` compares a literal with an identical literal"
    return None


def _constant_truth(node: ast.expr) -> bool | None:
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
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return False
    if not isinstance(node.ops[0], _SAMENESS_OPS):
        return False
    return _is_same_literal(node.left, node.comparators[0])


def _is_same_literal(left: ast.expr, right: ast.expr) -> bool:
    return _is_literal(left) and _is_literal(right) and ast.dump(left) == ast.dump(right)


def _is_literal(node: ast.expr) -> bool:
    match node:
        case ast.Constant():
            return True
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=operand):
            # `-1` is a negation of a constant, not a constant; without this,
            # `assertEqual(-1, -1)` would slip through.
            return _is_literal(operand)
        case ast.List() | ast.Set() | ast.Tuple():
            return all(_is_literal(element) for element in node.elts)
        case ast.Dict(keys=keys, values=values):
            return all(key is not None and _is_literal(key) for key in keys) and all(
                _is_literal(value) for value in values
            )
        case _:
            return False


def _is_always_falsy_literal(node: ast.expr) -> bool:
    if _constant_truth(node) is False:
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _called_method(node: ast.Call) -> str | None:
    match node.func:
        case ast.Attribute(attr=name) | ast.Name(id=name):
            return name
        case _:
            return None


def _preview(node: ast.expr) -> str:
    text = " ".join(ast.unparse(node).split())
    if len(text) > _OPERAND_PREVIEW_CHARS:
        return f"{text[:_OPERAND_PREVIEW_CHARS]}…"
    return text


def _message(node: ast.Assert | ast.Call, reason: str) -> str:
    slid_into_message_slot = isinstance(node, ast.Assert) and node.msg is not None
    hint = (
        " The expression you meant to assert on is sitting in the assertion-message slot — move it into the condition."
        if slid_into_message_slot
        else " Assert on a value the code produced, or delete the test."
    )
    return f"This assertion can never fail: {reason}.{hint}"
