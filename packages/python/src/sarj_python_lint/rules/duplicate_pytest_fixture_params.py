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
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_declarations


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import FixtureDeclaration


_BAD = 'import pytest\n\n@pytest.fixture(params=("empty", "empty"))\ndef payload(request):\n    return request.param\n'


@final
class DuplicatePytestFixtureParams(Rule):
    id: str = "duplicate-pytest-fixture-params"
    code: str = "SARJ524"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Review repeated immutable values in a pytest fixture parameter list.",
        rationale=(
            "Each fixture parameter reruns its dependent tests. Repeating the same immutable literal can add "
            "execution time without exercising a distinct input; Ruff PT014 covers test parametrization, not fixture params."
        ),
        remediation=(
            "Review the dependent test contracts, then remove an accidental duplicate. Preserve intentional repetition "
            "with explicit case IDs or an exact SARJ524 suppression explaining the repeated-run contract."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only directly imported pytest/pytest-asyncio fixtures in test paths with one decorator and literal list/tuple params are analyzed.",
            "Compares immutable scalar/tuple literals with type and floating-point sign preserved; mutable values, calls, aliases and pytest.param metadata are not compared.",
            "Explicit IDs, decorator unpacking and fixtures using request beyond direct request.param loads are excluded.",
            "Dependent fixtures, hooks and tests may observe case indices, generated IDs or repeated execution; findings require contract review and are never auto-deleted.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-fixture-input",
                title="The same input schedules the dependent tests twice",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", _BAD),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="distinct-fixture-inputs",
                title="Each fixture parameter represents a distinct input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/conftest.py", _BAD.replace('"empty", "empty"', '"empty", "filled"')),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            not is_test_path(context.path)
            or context.generated
            or "params" not in context.symbol_source
            or context.tree is None
        ):
            return []
        findings: list[Diagnostic] = []
        for fixture in fixture_declarations(context.tree):
            params = _parameter_values(fixture, context)
            if params is None:
                continue
            first_values: dict[str, ast.expr] = {}
            for value in params.elts:
                key = _literal_key(value)
                if key is None:
                    continue
                first = first_values.setdefault(key, value)
                if first is value or is_suppressed(context.source_lines, value.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=value.lineno,
                        col=value.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"fixture `{fixture.name}` repeats the immutable parameter from line {first.lineno}; "
                            "review dependent contracts before removing it, or give intentional repetition explicit IDs"
                        ),
                    )
                )
        return findings


def _parameter_values(fixture: FixtureDeclaration, context: PythonFileContext) -> ast.List | ast.Tuple | None:
    decorator = fixture.decorator
    if (
        len(fixture.node.decorator_list) != 1
        or not isinstance(decorator, ast.Call)
        or decorator.args
        or any(keyword.arg is None for keyword in decorator.keywords)
        or _observes_request_identity(fixture.node, context)
    ):
        return None
    keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
    if len(keywords) != len(decorator.keywords):
        return None
    ids = keywords.get("ids")
    if ids is not None and not (isinstance(ids, ast.Constant) and ids.value is None):
        return None
    params = keywords.get("params")
    return params if isinstance(params, ast.List | ast.Tuple) else None


def _literal_key(value: ast.expr) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str | bytes | bool | int | float | type(None)):
        return _scalar_key(value=value.value)
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, ast.UAdd | ast.USub)
        and isinstance(value.operand, ast.Constant)
        and isinstance(value.operand.value, int | float)
        and not isinstance(value.operand.value, bool)
    ):
        number = value.operand.value
        number = -number if isinstance(value.op, ast.USub) else +number
        return _scalar_key(value=number)
    if isinstance(value, ast.Tuple):
        keys = tuple(_literal_key(item) for item in value.elts)
        if all(key is not None for key in keys):
            return "tuple:" + "".join(f"{len(key)}:{key}" for key in keys if key is not None)
    return None


def _scalar_key(*, value: str | bytes | float | None) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f"int:{value:x}"
    return f"{type(value).__name__}:{value!r}"


def _observes_request_identity(node: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    for child in walk_ast(node):
        if isinstance(child, ast.Name) and child.id == "request":
            parent = context.parents.get(child)
            if not (
                isinstance(child.ctx, ast.Load)
                and isinstance(parent, ast.Attribute)
                and parent.value is child
                and parent.attr == "param"
                and isinstance(parent.ctx, ast.Load)
            ):
                return True
    return False
