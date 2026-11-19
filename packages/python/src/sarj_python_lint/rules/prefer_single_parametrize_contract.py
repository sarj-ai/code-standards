from __future__ import annotations

import ast
from math import prod
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
from sarj_python_lint.rules._local_source import unshadowed_import_namespace
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pytest import collected_tests


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MIN_AXES = 2
_DECORATOR_ARGUMENTS = 2
_MAX_AXES = 8
_MAX_CASES = 256
_MAX_VALUES = 32
_BAD = "import pytest\n@pytest.mark.parametrize('mode', ['a', 'b'])\n@pytest.mark.parametrize('kind', [1, 2])\ndef test_value(kind, mode):\n    assert kind in (1, 2) and mode in ('a', 'b')\n"
_GOOD = "import pytest\nfrom itertools import product\n@pytest.mark.parametrize(('kind', 'mode'), list(product([1, 2], ['a', 'b'])))\ndef test_value(kind, mode):\n    assert kind in (1, 2) and mode in ('a', 'b')\n"


@final
class PreferSingleParametrizeContract(Rule):
    id = "prefer-single-parametrize-contract"
    code = "SARJ583"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer one explicit pytest parameter contract; preserve Cartesian products compactly.",
        rationale="Stacked static axes scatter the test input contract across decorators. One named contract can keep their Cartesian product compact without repeating literal rows.",
        remediation="Use one tuple of argument names and list(itertools.product(...)) for independent static axes. Retain pytest's innermost-to-outermost axis order and verify collected IDs, case count and behavior. Do not expand the product into a repetitive literal table.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warns once on a collected test with two through eight import-proven pytest.mark.parametrize decorators, two positional arguments each, one unique literal argument name per axis and nonempty literal list/tuple values. Products above 256 cases or axes above 32 values abstain. This explicit style preference does not claim a test defect or propose fewer cases.",
            "Single decorators, pytest.param, IDs, marks, indirect/scope options, dynamic values, additional decorators, visible generation hooks, shadowed or patched pytest imports, generated files and unsupported/malformed forms abstain. Repository-specific collection plugins still require review; source-local analysis cannot certify their absence. No automatic fix changes collection or mark semantics.",
            "Existing upstream pytest-style rules own argument-name/value formatting. This rule only addresses a complete static stack, keeps Cartesian coverage and deliberately allows compact products; it does not revive the retired literal-table detector.",
        ),
        examples=(
            RuleExample(
                example_id="rejects-antipattern",
                title="Reject the anti-pattern",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/test_value.py", _BAD),),
                focus_path=PurePosixPath("tests/test_value.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="accepts-alternative",
                title="Accept the preferred alternative",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/test_value.py", _GOOD),),
                focus_path=PurePosixPath("tests/test_value.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or not is_test_path(context.path)
            or "parametrize" not in context.symbol_source
        ):
            return []
        functions = [function for function in collected_tests(context.tree.body) if _static_stack(function)]
        if not functions:
            return []
        if (
            context.has_wildcard_import
            or context.dynamic_namespace
            or context.resource_provenance.mock_namespace_patching
        ):
            return []
        if any(node.name == "pytest_generate_tests" for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        if not unshadowed_import_namespace(context.path, "pytest", facts=context.session.first_party):
            return []
        return [
            Diagnostic(
                context.path,
                function.decorator_list[0].lineno,
                function.decorator_list[0].col_offset + 1,
                self.code,
                self.description
                + " Use list(itertools.product(...)) in innermost-first axis order; preserve collected IDs, marks and every case.",
                severity=Severity.WARNING,
            )
            for function in functions
            if _pytest_stack(function, context)
            and not context.suppressions.is_suppressed(function.decorator_list[0].lineno, self.code)
        ]


def _static_stack(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if not _MIN_AXES <= len(function.decorator_list) <= _MAX_AXES:
        return False
    counts: list[int] = []
    names: set[str] = set()
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or len(decorator.args) != _DECORATOR_ARGUMENTS or decorator.keywords:
            return False
        axis_names = _names(decorator.args[0])
        values = decorator.args[1]
        if len(axis_names) != 1 or names.intersection(axis_names) or not isinstance(values, ast.List | ast.Tuple):
            return False
        if not 1 <= len(values.elts) <= _MAX_VALUES or not all(_literal(value) for value in values.elts):
            return False
        names.update(axis_names)
        counts.append(len(values.elts))
    return prod(counts) <= _MAX_CASES


def _pytest_stack(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    return all(
        isinstance(decorator, ast.Call)
        and context.resource_provenance.runtime_import_name(decorator.func) == "pytest.mark.parametrize"
        for decorator in function.decorator_list
    )


def _names(value: ast.expr) -> tuple[str, ...]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        names = tuple(item.strip() for item in value.value.split(","))
    elif isinstance(value, ast.List | ast.Tuple) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
    ):
        names = tuple(
            item.value for item in value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    else:
        return ()
    return names if all(name.isidentifier() for name in names) and len(set(names)) == len(names) else ()


def _literal(value: ast.expr, depth: int = 0) -> bool:
    if depth >= _MAX_AXES:
        return False
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str | int | float | bool | bytes | type(None))
    return isinstance(value, ast.Tuple | ast.List) and all(_literal(item, depth + 1) for item in value.elts)
