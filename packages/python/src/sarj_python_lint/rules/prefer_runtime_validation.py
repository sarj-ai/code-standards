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
    is_suppressed,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext

_TYPE_GUARDS = frozenset({"typing.TypeGuard", "typing_extensions.TypeGuard"})
_BAD = "from typing import TypeGuard\ndef is_record(value: object) -> TypeGuard[dict[str, str]]:\n    return isinstance(value, dict)\n"
_GOOD = "from pydantic import BaseModel\nclass Record(BaseModel):\n    name: str\ndef parse_record(value: object) -> Record:\n    return Record.model_validate(value)\n"


@final
class PreferRuntimeValidation(Rule):
    id = "prefer-runtime-validation"
    code = "SARJ534"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer runtime validation to TypeGuard assertions.",
        rationale="TypeGuard tells the type checker to trust a predicate's claimed result; its annotation performs no runtime validation. Returning a validated domain value keeps the accepted schema and downstream contract together.",
        remediation="At data boundaries, validate into a named Pydantic model or TypeAdapter and return the validated value. For type dispatch, use actual isinstance checks or match class patterns. Do not replace TypeGuard with a cast or merely change its annotation to TypeIs. Explain indispensable low-level refinements with a local exact-code exception.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warns on import-proven typing/typing_extensions TypeGuard return annotations, including quoted annotations and stable module type aliases. This is an architecture preference even when a particular guard correctly validates its result.",
            "Shadowed or mutated imports, dynamic namespaces, wildcard imports, generated/vendor files and unresolved imported application aliases abstain. Boolean predicates and TypeIs are outside this policy; existing guard correctness rules still check unsafe narrowing.",
            "No automatic rewrite: validated values, boolean predicates and rejecting parsers have different APIs and error behavior. Runtime validation must actually inspect or construct the accepted value.",
        ),
        examples=(
            RuleExample(
                example_id="type-guard-assertion",
                title="A claimed narrowing is not a schema validator",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/records.py", _BAD),),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validated-result",
                title="Return a validated domain value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/records.py", _GOOD),),
                focus_path=PurePosixPath("app/records.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "TypeGuard" not in context.symbol_source or context.tree is None or context.generated:
            return []
        facts = AnnotationOrigins(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        return [
            Diagnostic(
                context.path,
                function.returns.lineno,
                function.returns.col_offset + 1,
                self.code,
                "Prefer returning a runtime-validated domain value over a TypeGuard assertion; the annotation itself does not validate data.",
                severity=Severity.WARNING,
            )
            for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
            if function.returns is not None
            and _type_guard(function.returns, facts, at=function.returns)
            and not is_suppressed(context.source_lines, function.returns.lineno, self.code)
        ]


def _type_guard(node: ast.expr, facts: AnnotationOrigins, *, at: ast.expr) -> bool:
    resolved = facts.resolve_annotation(node, at=at)
    if resolved is None:
        return False
    parsed = resolved.expression
    return isinstance(parsed, ast.Subscript) and facts.qualified(parsed.value, resolved.at) in _TYPE_GUARDS
