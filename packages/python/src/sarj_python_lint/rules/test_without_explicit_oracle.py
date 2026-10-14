from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._pytest import uses_benchmark_fixture
from sarj_python_lint.rules._test_assertions import names_verification, reads_as_verification


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_NON_UNIT_MARKS = frozenset({"benchmark", "lto", "lto_judge", "skip", "skipif", "xfail"})


@final
class NoExplicitTestOracle(Rule):
    id = "test-without-explicit-oracle"
    code = "SARJ495"
    enabled_by_default = False
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A collected test has no visible assertion or exception oracle.",
        rationale=(
            "A test can execute a side effect without observing whether the intended effect occurred. "
            "The absence of an explicit oracle is a review candidate, not proof that a smoke or no-throw contract is weak."
        ),
        remediation=(
            "Identify the intended contract. Reuse adequate existing coverage, observe the returned value, state, "
            "or emitted effect, or retain the test when successful execution is itself the contract. Do not add "
            "a tautological assertion or delete a test solely to silence this advisory."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This opt-in advisory is excluded from default Python checks; select it explicitly or use code-standards observe.",
            "Only default-collected test_* functions and methods of undecorated or pytest-marked, constructor-free, base-free Test* classes are inspected.",
            "Assertions, explicit raises, verification-named calls, import aliases, and local helpers containing or forwarding an oracle are accepted conservatively.",
            "Unknown decorators, test opt-outs, benchmark/LLM/skipped tests, and callable fixture parameters are left unreported; external helper behavior is not inferred.",
            "An intentional no-throw test may match. Findings describe syntax and require contract review; they never authorize automatic deletion or error-level promotion.",
        ),
        examples=(
            RuleExample(
                example_id="unobserved-effect",
                title="Observe whether the requested side effect occurred",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/test_delivery.py", "def test_delivery():\n    deliver('hello')\n"),),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="observed-effect",
                title="The assertion distinguishes a missing delivery",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_delivery.py",
                        "def test_delivery(sender):\n    deliver('hello', sender)\n    assert sender.messages == ['hello']\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if not is_test_path(context.path) or context.path.name == "conftest.py" or context.generated:
            return []
        tree = context.tree
        if tree is None or _opts_out(tree.body) or not _scope_marks(tree.body, context.imports):
            return []
        helpers = _oracle_helpers(tree, context.imports)
        return [
            Diagnostic(
                path=context.path,
                line=function.lineno,
                col=function.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"`{function.name}` has no visible assertion or exception oracle. Review the contract: "
                    "observe the outcome, reuse existing coverage, or retain an intentional smoke/no-throw test."
                ),
            )
            for function in _collected_tests(tree, context.imports)
            if not uses_benchmark_fixture(function)
            and not _has_oracle(function, helpers, context.imports)
            and not _calls_fixture(function)
        ]


def _scope_nodes(function: _Function) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _has_oracle(function: _Function, helpers: frozenset[str], imports: ImportIndex) -> bool:
    for node in _scope_nodes(function):
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(node, ast.Call):
            if names_verification(node.func, helpers):
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr in helpers:
                return True
            qualified = imports.resolved_qualified_name(node.func)
            if qualified is not None and reads_as_verification(qualified.rsplit(".", 1)[-1]):
                return True
    return False


def _oracle_helpers(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    helpers: frozenset[str] = frozenset()
    while True:
        updated = helpers | frozenset(
            function.name for function in functions if _has_oracle(function, helpers, imports)
        )
        if updated == helpers:
            return helpers
        helpers = updated


def _opts_out(statements: Sequence[ast.stmt]) -> bool:
    return any(
        isinstance(target, ast.Name)
        and target.id == "__test__"
        and (not isinstance(value, ast.Constant) or value.value is not True)
        for target, value in _assignments(statements)
    )


def _assignments(statements: Sequence[ast.stmt]) -> Iterator[tuple[ast.expr, ast.expr]]:
    for statement in statements:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                yield target, statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            yield statement.target, statement.value


def _scope_marks(statements: Sequence[ast.stmt], imports: ImportIndex) -> bool:
    for target, value in _assignments(statements):
        if isinstance(target, ast.Name) and target.id == "pytestmark":
            marks = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
            if not _safe_marks(marks, imports):
                return False
    return True


def _disabled_tests(statements: Sequence[ast.stmt]) -> frozenset[str]:
    return frozenset(
        ast.unparse(target.value)
        for target, value in _assignments(statements)
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "__test__"
            and (not isinstance(value, ast.Constant) or value.value is not True)
        )
    )


def _safe_marks(decorators: Sequence[ast.expr], imports: ImportIndex) -> bool:
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        qualified = imports.resolved_qualified_name(target)
        if qualified is None or not qualified.startswith("pytest.mark."):
            return False
        if qualified.rsplit(".", 1)[-1] in _NON_UNIT_MARKS:
            return False
    return True


def _collected_tests(tree: ast.Module, imports: ImportIndex) -> Iterator[_Function]:
    disabled = _disabled_tests(tree.body)
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _test_function(statement, disabled, imports):
                yield statement
        elif isinstance(statement, ast.ClassDef) and statement.name not in disabled and _test_class(statement, imports):
            yield from _class_tests(statement, disabled, imports)


def _class_tests(node: ast.ClassDef, disabled: frozenset[str], imports: ImportIndex) -> Iterator[_Function]:
    class_disabled = _disabled_tests(node.body) | frozenset(
        name.removeprefix(f"{node.name}.") for name in disabled if name.startswith(f"{node.name}.")
    )
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _test_function(
            child, class_disabled, imports
        ):
            yield child


def _test_function(node: _Function, disabled: frozenset[str], imports: ImportIndex) -> bool:
    return node.name.startswith("test_") and node.name not in disabled and _safe_marks(node.decorator_list, imports)


def _test_class(node: ast.ClassDef, imports: ImportIndex) -> bool:
    if not node.name.startswith("Test") or node.bases or node.keywords or _opts_out(node.body):
        return False
    if any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name in {"__init__", "__new__"}
        for child in node.body
    ):
        return False
    return _safe_marks(node.decorator_list, imports) and _scope_marks(node.body, imports)


def _calls_fixture(function: _Function) -> bool:
    parameters = {
        argument.arg for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    }
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in parameters
        for node in _scope_nodes(function)
    )
