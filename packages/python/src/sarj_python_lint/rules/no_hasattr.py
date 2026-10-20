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
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


@final
class NoHasattr(Rule):
    id = "no-hasattr"
    code = "SARJ499"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Production code should not probe attributes with hasattr.",
        rationale=(
            "In a strictly typed application, hasattr hides whether an attribute can be missing at all: it silences "
            "the type checker instead of fixing a loose type, so a renamed field quietly takes the fallback branch."
        ),
        remediation=(
            "Narrow the value with isinstance, a Protocol, or a typed wrapper around the untyped library; keep a "
            "reasoned SARJ suppression only for genuine runtime feature detection."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct calls to the unshadowed builtin hasattr are reported; probes of an imported module and of dunder protocol attributes are accepted.",
            "Test modules and shared test support are excluded; runtime feature detection still needs a local suppression.",
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
        if is_test_path(context.path) or is_test_support_path(context.path):
            return []
        if not context.imports.builtin_is_unshadowed("hasattr"):
            return []
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "hasattr hides whether this attribute can be missing. Narrow the type with isinstance, a Protocol, "
                "or a typed wrapper instead.",
                severity=Severity.WARNING,
            )
            for node in context.nodes(ast.Call)
            if isinstance(node.func, ast.Name)
            and node.func.id == "hasattr"
            and not _is_feature_detection(node, context.imports)
        ]


def _is_feature_detection(call: ast.Call, imports: ImportIndex) -> bool:
    match call.args:
        case [target, name]:
            pass
        case _:
            return False
    if (
        isinstance(name, ast.Constant)
        and isinstance(name.value, str)
        and name.value.startswith("__")
        and name.value.endswith("__")
    ):
        return True
    root = target
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    binding = imports.bindings.get(root.id)
    return binding is not None and binding.symbol is None
