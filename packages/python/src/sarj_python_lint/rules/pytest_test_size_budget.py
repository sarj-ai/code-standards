from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
)
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._test_assertions import names_verification


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MAX_STATEMENTS = 15


@final
class PytestTestSizeBudget(Rule):
    id = "pytest-test-size-budget"
    code = "SARJ587"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary=f"Keep collected pytest tests within {_MAX_STATEMENTS} statements, without branches or verifying loops.",
        rationale=(
            "A test should read as one arrangement, one action and its observed outcome. Branches and loops make the "
            "test choose which statements run, so a case can silently assert nothing, and a long body usually checks "
            "several behaviors at once, so a failure no longer names the broken one (xUnit Test Patterns: Conditional "
            "Test Logic and Eager Test; Google's Software Engineering at Google: Don't Put Logic in Tests)."
        ),
        remediation=(
            "Split each branch or behavior into its own test, or use pytest.mark.parametrize for a table of inputs. "
            "Replace try/except with pytest.raises, collect values with a comprehension, and move repeated "
            "arrangement or polling into a fixture, factory or tested helper. Do not merge statements onto one line "
            "or hide them in an untested helper only to lower the count."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only default-collected test* functions and methods of Test* classes in test files are checked; fixtures, helpers and conftest.py are not.",
            "Statements are counted in the test's own scope, excluding a docstring; a nested function or class counts as one statement and its body is ignored. A long literal or call counts as one statement.",
            "if, match and try with except or else are reported once per test at the first occurrence.",
            "for, async for and while are reported only when they contain an assert, raise or verification-named call such as pytest.raises; loops that only seed or drive state still count toward the budget.",
            "try/finally cleanup, with blocks, comprehensions and conditional expressions are allowed.",
            "The budget is a review threshold, not a correctness boundary; integration and scenario tests may legitimately exceed it.",
        ),
        examples=(
            RuleExample(
                example_id="branching-on-a-parameter",
                title="Split or parametrize instead of branching",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_guard.py",
                        "import pytest\n\n\n"
                        "@pytest.mark.parametrize('allowed', [True, False])\n"
                        "def test_guard(allowed):\n"
                        "    if allowed:\n"
                        "        assert check('ok')\n"
                        "    else:\n"
                        "        with pytest.raises(ValueError):\n"
                        "            check('bad')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_guard.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="one-test-per-outcome",
                title="One straight-line test per outcome",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_guard.py",
                        "import pytest\n\n\n"
                        "def test_guard_accepts_ok():\n"
                        "    assert check('ok')\n\n\n"
                        "def test_guard_rejects_bad():\n"
                        "    with pytest.raises(ValueError):\n"
                        "        check('bad')\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_guard.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="over-budget",
                title="Split a test that checks several behaviors",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_cart.py",
                        "def test_cart():\n"
                        "    cart = Cart()\n"
                        + "".join(
                            f"    cart.add('item-{index}')\n    assert len(cart) == {index + 1}\n" for index in range(8)
                        ),
                    ),
                ),
                focus_path=PurePosixPath("tests/test_cart.py"),
                expected_count=1,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated or context.path.name == "conftest.py" or not is_test_path(context.path):
            return []
        diagnostics: list[Diagnostic] = []
        for test in collected_tests(tree.body):
            statements = list(_own_statements(_without_docstring(test.body)))
            if len(statements) > _MAX_STATEMENTS:
                diagnostics.append(
                    self._diagnostic(
                        context,
                        test,
                        f"`{test.name}` has {len(statements)} statements; collected tests allow at most "
                        f"{_MAX_STATEMENTS}. Split it by behavior or move shared arrangement into fixtures.",
                    )
                )
            branch = next((statement for statement in statements if _branches(statement)), None)
            if branch is not None:
                diagnostics.append(
                    self._diagnostic(
                        context,
                        branch,
                        f"`{test.name}` uses `{_keyword(branch)}`; split each branch into its own test, parametrize "
                        "the cases, or use pytest.raises or a comprehension.",
                    )
                )
        return diagnostics

    def _diagnostic(self, context: PythonFileContext, node: ast.stmt, message: str) -> Diagnostic:
        return Diagnostic(
            path=context.path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=self.code,
            severity=Severity.WARNING,
            message=message,
        )


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    match body:
        case [ast.Expr(value=ast.Constant(value=str())), *rest]:
            return rest
        case _:
            return body


def _own_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for statement in body:
        yield statement
        match statement:
            case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
                yield from _own_statements([*statement.body, *statement.orelse])
            case ast.With() | ast.AsyncWith():
                yield from _own_statements(statement.body)
            case ast.Try() | ast.TryStar():
                handlers = [nested for handler in statement.handlers for nested in handler.body]
                yield from _own_statements([*statement.body, *handlers, *statement.orelse, *statement.finalbody])
            case ast.Match():
                yield from _own_statements([nested for case in statement.cases for nested in case.body])
            case _:
                pass


def _branches(statement: ast.stmt) -> bool:
    match statement:
        case ast.If() | ast.Match():
            return True
        case ast.For() | ast.AsyncFor() | ast.While():
            return any(_verifies(node) for node in ast.walk(statement))
        case ast.Try() | ast.TryStar():
            return bool(statement.handlers or statement.orelse)
        case _:
            return False


def _verifies(node: ast.AST) -> bool:
    match node:
        case ast.Assert() | ast.Raise():
            return True
        case ast.Call(func=func):
            return names_verification(func)
        case _:
            return False


def _keyword(statement: ast.stmt) -> str:
    match statement:
        case ast.AsyncFor():
            return "async for"
        case ast.Try() | ast.TryStar():
            return "try/except"
        case _:
            return type(statement).__name__.lower()
