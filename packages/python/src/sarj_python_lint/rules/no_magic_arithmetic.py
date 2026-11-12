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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_TRIVIAL = frozenset({-2, -1, 0, 1, 2})
_TIMING_CALLS = frozenset(
    {
        "asyncio.sleep",
        "asyncio.timeout",
        "asyncio.timeout_at",
        "asyncio.wait_for",
        "time.sleep",
        "anyio.sleep",
        "trio.sleep",
    }
)
_FACTOR_OPERATIONS = (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.LShift, ast.RShift)


@final
class NoMagicArithmetic(Rule):
    id = "no-magic-arithmetic"
    code = "SARJ570"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Name nontrivial numeric factors and operational limits.",
        rationale="Unnamed conversion factors, frame sizes and timing limits hide units and can drift across related operations.",
        remediation="Extract a meaningfully named constant or use validated configuration. Reuse an existing constant when it represents the same unit or limit.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Complements Ruff PLR2004, which owns comparisons. Reviews nontrivial numeric literals in runtime multiply/divide/modulo/power/shift operations, slices, builtin range calls and import-proven sleep/timeout calls.",
            "Named uppercase constant definitions, function and field defaults, trivial -2 through 2, ordinary positional indexes, round precision, tests and generated sources are excluded. Floats other than the trivial values remain review candidates.",
            "The rule does not infer an intended constant name, replace mathematically meaningful parameters automatically, or claim a correctness defect. Open scientific formulas can retain a reasoned local exception.",
            "Numeric spelling is independently owned by numeric-literal-separators; arithmetic review never changes a value.",
        ),
        examples=(
            RuleExample(
                example_id="undeclared-domain",
                title="The contract is implicit",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", "def normalize(sample):\n    return sample / 32768\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-domain",
                title="The contract is explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "PCM16_SCALE = 32_768\ndef normalize(sample):\n    return sample / PCM16_SCALE\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        call_signal = any(symbol in context.symbol_source for symbol in ("range", "sleep", "timeout", "wait_for"))
        facts = AnnotationOrigins(context) if call_signal else None
        findings: list[Diagnostic] = []
        for node in context.nodes(ast.Constant):
            if type(node.value) not in {int, float} or node.value in _TRIVIAL:
                continue
            if not _runtime(node, context) or _named_constant(node, context):
                continue
            if not _operation_literal(node, context, facts) or context.suppressions.is_suppressed(
                node.lineno, self.code
            ):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    node.lineno,
                    node.col_offset + 1,
                    self.code,
                    "Name this numeric factor or operational limit with its meaning and units, or use validated configuration.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _operation_literal(node: ast.expr, context: PythonFileContext, facts: AnnotationOrigins | None) -> bool:
    parent = context.parents.get(node)
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.USub | ast.UAdd):
        parent = context.parents.get(parent)
    match parent:
        case ast.BinOp(op=operation) | ast.AugAssign(op=operation):
            return isinstance(operation, _FACTOR_OPERATIONS)
        case ast.Slice():
            return True
        case ast.Call(func=function) if facts is not None:
            return facts.builtin(function, "range", parent) or facts.qualified(function, parent) in _TIMING_CALLS
        case _:
            return False


def _runtime(node: ast.AST, context: PythonFileContext) -> bool:
    current = node
    while (parent := context.parents.get(current)) is not None:
        match parent:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return current in parent.body
            case ast.Lambda():
                return current is parent.body
            case _:
                pass
        current = parent
    return False


def _named_constant(node: ast.AST, context: PythonFileContext) -> bool:
    current = context.parents.get(node)
    while current is not None:
        match current:
            case ast.Assign(targets=targets):
                return all(isinstance(target, ast.Name) and target.id.isupper() for target in targets)
            case ast.AnnAssign(target=target):
                return isinstance(target, ast.Name) and target.id.isupper()
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Module():
                return False
            case _:
                pass
        current = context.parents.get(current)
    return False
