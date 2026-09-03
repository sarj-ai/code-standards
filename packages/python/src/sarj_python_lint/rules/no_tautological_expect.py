from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class _Tautology(NamedTuple):
    node: ast.Assert
    reason: str


# `pytest.fail(...)` / `self.fail(...)` — an arm that calls it cannot pass.
_FAIL = "fail"

# Enough of the operand to identify it in the message without pasting a screenful.
_OPERAND_PREVIEW_CHARS = 40


class NoTautologicalExpect(Rule):
    id: str = "no-statically-truthy-assertion"
    code: str = "SARJ057"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A bare assertion condition is statically truthy.",
        rationale=(
            "A condition that stays truthy whenever evaluation succeeds cannot reject an incorrect result and often "
            "means the intended condition was wrapped in a container or placed in the message slot."
        ),
        remediation=(
            "Assert an explicit runtime-derived condition. If the test only requires an operation not to raise, "
            "evaluate it directly and retain any meaningful follow-up assertion."
        ),
        category=RuleCategory.TESTING,
        aliases=("no-tautological-expect",),
        limitations=(
            "Detection covers truthy scalar constants and definitely non-empty list, set, and dict displays.",
            "Ruff owns asserted strings and tuples, literal comparisons and identity, and unittest-style assertion methods.",
            "Generated files, always-failing assertions, deliberate match-arm success markers, and runtime-value comparisons are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="condition-in-message-slot",
                title="The intended condition became an assertion message",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "def test_service(response):\n    assert True, response.status_code == 200\n",
                    ),
                ),
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
                        "def test_service(response):\n    assert response.status_code == 200\n",
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
        if is_generated(path, source):
            return []
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
                severity=Severity.WARNING,
            )
            for node, reason in _tautologies(tree, exempt)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _exempt_nodes(tree: ast.Module) -> set[ast.AST]:
    exempt: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Match):
            exempt.update(_match_arm_markers(node))
    return exempt


def _match_arm_markers(node: ast.Match) -> set[ast.AST]:
    if not any(all(_always_fails(stmt) for stmt in case.body) for case in node.cases):
        return set()
    return {
        case.body[0]
        for case in node.cases
        if len(case.body) == 1
        and isinstance(case.body[0], ast.Assert)
        and _constant_truth(case.body[0].test) is True
        and not _ruff_owned_string(case.body[0].test)
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
        if not isinstance(node, ast.Assert) or node in exempt:
            continue
        reason = _fixed_truth_reason(node.test)
        if reason is not None:
            found.append(_Tautology(node, reason))
    return found


def _fixed_truth_reason(test: ast.expr) -> str | None:
    if _constant_truth(test) is True and not _ruff_owned_string(test):
        return f"`{_preview(test)}` is a constant truthy value"
    kind = _nonempty_container_kind(test)
    if kind is not None:
        return f"a non-empty {kind} display is truthy whatever it contains"
    return None


def _ruff_owned_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))


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
        return "dict" if any(key is not None for key in node.keys) else None
    if not isinstance(node, (ast.List, ast.Set)):
        return None
    return type(node).__name__.lower() if any(not isinstance(elt, ast.Starred) for elt in node.elts) else None


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


def _message(node: ast.Assert, reason: str) -> str:
    slid_into_message_slot = node.msg is not None
    hint = (
        " The message is never displayed; if it is the intended condition, move it before the comma."
        if slid_into_message_slot
        else " Assert an explicit postcondition, or evaluate the expression directly for a no-raise test."
    )
    return f"This assertion condition is always truthy if evaluation succeeds: {reason}.{hint}"
