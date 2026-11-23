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
from sarj_python_lint.rules._comments import comment_line_numbers
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import none_guard_candidates


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferWalrusNoneGuard(Rule):
    id = "prefer-walrus-none-guard"
    code = "SARJ589"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Bind a compact synchronous lookup in its immediately following terminal None guard.",
        rationale=(
            "A temporary assigned on one line and tested for None on the next splits one decision across two "
            "statements. Binding it in the guard keeps the lookup, the branch and the name together, exactly as "
            "SARJ432 already requires for awaited lookups."
        ),
        remediation=(
            "Rewrite `value = lookup(); if value is None: return` as `if (value := lookup()) is None: return`. "
            "Keep `is not None` when the terminal branch consumes the bound value. Keep two statements when the "
            "assignment is an intentional debugging or tracing boundary."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Only a one-line call assigned to a single name and followed immediately by an exact `is None` or `is not None` guard ending in return or raise is checked; truthiness guards are excluded.",
            "Statements before the terminal operation must be simple assignments. An `is None` guard requires a later use on the surviving path and no use inside the guard; an `is not None` guard must consume the binding and leave no later use before rebinding.",
            "Awaited lookups belong to SARJ432 and regex `search`/`match`/`fullmatch` lookups to SARJ081, so neither is reported twice. Comments in the span, else branches, ambiguous name flow, conditions over 120 columns, generated files and stub files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="split-optional-lookup",
                title="A synchronous lookup is split from its absence guard",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    found = labels.get(key)\n"
                        "    if found is None:\n"
                        "        return 'unknown'\n"
                        "    return found.title()\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    if (found := labels.get(key)) is None:\n"
                        "        return 'unknown'\n"
                        "    return found.title()\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guard-bound-lookup",
                title="The lookup is bound in its absence guard",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    if (found := labels.get(key)) is None:\n"
                        "        return 'unknown'\n"
                        "    return found.title()\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if path.suffix == ".pyi" or context.generated or context.tree is None:
            return []
        if any(token not in source for token in ("None", "if", "=")):
            return []
        diagnostics = [
            Diagnostic(
                path=path,
                line=candidate.assignment.lineno,
                col=candidate.assignment.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"`{candidate.name}` only separates a lookup from its terminal None guard; "
                    f"bind it as `{candidate.binding}`"
                ),
            )
            for candidate in none_guard_candidates(context, self.code, comment_line_numbers(source), awaited=False)
        ]
        if diagnostics and context.session.python_target.has_declared_support_before(path, (3, 8)):
            return []
        return sorted(diagnostics, key=lambda item: (item.line, item.col))
