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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class DiscourageNullableConstructorParameters(Rule):
    id = "discourage-nullable-constructor-parameters"
    code = "SARJ468"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Avoid nullable constructor parameters when a non-nullable interface can express the choice.",
        rationale=(
            "Nullable constructor parameters allow partially configured objects and force callers and implementations "
            "to handle an absent value. Required nullable parameters still permit this state."
        ),
        remediation="Prefer a non-nullable dependency or a separate constructor for the absent case; suppress deliberate nullable values with a reason.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only explicitly annotated `__init__` parameters using PEP 604 unions containing None are checked.",
            "Tests and generated files are excluded; genuinely absent domain values may justify a suppression.",
        ),
        examples=(
            RuleExample(
                example_id="nullable-dependency",
                title="Constructor permits a missing dependency",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, store: Store | None = None) -> None:\n"
                        "        self.store = store\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="non-nullable-dependency",
                title="Constructor requires a usable dependency",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, store: Store) -> None:\n        self.store = store\n",
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
        if context.generated or context.tree is None or is_test_path(context.path):
            return []
        findings: list[Diagnostic] = []
        for node in ast.walk(context.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) or method.name != "__init__":
                    continue
                positional = method.args.posonlyargs + method.args.args
                for parameter in (*positional, *method.args.kwonlyargs):
                    self._append_if_nullable(context, parameter, findings)
        return findings

    def _append_if_nullable(
        self,
        context: PythonFileContext,
        parameter: ast.arg,
        findings: list[Diagnostic],
    ) -> None:
        if parameter.annotation is None or not _is_nullable_union(parameter.annotation):
            return
        findings.append(
            Diagnostic(
                path=context.path,
                line=parameter.lineno,
                col=parameter.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=f"Constructor parameter `{parameter.arg}` accepts None; prefer a non-nullable interface.",
            )
        )


def _is_nullable_union(annotation: ast.expr) -> bool:
    if not isinstance(annotation, ast.BinOp) or not isinstance(annotation.op, ast.BitOr):
        return False
    return _is_none_union_member(annotation.left) or _is_none_union_member(annotation.right)


def _is_none_union_member(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_none_union_member(annotation.left) or _is_none_union_member(annotation.right)
    return isinstance(annotation, ast.Constant) and annotation.value is None
