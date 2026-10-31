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


_BANNED_NAMES = frozenset(
    {"locals", "globals", "compile", "__import__", "delattr", "getattr", "exec", "eval", "breakpoint"}
)


@final
class NoDynamicBuiltins(Rule):
    id = "no-dynamic-builtins"
    code = "SARJ557"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Use explicit typed state instead of dynamic Python builtin access.",
        rationale=(
            "Dynamic namespace inspection, source compilation, and string-based attribute access hide dependencies "
            "from type checking and refactoring. The strict policy also rejects executor/debugger references that "
            "can otherwise escape their native call checks through an alias."
        ),
        remediation=(
            "Pass typed state explicitly, use explicit imports and declared attributes, and keep source as data. "
            "A required compiler or plugin boundary needs a local, explained suppression."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Ruff S307, S102, T100, B009, B043 and qualified/imported banned-api checks retain their native owners; this rule closes bare-name and simple module-alias gaps.",
            "Locally shadowed names and unrelated methods are accepted. Arbitrary dictionary/reflection lookups and complex rebinding are not reconstructed.",
        ),
        examples=(
            RuleExample(
                example_id="dynamic-field",
                title="A string field name hides the object contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service/reader.py", "def read(value, field):\n    return getattr(value, field, None)\n"
                    ),
                ),
                focus_path=PurePosixPath("service/reader.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-field",
                title="A declared field makes the contract explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service/reader.py",
                        "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass User:\n    name: str\n\ndef read(value: User) -> str:\n    return value.name\n",
                    ),
                ),
                focus_path=PurePosixPath("service/reader.py"),
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
            or not any(name in context.symbol_source for name in _BANNED_NAMES)
        ):
            return []
        return [
            Diagnostic(
                context.path,
                reference.node.lineno,
                reference.node.col_offset + 1,
                self.code,
                f"Do not use the builtin {reference.name}. Use explicit typed state, normal imports, or declared attribute access; a required runtime boundary needs an explained local suppression.",
            )
            for reference in RuntimeNames(context).banned_references(_BANNED_NAMES)
        ]
