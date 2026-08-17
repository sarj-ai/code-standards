"""SARJ413 — Repeated static call assertions should be named test cases.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_repeated_static_call_cases.py
"""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import PurePosixPath
import tokenize
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
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
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules.duplicate_test_body import duplicate_test_owner_ids


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_MIN_CASES = 3
_MIN_DISTINCT_CASES = 2
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_ACCESSOR_CALLEES = frozenset({"get"})
_UNSAFE_CALLEE_PARTS = frozenset({"mock", "snapshot", "spy"})


@final
class RepeatedStaticCallCases(Rule):
    id = "repeated-static-call-cases"
    code = "SARJ413"
    documentation = RuleDocumentation(
        summary="Repeated static call assertions are hidden inside one coarse test case.",
        rationale=(
            "When several independent static inputs share one test callback, the first failure hides later cases "
            "and the runner cannot name the input that failed."
        ),
        remediation="Move the inputs and expectations into a named pytest parameter table.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only runs of at least three consecutive top-level assertions in collected pytest-style tests are checked.",
            "Calls, inputs, and expectations must be statically representable; unittest classes, zero-argument calls, mocks, snapshots, and intervening prose or setup are excluded.",
            "Common mapping accessors are excluded because repeated field assertions usually describe one cohesive object contract, not independent input cases.",
            "Tests participating in a duplicate-test-body group are left to SARJ066, which has the broader finding.",
            "Case names and parameter boundaries require judgment, so the rule has no autofix.",
        ),
        examples=(
            RuleExample(
                example_id="parameterized-parser-cases",
                title="Give each parser input a runner-visible case",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_parser.py",
                        "@pytest.mark.parametrize(('value', 'expected'), [('a', 1), ('b', 2), ('c', 3)])\ndef test_parse(value, expected):\n    assert parse(value) == expected\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_parser.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="repeated-parser-assertions",
                title="Do not hide independent inputs in one callback",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_parser.py",
                        "def test_parse():\n    assert parse('a') == 1\n    assert parse('b') == 2\n    assert parse('c') == 3\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_parser.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        comments = _comment_lines(source)
        duplicate_owners = duplicate_test_owner_ids(tree, source)
        findings = [
            Diagnostic(
                path=path,
                line=run[0].lineno,
                col=run[0].col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"these {len(run)} static call assertions run as one coarse test; move the inputs and "
                    "expectations into named pytest parameters."
                ),
            )
            for test in _test_functions(tree)
            if id(test) not in duplicate_owners
            for run in _runs(test, comments)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _dotted_name(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else (*parent, node.attr)
    return None


def _comment_lines(source: str) -> frozenset[int]:
    try:
        return frozenset(
            token.start[0]
            for token in tokenize.generate_tokens(StringIO(source).readline)
            if token.type == tokenize.COMMENT
        )
    except IndentationError, tokenize.TokenError:
        return frozenset()


def _test_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    local_classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def is_test_case(node: ast.ClassDef, seen: frozenset[str] = frozenset()) -> bool:
        if node.name in seen:
            return False
        for base in node.bases:
            name = _base_name(base)
            if name is not None and name.endswith("TestCase"):
                return True
            if name in local_classes and is_test_case(local_classes[name], seen | {node.name}):
                return True
        return False

    for statement in tree.body:
        if isinstance(statement, _FUNC_NODES) and statement.name.startswith("test_"):
            yield statement
        elif isinstance(statement, ast.ClassDef) and not is_test_case(statement):
            yield from (
                child for child in statement.body if isinstance(child, _FUNC_NODES) and child.name.startswith("test_")
            )


def _base_name(node: ast.expr) -> str | None:
    dotted = _dotted_name(node)
    return None if dotted is None else dotted[-1]


def _runs(test: ast.FunctionDef | ast.AsyncFunctionDef, comments: frozenset[int]) -> Iterator[list[ast.Assert]]:
    current: list[ast.Assert] = []
    current_shape: object | None = None
    current_values: set[str] = set()
    for statement in test.body:
        if not isinstance(statement, ast.Assert) or _has_attached_comment(statement, comments):
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_shape, current_values = [], None, set()
            continue
        parsed = _assertion_shape(statement)
        if parsed is None:
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_shape, current_values = [], None, set()
            continue
        shape, values = parsed
        if current and (shape != current_shape or _has_intervening_comment(current[-1], statement, comments)):
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_values = [], set()
        current.append(statement)
        current_shape = shape
        current_values.add(values)
    if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
        yield current


def _assertion_shape(node: ast.Assert) -> tuple[object, str] | None:
    expression = node.test
    polarity = "truthy"
    expectation: ast.expr | None = None
    call_expr: ast.expr
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        polarity = "falsy"
        call_expr = expression.operand
    elif isinstance(expression, ast.Compare) and len(expression.ops) == 1 and len(expression.comparators) == 1:
        call_expr = expression.left
        expectation = expression.comparators[0]
        polarity = type(expression.ops[0]).__name__
    else:
        call_expr = expression
    parsed = _call(call_expr)
    if parsed is None or (expectation is not None and not _static(expectation)):
        return None
    call, awaited = parsed
    callee = _dotted_name(call.func)
    if (
        callee is None
        or not _eligible_callee(callee)
        or not call.args
        or any(isinstance(arg, ast.Starred) or not _static(arg) for arg in call.args)
        or any(keyword.arg is None or not _static(keyword.value) for keyword in call.keywords)
    ):
        return None
    skeleton = (
        callee,
        awaited,
        polarity,
        tuple(_static_shape(arg) for arg in call.args),
        tuple((keyword.arg, _static_shape(keyword.value)) for keyword in call.keywords),
        None if expectation is None else _static_shape(expectation),
    )
    values = _static_value(ast.Tuple(elts=[*call.args, *(keyword.value for keyword in call.keywords)], ctx=ast.Load()))
    return skeleton, values


def _eligible_callee(callee: tuple[str, ...]) -> bool:
    return callee[-1] not in _ACCESSOR_CALLEES and not any(
        any(part in segment.lower() for part in _UNSAFE_CALLEE_PARTS) for segment in callee
    )


def _has_intervening_comment(previous: ast.Assert, current: ast.Assert, comments: frozenset[int]) -> bool:
    return any((previous.end_lineno or previous.lineno) < line < current.lineno for line in comments)


def _has_attached_comment(statement: ast.Assert, comments: frozenset[int]) -> bool:
    return any(statement.lineno <= line <= (statement.end_lineno or statement.lineno) for line in comments)


def _call(node: ast.expr) -> tuple[ast.Call, bool] | None:
    awaited = isinstance(node, ast.Await)
    candidate = node.value if awaited else node
    return (candidate, awaited) if isinstance(candidate, ast.Call) else None


def _static(node: ast.expr) -> bool:
    match node:
        case ast.Constant():
            return True
        case ast.Attribute():
            return _dotted_name(node) is not None
        case ast.UnaryOp(op=ast.UAdd() | ast.USub() | ast.Invert(), operand=operand):
            return _static(operand)
        case ast.Tuple() | ast.List() | ast.Set():
            return all(_static(elt) for elt in node.elts)
        case ast.Dict(keys=keys, values=values):
            return all(key is not None and _static(key) for key in keys) and all(_static(value) for value in values)
        case _:
            return False


def _static_shape(node: ast.expr) -> object:
    match node:
        case ast.Constant(value=value):
            return ("constant", type(value).__name__)
        case ast.Attribute():
            return ("symbol", len(_dotted_name(node) or ()))
        case ast.UnaryOp(op=op, operand=operand):
            return (type(op).__name__, _static_shape(operand))
        case ast.Tuple() | ast.List() | ast.Set():
            return (type(node).__name__, tuple(_static_shape(elt) for elt in node.elts))
        case ast.Dict(keys=keys, values=values):
            return (
                "Dict",
                tuple(
                    (_static_shape(key), _static_shape(value)) for key, value in zip(keys, values, strict=True) if key
                ),
            )
        case _:
            raise AssertionError


def _static_value(node: ast.expr) -> str:
    """Return a bounded comparison token without retaining a large literal."""
    rendered = ast.dump(node, annotate_fields=False, include_attributes=False)
    return rendered[:512]
