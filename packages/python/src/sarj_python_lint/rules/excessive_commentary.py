from __future__ import annotations

from pathlib import PurePosixPath
import re
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
)
from sarj_python_lint.rules._prose_budget import (
    groups,
    has_technical_anchor,
)


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LINES = 4
_MIN_WORDS = 28
_RATIONALE_RE = re.compile(
    r"\b(?:because|otherwise|therefore|must|never|cannot|can't|required?|invariant|"
    r"compatibility|security|race|atomic|deadlock|rollback|lock|data loss)\b",
    re.IGNORECASE,
)
_RATIONALE_SO_RE = re.compile(r"\bso\s+(?:that|a|an|the|this|it|we|they)\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )", re.MULTILINE)


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ434"
    documentation = RuleDocumentation(
        summary="Long standalone implementation commentary — make the code self-documenting and retain only durable constraints.",
        rationale=(
            "A paragraph that narrates nearby implementation behavior competes with the code and can drift independently "
            "from it."
        ),
        remediation=(
            "Delete the narration and clarify names, types, or structure. Keep concise comments that record a durable "
            "constraint or externally owned contract."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only contiguous standalone line-comment blocks with at least four non-empty lines and 28 words are inspected.",
            "Generated files, directives, licenses, structured lists, docstrings, inline comments, rationale markers, and concrete technical anchors are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="activation-narration",
                title="Implementation paragraph narrates a validation helper",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "# Everything standing between this integration and being usable.\n"
                        "# Returns all the reasons rather than the first failure.\n"
                        "# Someone activating a half-built integration wants the complete list.\n"
                        "# That avoids discovering one problem per round trip.\n"
                        "reasons = []\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="durable-constraint",
                title="A concrete compatibility constraint remains local",
                outcome=ExampleOutcome.NO_MATCH,
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
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for group in groups(path, source):
            lines = tuple(stripped for line in group.text.splitlines() if (stripped := line.strip()))
            if group.kind != "comment" or len(lines) < _MIN_LINES or len(group.text.split()) < _MIN_WORDS:
                continue
            if any(
                (
                    _BULLET_RE.search(group.text),
                    has_technical_anchor(group.text),
                    _RATIONALE_RE.search(group.text),
                    _RATIONALE_SO_RE.search(group.text),
                )
            ):
                continue
            findings.append(
                Diagnostic(
                    path,
                    group.line,
                    group.col,
                    self.code,
                    self.description,
                    column_encoding=group.column_encoding,
                )
            )
        return findings
