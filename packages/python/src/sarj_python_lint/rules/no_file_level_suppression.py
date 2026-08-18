from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._suppression_comments import Comment, scan_comments_or_none


if TYPE_CHECKING:
    from pathlib import Path


# Match directive heads using each type checker's accepted spelling. Ruff's
# file-level blanket is already owned by PGH004.
_TYPE_IGNORE_RE = re.compile(r"^type:\s*ignore(?P<rest>.*)")
_PYRIGHT_IGNORE_RE = re.compile(r"^pyright:\s*ignore(?P<rest>.*)")

# Require a scoped rule list after directive heads that support one.
_BRACKET_CODES_RE = re.compile(r"^\s*\[\s*\w")

# `type: ignored` is a different word, not the directive.
_WORD_CONTINUATION_RE = re.compile(r"^\w")

_TYPE_IGNORE_MESSAGE = (
    "file-level `# type: ignore` silences every mypy error in this file, "
    "including ones added later — scope it (`# type: ignore[attr-defined]`) "
    "or fix the findings."
)
_PYRIGHT_IGNORE_MESSAGE = (
    "file-level `# pyright: ignore` silences every pyright diagnostic in this file, "
    "including ones added later — scope it (`# pyright: ignore[reportUnusedImport]`) "
    "or fix the findings."
)


class NoFileLevelSuppression(Rule):
    id: str = "no-file-level-suppression"
    code: str = "SARJ038"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Unscoped file-level type-checker suppressions hide every current and future diagnostic.",
        rationale="Mypy and Pyright blankets also hide diagnostics introduced by future tool upgrades.",
        remediation="Fix the findings or limit the directive to the specific diagnostic codes being suppressed.",
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Only mypy-compatible `type: ignore` and Pyright file-level directives are analyzed.",
            "Ruff's `# ruff: noqa` blanket is owned by Ruff PGH004.",
            "Trailing per-line suppressions and directives with an explicit code list are allowed.",
        ),
        examples=(
            RuleExample(
                example_id="unscoped-type-checker-suppression",
                title="Mypy disabled for the file",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("service.py", "# type: ignore\nimport os\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="scoped-type-checker-suppression",
                title="Mypy suppression names its code",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("service.py", "# type: ignore[import-not-found]\nimport os\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=message,
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
            for comment in comments
            if (message := _blanket_message(comment)) is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _blanket_message(comment: Comment) -> str | None:
    if not (comment.standalone and comment.before_first_statement):
        return None
    if _is_unscoped(comment.body, _TYPE_IGNORE_RE, _BRACKET_CODES_RE):
        return _TYPE_IGNORE_MESSAGE
    if _is_unscoped(comment.body, _PYRIGHT_IGNORE_RE, _BRACKET_CODES_RE):
        return _PYRIGHT_IGNORE_MESSAGE
    return None


def _is_unscoped(body: str, directive: re.Pattern[str], codes: re.Pattern[str]) -> bool:
    match = directive.match(body)
    if match is None:
        return False
    rest = match["rest"]
    if _WORD_CONTINUATION_RE.match(rest):
        return False
    return not codes.match(rest)
