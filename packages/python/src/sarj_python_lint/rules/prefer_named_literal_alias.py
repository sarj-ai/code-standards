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
from sarj_python_lint.rules._imports import TYPING_SOURCES


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


def _annotations(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        match node:
            case ast.AnnAssign(annotation=annotation):
                yield annotation
            case ast.arg(annotation=ast.expr() as annotation):
                yield annotation
            case ast.FunctionDef(returns=ast.expr() as returns) | ast.AsyncFunctionDef(returns=ast.expr() as returns):
                yield returns
            case _:
                pass


@final
class PreferNamedLiteralAlias(Rule):
    id = "prefer-named-literal-alias"
    code = "SARJ586"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Name multi-member Literal annotations with a reusable type alias.",
        rationale=(
            "An inline multi-member Literal is an anonymous domain. Each copy drifts independently, "
            "and readers cannot tell which annotations share one closed set of values."
        ),
        remediation=(
            'Declare `type Reason = Literal["a", "b"]` once and annotate with `Reason` everywhere the domain is used.'
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Parameter, return and variable annotations are checked; casts and other runtime expressions are not.",
            "A single-member Literal, such as a Pydantic discriminator tag, is accepted inline.",
        ),
        examples=(
            RuleExample(
                example_id="inline-literal-domain",
                title="A parameter repeats an anonymous Literal domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from typing import Literal\n\n\n"
                        "class FallbackError(RuntimeError):\n"
                        '    def __init__(self, reason: Literal["unavailable", "failed"]) -> None:\n'
                        "        super().__init__(reason)\n"
                        '        self.reason: Literal["unavailable", "failed"] = reason\n',
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="named-literal-domain",
                title="Annotations share one named Literal alias",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from typing import Literal\n\n"
                        'type FallbackReason = Literal["unavailable", "failed"]\n\n\n'
                        "class FallbackError(RuntimeError):\n"
                        "    def __init__(self, reason: FallbackReason) -> None:\n"
                        "        super().__init__(reason)\n"
                        "        self.reason: FallbackReason = reason\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "Literal" not in context.source or context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message="Name this Literal domain with a `type` alias and reuse it instead of inlining it.",
                severity=Severity.WARNING,
            )
            for annotation in _annotations(context.tree)
            for node in ast.walk(annotation)
            if isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Tuple)
            and len(node.slice.elts) > 1
            and context.module_imports.resolves(node.value, sources=TYPING_SOURCES, symbol="Literal")
            and not context.suppressions.is_suppressed(node.lineno, self.code)
        ]
