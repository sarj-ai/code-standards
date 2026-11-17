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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoNonlocalStatement(Rule):
    id = "no-nonlocal-statement"
    code = "SARJ578"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Reject `nonlocal` statements; pass state explicitly or give it a typed owner.",
        rationale=(
            "Rebinding an enclosing function's variables hides state changes across callable boundaries. "
            "An explicit return value or typed state owner makes that dependency visible."
        ),
        remediation=(
            "Return the updated value and assign it in the caller, or move callback state onto a typed owner. "
            "Do not just delete the declaration: that changes Python's name binding and can break the callable."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Every authored Python nonlocal statement is reported once, including read-only declarations and multiple names.",
            "Ruff PLW0602, PLW0603 and PLW0604 own the separate global-statement ban; this rule does not duplicate them.",
            "Comments, strings, generated and vendored sources are excluded. Malformed source is left to the syntax checker.",
            "There is no automatic fix because rewriting closure state requires a semantic change.",
        ),
        examples=(
            RuleExample(
                example_id="hidden-closure-rebinding",
                title="A callback rebinds its enclosing function's state",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/counter.py",
                        "def increment(value: int) -> int:\n"
                        "    def update() -> None:\n"
                        "        nonlocal value\n"
                        "        value += 1\n"
                        "    update()\n"
                        "    return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counter.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-state-return",
                title="The caller assigns an explicit return value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/counter.py",
                        "def increment(value: int) -> int:\n"
                        "    def update(current: int) -> int:\n"
                        "        return current + 1\n"
                        "    return update(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counter.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "nonlocal" not in context.source or context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message="`nonlocal` hides closure rebinding; return the updated value or use an explicit typed state owner.",
                severity=Severity.ERROR,
            )
            for node in context.nodes(ast.Nonlocal)
            if not context.suppressions.is_suppressed(node.lineno, self.code)
        ]
