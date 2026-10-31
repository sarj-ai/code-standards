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
from sarj_python_lint.rules._runtime_names import RuntimeNames


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class NoHasattr(Rule):
    id = "no-hasattr"
    code = "SARJ499"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not probe attributes with the builtin hasattr.",
        rationale=(
            "In strictly typed code, hasattr hides whether an attribute can be missing at all: it silences "
            "the type checker instead of fixing a loose type, so a renamed field quietly takes the fallback branch."
        ),
        remediation=(
            "Narrow the value with isinstance, a Protocol, or a typed wrapper around the untyped library; keep a "
            "reasoned SARJ suppression only for genuine runtime feature detection."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Unshadowed builtin references and simple builtins-module aliases are reported, including tests, module probes and dunder probes.",
            "Native Ruff B004 owns direct __call__ probes; TID251 owns qualified builtin access and imports. Required feature detection needs an explained local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="hasattr-probe",
                title="A hasattr probe hides a loose type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service/agent.py",
                        "def model_name(settings: object) -> str:\n"
                        "    return settings.model if hasattr(settings, 'model') else 'default'\n",
                    ),
                ),
                focus_path=PurePosixPath("service/agent.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-access",
                title="A typed parameter states which attributes exist",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service/agent.py",
                        "from dataclasses import dataclass\n\n@dataclass\nclass LLMSettings:\n    model: str\n\n"
                        "def model_name(settings: LLMSettings) -> str:\n    return settings.model\n",
                    ),
                ),
                focus_path=PurePosixPath("service/agent.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "hasattr" not in context.symbol_source or context.tree is None or context.generated:
            return []
        return [
            Diagnostic(
                context.path,
                reference.node.lineno,
                reference.node.col_offset + 1,
                self.code,
                "hasattr hides whether this attribute can be missing. Narrow the type with isinstance, a Protocol, "
                "or a typed wrapper instead.",
            )
            for reference in RuntimeNames(context).banned_references(frozenset({"hasattr"}))
        ]
