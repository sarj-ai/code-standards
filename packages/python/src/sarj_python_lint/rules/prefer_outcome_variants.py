from __future__ import annotations

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
from sarj_python_lint.rules._nullable_outcome import nullable_outcome_diagnostics
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferOutcomeVariants(Rule):
    id = "prefer-outcome-variants"
    code = "SARJ571"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Express nullable success and error state as tagged outcome variants.",
        rationale="An optional error beside success or payload state admits contradictory combinations. Tagged variants expose complete success payloads and explicit failure context to callers.",
        remediation="Reuse an established Result[T, E] or declare Success | Error variants with a shared Literal discriminator. Require success payloads and the error value in their respective variants; retain typed partial progress when failures need it. Preserve accepted inputs and serialized contracts during migration.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "A nullable error must be paired with a success Boolean, a finite success/error Literal tag, a nullable payload, or a Result/Outcome name plus other fields. Names alone never trigger this advisory.",
            "Recognizes direct import-proven Pydantic, dataclass, TypedDict, attrs and msgspec records, bounded Optional/Union/Annotated aliases and quoted annotations. Opaque ancestry and imported aliases are not guessed.",
            "Separate variants, independent last-error telemetry, scalar numeric uncertainty, mandatory error context, class metadata, tests and generated files are excluded. Exact-code suppressions are respected.",
            "Source-proven validator dependencies retain SARJ510 as their stronger owner when both rules are enabled. This warning does not change existing SARJ510 errors or automatically migrate constructors, persistence or partial progress.",
        ),
        examples=(
            RuleExample(
                example_id="nullable-outcome-record",
                title="A nullable error and success flag admit contradictory outcomes",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass AudioResult(BaseModel):\n    passed: bool = False\n    error: str | None = None\n    value: bytes | None = None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="separate-outcome-variants",
                title="Success and error variants have non-null payloads",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel\nclass RunSuccess(BaseModel):\n    passed: Literal[True] = True\n    value: bytes\nclass RunError(BaseModel):\n    passed: Literal[False] = False\n    error: str\ntype RunResult = RunSuccess | RunError\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path):
            return []
        return nullable_outcome_diagnostics(context, self.code)
