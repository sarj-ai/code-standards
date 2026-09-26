from __future__ import annotations

import ast
from collections import deque
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._ast_index import children


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sarj_python_lint._file_context import PythonFileContext


_ERROR_COMPLEXITY = 20
_MAX_CONTRIBUTORS = 3
type Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


class ComplexityPoint(NamedTuple):
    line: int
    amount: int
    construct: str


def function_complexity(function: Function) -> list[ComplexityPoint]:
    visitor = _Complexity()
    body = [function.body] if isinstance(function, ast.Lambda) else function.body
    visitor.visit_all(body, 0)
    visitor.run()
    return visitor.points


@final
class _Complexity:
    def __init__(self) -> None:
        self.points: list[ComplexityPoint] = []
        self._pending: deque[tuple[ast.AST, int]] = deque()

    def run(self) -> None:
        while self._pending:
            node, nesting = self._pending.popleft()
            self.scan(node, nesting)

    def add(self, node: ast.expr | ast.stmt | ast.ExceptHandler, nesting: int, construct: str) -> None:
        self.points.append(ComplexityPoint(node.lineno, nesting + 1, construct))

    def visit_all(self, items: Iterable[ast.AST], nesting: int) -> None:
        for item in items:
            self.visit(item, nesting)

    def visit(self, node: ast.AST, nesting: int) -> None:
        self._pending.append((node, nesting))

    def scan(self, node: ast.AST, nesting: int) -> None:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda() | ast.ClassDef():
                return
            case ast.If():
                self.visit_if(node, nesting)
            case ast.For() | ast.AsyncFor() | ast.While():
                self.add(node, nesting, "loop")
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    self.visit(node.target, nesting)
                self.visit(node.test if isinstance(node, ast.While) else node.iter, nesting)
                self.visit_all(node.body, nesting + 1)
                self.visit_else(node.orelse, nesting)
            case ast.IfExp():
                self.add(node, nesting, "conditional")
                self.visit(node.test, nesting)
                self.visit_all((node.body, node.orelse), nesting + 1)
            case ast.ExceptHandler():
                self.add(node, nesting, "except")
                if node.type is not None:
                    self.visit(node.type, nesting)
                self.visit_all(node.body, nesting + 1)
            case ast.Match():
                self.add(node, nesting, "match")
                self.visit(node.subject, nesting)
                for case in node.cases:
                    if case.guard is not None:
                        self.add(case.guard, nesting + 1, "case guard")
                        self.visit(case.guard, nesting + 1)
                    self.visit_all(case.body, nesting + 1)
            case ast.BoolOp():
                self.visit_boolean(node, nesting)
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                self.visit_comprehension(node, nesting)
            case ast.Try() | ast.TryStar():
                self.visit_all(node.body, nesting)
                self.visit_all(node.handlers, nesting)
                self.visit_else(node.orelse, nesting)
                self.visit_all(node.finalbody, nesting)
            case _:
                self.visit_all(children(node), nesting)

    def visit_if(self, node: ast.If, nesting: int) -> None:
        self.add(node, nesting, "if")
        while True:
            self.visit(node.test, nesting)
            self.visit_all(node.body, nesting + 1)
            match node.orelse:
                case [ast.If() as alternate] if alternate.col_offset == node.col_offset:
                    self.add(alternate, 0, "elif")
                    node = alternate
                case _:
                    self.visit_else(node.orelse, nesting)
                    return

    def visit_else(self, body: list[ast.stmt], nesting: int) -> None:
        if body:
            self.add(body[0], 0, "else")
            self.visit_all(body, nesting + 1)

    def visit_boolean(self, node: ast.BoolOp, nesting: int) -> None:
        previous: type[ast.boolop] | None = None

        def flatten(expression: ast.expr) -> None:
            nonlocal previous
            if not isinstance(expression, ast.BoolOp):
                self.visit(expression, nesting)
                return
            for index, value in enumerate(expression.values):
                if index:
                    operator = type(expression.op)
                    if operator is not previous:
                        self.add(expression, 0, "and" if operator is ast.And else "or")
                    previous = operator
                flatten(value)

        flatten(node)

    def visit_comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, nesting: int
    ) -> None:
        for generator in node.generators:
            self.visit(generator.target, nesting)
            self.visit(generator.iter, nesting)
            self.add(generator.target, nesting, "comprehension loop")
            nesting += 1
            for condition in generator.ifs:
                self.add(condition, nesting, "comprehension filter")
                self.visit(condition, nesting)
                nesting += 1
        values = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
        self.visit_all(values, nesting)


@final
class NoExcessiveCognitiveComplexity(Rule):
    id: str = "no-excessive-cognitive-complexity"
    code: str = "SARJ444"
    documentation = RuleDocumentation(
        summary=f"Error on cognitive complexity above {_ERROR_COMPLEXITY}; scores up to 20 pass.",
        rationale="Nested control flow increases the context a reader must retain while following a function.",
        remediation="Examples are fictional and written for this documentation; domain types are omitted. The library example replaces nested eligibility checks with early returns while preserving evaluation order. Refactor one function at a time, starting with its largest contributors. First simplify control flow and reduce nesting within the function. Extract a helper only when it clarifies a cohesive responsibility or enables meaningful reuse; do not split code solely to lower the score. Use lookup tables only for equivalent pure dispatch. Preserve APIs, side effects, evaluation order, and exception behavior. Run relevant tests before and after; remeasure the original and extracted functions. Do not hide branches in dense expressions or add indirection just to lower a score.",
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Sarj metric, not exact Sonar compatibility: functions and lambdas are independent; calls, recursion, function annotations, parameter defaults, and decorators are not scored.",
            "Conditions, loops, exception handlers, match statements, and conditional expressions add one plus nesting. Elif and else add one; their bodies add nesting. Each run of like boolean operators adds one.",
            "Comprehension loops and filters add one plus nesting. Match cases are free; case guards count as nested conditions. Try, finally, with, return, break, continue, and await add no points themselves.",
            "Generated code is excluded; authored tests and all function lengths are checked. The threshold is a shared policy constant, not a correctness boundary.",
        ),
        examples=(
            RuleExample(
                example_id="nested-decisions",
                title="Six nested decisions require a review",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "src/decision.py",
                        "def decide(a, b, c, d, e, f):\n    if a:\n        if b:\n            if c:\n                if d:\n                    if e:\n                        if f:\n                            act()\n",
                    ),
                ),
                focus_path=PurePosixPath("src/decision.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guard-decisions",
                title="Guard clauses reduce nesting",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "src/decision.py",
                        "def decide(a, b, c, d, e, f):\n    if not a:\n        return\n    if not b:\n        return\n    if not c:\n        return\n    if not d:\n        return\n    if not e:\n        return\n    if not f:\n        return\n    act()\n",
                    ),
                ),
                focus_path=PurePosixPath("src/decision.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="library-check-before",
                scenario="library-check",
                title="Synthetic library eligibility before: score 28",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "src/library.py",
                        "def can_borrow(member, book):\n    if member.active:\n        if member.email_verified:\n            if not member.suspended:\n                if member.balance == 0:\n                    if member.borrowed_count < 5:\n                        if book.available:\n                            if not book.reference_only:\n                                return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("src/library.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="library-check-after",
                scenario="library-check",
                title="Synthetic library eligibility after: score 7",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "src/library.py",
                        "def can_borrow(member, book):\n    if not member.active:\n        return False\n    if not member.email_verified:\n        return False\n    if member.suspended:\n        return False\n    if not (member.balance == 0):\n        return False\n    if not (member.borrowed_count < 5):\n        return False\n    if not book.available:\n        return False\n    if book.reference_only:\n        return False\n    return True\n",
                    ),
                ),
                focus_path=PurePosixPath("src/library.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated or context.tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda):
            points = function_complexity(function)
            score = sum(point.amount for point in points)
            if score <= _ERROR_COMPLEXITY:
                continue
            largest = sorted(points, key=lambda point: (-point.amount, point.line))[:_MAX_CONTRIBUTORS]
            detail = "; ".join(f"L{point.line} +{point.amount} {point.construct}" for point in largest)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=function.lineno,
                    col=function.col_offset + 1,
                    code=self.code,
                    message=f"Cognitive complexity {score} exceeds {_ERROR_COMPLEXITY}. Largest contributors: {detail}. Start with the largest contributors: simplify control flow and flatten nesting. Extract a helper only when it clarifies a cohesive responsibility or enables meaningful reuse, never solely to lower the score. Do not hide branches in dense expressions. Preserve behavior and public APIs, run relevant tests before and after, then remeasure.",
                    severity=Severity.ERROR,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))
