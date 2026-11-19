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
from sarj_python_lint.rules._comment_narration import CommentNarration
from sarj_python_lint.rules._prose_budget import groups, has_documentation_structure


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PARAGRAPH_CHARACTERS = 320
_LONG_PARAGRAPH = (
    "# Keep the previous snapshot available until its replacement has completed validation, because\n"
    "# another reader may still hold the shared version token while this operation builds its next\n"
    "# snapshot. Publish all replacement fields together and clear temporary resources only after\n"
    "# publication succeeds. If validation fails, preserve the previous snapshot for the next reader.\n"
    "snapshot = refresh_snapshot()\n"
)


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ434"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Remove proven duplicate narration; review implementation paragraphs above 320 characters.",
        rationale=(
            "A paragraph that repeats the same action names in the same order adds a second copy of the implementation. "
            "Comment length alone cannot distinguish noise from a necessary technical constraint."
        ),
        remediation=(
            "Delete the duplicate narration and keep the authored action names. Preserve constraints, references, "
            "uncertainty, ordering requirements and side-effect explanations that add meaning beyond those names."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes remove only a paragraph accepted by the shared ordered-narration proof: flat zero-argument direct calls, single-name call assignments and a terminal call return, or the exact initializer/accumulator-calls/return shape. Every line must repeat its corresponding action name; constraints, directives, qualifiers and extra statements remain protected. Each removed comment leaves its original blank line.",
            "Contiguous standalone implementation comment blocks with at least two non-empty lines and 12 words are inspected.",
            "An error requires each line to exactly repeat its corresponding direct zero-argument call identifier in the same order. Supported owners contain only those flat calls, single-name call assignments and call returns, or the exact accumulation shape.",
            "Guards, loops, branches, additional statements, intervening comments, arguments, qualified calls, quoted text, novel words and meaning-bearing qualifiers cause abstention. Arbitrary prose is not inferred to be redundant from its length.",
            "Standalone unstructured implementation comment paragraphs above 320 characters produce one manual warning. Length is a reviewed style budget, not proof of redundancy; preserve technical facts, references, uncertainty and ordering constraints while considering named phases or a shorter local explanation. No warning autofix is offered. Structured notes, examples, directives, licenses, docstrings, inline comments and generated files remain excluded. Existing exact-narration errors take precedence for the same block.",
            "Generated files, directives, licenses, docstrings, inline comments and short comments are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="oversized-implementation-paragraph",
                scenario="paragraph-budget",
                title="Review a long explanation without deleting its ordering constraint",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app.py", _LONG_PARAGRAPH),),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concise-ordering-constraint",
                scenario="paragraph-budget",
                title="Keep the concise reason beside the code",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "# Retain the previous snapshot until validation and publication succeed.\nsnapshot = refresh_snapshot()\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="activation-narration",
                title="A paragraph exactly repeats two flat action names",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def activate():\n"
                        "    # Load current account profile activation settings\n"
                        "    # Build current account profile activation response\n"
                        "    load_current_account_profile_activation_settings()\n"
                        "    return build_current_account_profile_activation_response()\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="activation-rationale",
                title="The original activation paragraph explains why all failures are returned",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def activation_reasons():\n"
                        "    # Everything standing between this integration and being usable.\n"
                        "    # Returns all the reasons rather than the first failure.\n"
                        "    # Someone activating a half-built integration wants the complete list.\n"
                        "    # That avoids discovering one problem per round trip.\n"
                        "    reasons = []\n"
                        "    reasons.extend(integration_reasons())\n"
                        "    reasons.extend(endpoint_reasons())\n"
                        "    return reasons\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="durable-constraint",
                title="A concrete compatibility constraint remains local",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="durable-constraint",
                files=(
                    ExampleFile.python(
                        "app.py",
                        "# Legacy clients send `execution_phase` until API-812 is retired.\n"
                        "# Keep the adapter at this boundary so internal models stay camelCase.\n"
                        'phase = payload["execution_phase"]\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="Exact authored words have a convergent comment fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def reasons():\n    # Collect active account profile activation rejection reasons\n    # Collect current endpoint profile activation rejection reasons\n    # Collect current integration profile activation rejection reasons\n    # Collect current action profile activation rejection reasons\n    values = []\n    values.extend(collect_active_account_profile_activation_rejection_reasons())\n    values.extend(collect_current_endpoint_profile_activation_rejection_reasons())\n    values.extend(collect_current_integration_profile_activation_rejection_reasons())\n    values.extend(collect_current_action_profile_activation_rejection_reasons())\n    return values\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def reasons():\n\n\n\n\n    values = []\n    values.extend(collect_active_account_profile_activation_rejection_reasons())\n    values.extend(collect_current_endpoint_profile_activation_rejection_reasons())\n    values.extend(collect_current_integration_profile_activation_rejection_reasons())\n    values.extend(collect_current_action_profile_activation_rejection_reasons())\n    return values\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        narration = CommentNarration(context)
        findings: list[Diagnostic] = []
        for group in groups(context.path, context.source, tree=context.tree):
            exact = narration.match(group) is not None
            paragraph = (
                group.kind == "comment"
                and len(group.text) > _PARAGRAPH_CHARACTERS
                and not has_documentation_structure(group.text)
                and not any(marker in group.text for marker in ("```", ">>>", "Examples:", "Example:"))
            )
            if not exact and not paragraph:
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    group.line,
                    group.col,
                    self.code,
                    "Delete comment paragraphs that exactly repeat the following ordered action names."
                    if exact
                    else f"Review this {len(group.text)}-character implementation paragraph (budget {_PARAGRAPH_CHARACTERS}). Prefer named phases or a concise local reason; preserve technical facts, references and ordering constraints. No automatic deletion is safe.",
                    severity=Severity.ERROR if exact else Severity.WARNING,
                    column_encoding=group.column_encoding,
                )
            )
        return findings
