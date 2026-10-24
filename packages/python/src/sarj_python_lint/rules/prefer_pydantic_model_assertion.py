from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._declared_contracts import (
    MODEL_BASES,
    SETTINGS_BASES,
    DeclaredContracts,
    ordinary_pytest_test,
)
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._test_composition import direct_nodes


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MIN_FIELDS = 2
_MODEL = "from pydantic import BaseModel\nclass User(BaseModel):\n    id: int\n    name: str\n"


@final
class PreferPydanticModelAssertion(ProjectRule):
    id = "prefer-pydantic-model-assertion"
    code = "SARJ527"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Compare a Pydantic model or an explicit field projection instead of consecutive property assertions.",
        rationale="Consecutive assertions on the same model scatter one expected record across statements and obscure which fields form the test's contract.",
        remediation="Prefer 'assert result == ExpectedModel(...)' for the complete contract, or 'assert result.model_dump(include={...}) == {...}' for an intentional subset. Keep any needed None guard. Preserve identity, approximate comparisons, custom serialization and private-attribute semantics; do not fill irrelevant fields or use model_construct/model_copy to bypass validation.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only consecutive plain equality or bool/None identity assertions on two distinct declared fields of a source-proven Pydantic model are considered. Models are resolved through declared parameter/local/return annotations and simple construction/validation calls. Plain properties are deliberately excluded because model_dump omits them. Unknown receivers, non-model objects, calls in expected values, assertion messages, repeated fields, nested attributes and custom comparison operators are excluded. This is a review advisory, never an automatic rewrite or assertion deletion.",
        ),
        examples=(
            RuleExample(
                example_id="scattered-fields",
                title="Two assertions describe one expected model",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_user.py",
                        _MODEL
                        + "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_user.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-projection",
                title="One assertion states the selected field contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_user.py",
                        _MODEL
                        + "def test_user(result: User):\n    assert result.model_dump(include={'id', 'name'}) == {'id': 1, 'name': 'Alice'}\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_user.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or not is_test_path(context.path):
            return []
        contracts = DeclaredContracts(context)
        findings: list[Diagnostic] = []
        for function in collected_tests(context.tree.body):
            if not ordinary_pytest_test(function, context):
                continue
            for statements in _blocks(function):
                for run in _assertion_runs(statements, context):
                    _report(context, contracts, run, findings, self.code)
        return findings


def _assertion_runs(
    statements: list[ast.stmt], context: PythonFileContext
) -> Iterator[list[tuple[ast.Assert, ast.Attribute]]]:
    run: list[tuple[ast.Assert, ast.Attribute]] = []
    for statement in [*statements, ast.Pass()]:
        field = _asserted_field(statement, context)
        if field is None or (run and ast.dump(field.value) != ast.dump(run[0][1].value)):
            yield run
            run = []
        if field is not None and isinstance(statement, ast.Assert):
            run.append((statement, field))


def _blocks(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[list[ast.stmt]]:
    yield function.body
    for node in direct_nodes(function):
        match node:
            case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
                yield node.body
                yield node.orelse
            case ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
                yield node.body
            case ast.Try() | ast.TryStar():
                yield node.body
                yield node.orelse
                yield node.finalbody
            case _:
                continue


def _asserted_field(statement: ast.stmt, context: PythonFileContext) -> ast.Attribute | None:
    if not isinstance(statement, ast.Assert) or statement.msg is not None:
        return None
    comparison = statement.test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1:
        return None
    field, expected = comparison.left, comparison.comparators[0]
    if not isinstance(field, ast.Attribute) or not isinstance(field.value, ast.Name):
        return None
    operator = comparison.ops[0]
    if isinstance(operator, ast.Is):
        if not _boolean_or_none(expected, context):
            return None
    elif not isinstance(operator, ast.Eq) or not isinstance(expected, ast.Constant | ast.Name):
        return None
    return field


def _boolean_or_none(expected: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(expected, ast.Constant):
        return expected.value is None or isinstance(expected.value, bool)
    if isinstance(expected, ast.Name):
        binding = context.static_resource_provenance.binding(expected.id, expected)
        return (
            isinstance(binding, ast.arg)
            and isinstance(binding.annotation, ast.Name)
            and binding.annotation.id == "bool"
            and context.imports.builtin_is_unshadowed("bool")
        )
    return False


def _report(
    context: PythonFileContext,
    contracts: DeclaredContracts,
    run: list[tuple[ast.Assert, ast.Attribute]],
    findings: list[Diagnostic],
    code: str,
) -> None:
    fields = {field.attr for _, field in run}
    if len(fields) < _MIN_FIELDS or len(fields) != len(run):
        return
    model = contracts.value(run[0][1].value)
    if model is None or not contracts.inherits(model, MODEL_BASES | SETTINGS_BASES):
        return
    declared = {
        node.target.id
        for node in model.declaration.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    if not fields <= declared:
        return
    first = run[0][0]
    selected = ", ".join(repr(field) for field in sorted(fields))
    findings.append(
        Diagnostic(
            context.path,
            first.lineno,
            first.col_offset + 1,
            code,
            f"Compare one expected model, or use model_dump(include={{{selected}}}) for these selected fields; preserve any None guard and comparison semantics.",
            severity=Severity.WARNING,
        )
    )
