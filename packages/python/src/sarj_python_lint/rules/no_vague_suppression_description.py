from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from pathlib import Path


_DIRECTIVE_RE = re.compile(
    r"^(?:noqa\s*:\s*[A-Z0-9_, -]+|sarj-noqa\s*:\s*[A-Z0-9_, -]+|"
    r"type\s*:\s*ignore\s*\[[^\]]+\]|pyright\s*:\s*ignore\s*\[[^\]]+\])"
    r"\s*(?:—|--)\s*(?P<description>.+?)\s*$",
    re.IGNORECASE,
)
_VAGUE_RE = re.compile(
    r"^(?:needed|required|intentional(?:ly)?|ignore(?:d)?|false positive|type error|"
    r"python|mypy|pyright|ruff|to satisfy (?:the )?(?:linter|type checker|mypy|pyright|ruff))\.?$",
    re.IGNORECASE,
)


@final
class NoVagueSuppressionDescription(Rule):
    id = "no-vague-suppression-description"
    code = "SARJ419"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Suppression descriptions must name the concrete mismatch or safety invariant.",
        rationale="Generic reasons satisfy review conventions without making the suppressed risk auditable or removable.",
        remediation="Name the exact tool mismatch, external contract, or invariant that makes this suppression safe.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only scoped noqa, type-checker, and sarj-noqa directives with a present but closed generic reason are checked.",
            "Missing descriptions and descriptions containing concrete context are owned by their native tools or remain unchanged.",
        ),
        examples=(
            RuleExample(
                example_id="generic-suppression-reason",
                title="Generic reason does not make the suppression auditable",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "adapter.py", "value = vendor.value  # type: ignore[attr-defined] -- false positive\n"
                    ),
                ),
                focus_path=PurePosixPath("adapter.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concrete-suppression-reason",
                title="Concrete runtime mismatch explains the suppression",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "adapter.py",
                        "value = vendor.value  # type: ignore[attr-defined] -- vendor stubs omit the runtime field\n",
                    ),
                ),
                focus_path=PurePosixPath("adapter.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        return [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=self.description,
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
            for comment in comments
            if (match := _DIRECTIVE_RE.match(comment.body)) is not None
            and _VAGUE_RE.fullmatch(match["description"].strip()) is not None
        ]
