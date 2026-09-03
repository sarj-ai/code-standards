from __future__ import annotations

import ast
from http import HTTPStatus
from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_SERVER_ERROR_MIN = 500
_SERVER_ERROR_MAX = 599
_SERVER_ERROR_FAMILY = 5
_STATUS_FAMILY_DIVISOR = 100
_RANGE_COMPARISON_COUNT = 2
_STATUS_CONSTANT_RE = re.compile(r"HTTP_(\d{3})(?:_.+)?")
_HTTP_STATUS_SOURCES = frozenset({"http"})
_FRAMEWORK_STATUS_SOURCES = frozenset(
    {
        "fastapi",
        "fastapi.status",
        "rest_framework",
        "rest_framework.status",
        "starlette",
        "starlette.status",
    }
)


def _int(node: ast.expr, imports: ImportIndex) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    terminal_name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
    imported_name = imports.resolved_symbol(node, sources=_FRAMEWORK_STATUS_SOURCES)
    name = imported_name or terminal_name
    if (match := _STATUS_CONSTANT_RE.fullmatch(name)) and (
        imported_name is not None or _is_framework_status_receiver(node, imports)
    ):
        return int(match.group(1))
    if (
        isinstance(node, ast.Attribute)
        and imports.resolves(node.value, sources=_HTTP_STATUS_SOURCES, symbol="HTTPStatus")
        and (member := HTTPStatus.__members__.get(node.attr)) is not None
    ):
        return member.value
    return None


def _is_framework_status_receiver(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Attribute) and imports.resolves(
        node.value,
        sources=frozenset({"fastapi", "rest_framework", "starlette"}),
        symbol="status",
    )


def _negative_only(node: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Compare):
        return _positive_server_error(node.operand, imports)
    if not isinstance(node, ast.Compare):
        return False
    compare = node
    if len(compare.ops) != 1 or len(compare.comparators) != 1:
        return False
    left = compare.left
    right = compare.comparators[0]
    op = compare.ops[0]
    match op:
        case ast.NotEq():
            return (
                (_status_code(left) and _server_error(right, imports))
                or (_server_error(left, imports) and _status_code(right))
                or (_status_family(left, imports) and _int(right, imports) == _SERVER_ERROR_FAMILY)
                or (_int(left, imports) == _SERVER_ERROR_FAMILY and _status_family(right, imports))
            )
        case ast.Lt() if _status_code(left):
            return _int(right, imports) == _SERVER_ERROR_MIN
        case ast.LtE() if _status_code(left):
            return _int(right, imports) == _SERVER_ERROR_MIN - 1
        case ast.NotIn() if _status_code(left):
            return _all_server_errors(right, imports)
        case _:
            return False


def _positive_server_error(compare: ast.Compare, imports: ImportIndex) -> bool:
    if len(compare.ops) == 1 and len(compare.comparators) == 1:
        left = compare.left
        right = compare.comparators[0]
        match compare.ops[0]:
            case ast.Eq():
                return (_status_code(left) and _server_error(right, imports)) or (
                    _server_error(left, imports) and _status_code(right)
                )
            case ast.GtE():
                return _status_code(left) and _int(right, imports) == _SERVER_ERROR_MIN
            case ast.Gt():
                return _status_code(left) and _int(right, imports) == _SERVER_ERROR_MIN - 1
            case ast.LtE():
                return _int(left, imports) == _SERVER_ERROR_MIN and _status_code(right)
            case ast.Lt():
                return _int(left, imports) == _SERVER_ERROR_MIN - 1 and _status_code(right)
            case ast.In():
                return _status_code(left) and _all_server_errors(right, imports)
            case _:
                return False
    if len(compare.ops) != _RANGE_COMPARISON_COUNT or len(compare.comparators) != _RANGE_COMPARISON_COUNT:
        return False
    lower, status, upper = compare.left, *compare.comparators
    return (
        _int(lower, imports) == _SERVER_ERROR_MIN
        and _status_code(status)
        and _int(upper, imports) in {_SERVER_ERROR_MAX, _SERVER_ERROR_MAX + 1}
        and isinstance(compare.ops[0], ast.LtE)
        and isinstance(compare.ops[1], (ast.Lt, ast.LtE))
    )


def _status_code(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "status_code"


def _status_family(node: ast.expr, imports: ImportIndex) -> bool:
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.FloorDiv)
        and _status_code(node.left)
        and _int(node.right, imports) == _STATUS_FAMILY_DIVISOR
    )


def _server_error(node: ast.expr, imports: ImportIndex) -> bool:
    value = _int(node, imports)
    return value is not None and _SERVER_ERROR_MIN <= value <= _SERVER_ERROR_MAX


def _all_server_errors(node: ast.expr, imports: ImportIndex) -> bool:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and imports.builtin_is_unshadowed("range")
    ):
        values = [_int(arg, imports) for arg in node.args]
        return values == [_SERVER_ERROR_MIN, _SERVER_ERROR_MAX + 1]
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)) or not node.elts:
        return False
    values = [_int(elt, imports) for elt in node.elts]
    return all(value is not None and _SERVER_ERROR_MIN <= value <= _SERVER_ERROR_MAX for value in values)


def _test_nodes(test: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    stack: list[ast.AST] = [*reversed(test.body)]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _collected_tests(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name.startswith("test_"):
            yield statement
            continue
        if not isinstance(statement, ast.ClassDef) or not (
            statement.name.startswith("Test")
            or any(
                (isinstance(base, ast.Name) and base.id == "TestCase")
                or (isinstance(base, ast.Attribute) and base.attr == "TestCase")
                for base in statement.bases
            )
        ):
            continue
        yield from (
            child
            for child in statement.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
        )


@final
class NegativeOnlyHttpStatusAssertion(Rule):
    id = "negative-only-http-status-assertion"
    code = "SARJ408"
    documentation = RuleDocumentation(
        summary="HTTP test assertion only excludes a server error instead of identifying the intended response.",
        rationale=(
            "Authentication, routing, validation, and domain failures can all replace the intended response while "
            "a negative-only status assertion remains green."
        ),
        remediation=(
            "Assert the intended exact status and the relevant domain payload or side effect. When the explicit "
            "contract is only that a fuzz, chaos, smoke, or crash-regression request avoids a server exception, "
            "suppress SARJ408 on that assertion with a concise reason."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only assertions on an attribute named `status_code` in collected Python tests are checked.",
            "Exact status contracts, finite success sets, arbitrary `.status` attributes, and locally suppressed chaos tests are excluded.",
            "Only Python `assert` statements in default test_* collection shapes are analyzed.",
            "The intended status cannot be inferred safely, so the rule has no autofix.",
        ),
        examples=(
            RuleExample(
                example_id="exact-validation-status",
                title="Assert the intended validation response",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_route.py",
                        "def test_invalid_payload(client):\n"
                        "    response = client.post('/items', json={})\n"
                        "    assert response.status_code == 422\n"
                        "    assert response.json()['detail']\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_route.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="negative-only-server-status",
                title="Do not accept every non-server-error response",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_route.py",
                        "def test_invalid_payload(client):\n    response = client.post('/items', json={})\n    assert response.status_code != 500\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_route.py"),
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
        imports = ImportIndex.from_tree(tree)
        findings: list[Diagnostic] = []
        for test in _collected_tests(tree):
            findings.extend(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        "this assertion proves only that the response avoided a server-error outcome. Assert the "
                        "intended status and domain effect, or suppress SARJ408 with a reason when avoiding a server "
                        "exception is itself the regression, smoke, fuzz, or chaos contract."
                    ),
                )
                for node in _test_nodes(test)
                if isinstance(node, ast.Assert) and _negative_only(node.test, imports)
            )
        findings.sort(key=lambda finding: (finding.line, finding.col))
        return findings
