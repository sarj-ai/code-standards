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
    Severity,
)
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._suppression_comments import Comment


_INLINE_DIRECTIVE = (
    r"(?:noqa\s*:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*|sarj-noqa\s*:\s*SARJ\d+(?:\s*,\s*SARJ\d+)*|"
    r"type\s*:\s*ignore\s*\[[^\]]+\]|(?:based)?pyright\s*:\s*ignore\s*\[[^\]]+\]|"
    r"ruff\s*:\s*ignore\s*\[[^\]]+\])"
)
_FILE_DIRECTIVE = (
    r"(?:ruff\s*:\s*(?:file-ignore\s*\[[^\]]+\]|noqa(?:\s*:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?)|"
    r"flake8\s*:\s*noqa(?:\s*:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?)"
)
_DIRECTIVE_START = rf"(?:{_INLINE_DIRECTIVE}|{_FILE_DIRECTIVE})"
_DIRECTIVE_RE = re.compile(
    rf"(?:^|#\s*)(?:(?P<inline>{_INLINE_DIRECTIVE})|(?P<file>{_FILE_DIRECTIVE}))"
    rf"(?P<description>.*?)(?=\s+#\s*{_DIRECTIVE_START}|\s*$)",
    re.IGNORECASE,
)
_VAGUE_RE = re.compile(
    r"^(?:(?:(?:because|just)\s+)?(?:needed|required|necessary|intentional(?:ly)?|ignore(?:d)?|"
    r"false[- ]positive|type error|typing issue|lint issue|known issue|expected|safe|harmless|todo|"
    r"upstream bug|tool limitation)(?:\s+(?:here|for now|workaround))?|"
    r"(?:temporary\s+)?workaround|by design|not an issue|fix later|same|n/?a|legacy|pre-existing,? out of scope|"
    r"(?:to satisfy|required by)\s+(?:the\s+)?(?:tool|linter|type checker|mypy|pyright|ruff)|"
    r"python|mypy|pyright|ruff)[.!?]?$",
    re.IGNORECASE,
)


@final
class NoVagueSuppressionDescription(Rule):
    id = "no-vague-suppression-description"
    code = "SARJ419"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Suppressions need a concrete description of the exception.",
        rationale="Generic reasons satisfy review conventions without making the suppressed risk auditable or removable.",
        remediation=(
            "Name the concrete tool mismatch or safety invariant and the condition that would allow removal. Cite an "
            "upstream issue or affected version when that is the durable boundary."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks missing descriptions and supported Python suppression descriptions that exactly match a bounded generic phrase. Multiple directives on one line may share its trailing boundary explanation.",
            "Blanket directives, formatter and coverage pragmas, Pylint directives, and whether a suppression is necessary remain outside this rule.",
            "Ordinary scoped directives must be attached to code; recognized Ruff and Flake8 file directives may stand alone.",
            "Generated-source markers do not waive this check. Generated/vendor boundaries belong in explicit whole-path exclusions.",
        ),
        examples=(
            RuleExample(
                example_id="generic-suppression-reason",
                title="Generic reason does not make the suppression auditable",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "adapter.py", "value = vendor.value  # ruff: ignore[attr-defined] -- false positive\n"
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
            RuleExample(
                example_id="missing-suppression-reason",
                scenario="missing-reason",
                title="A scoped suppression still needs an explanation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("adapter.py", "value = vendor.value # pyright: ignore[reportAny]\n"),),
                focus_path=PurePosixPath("adapter.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explained-suppression-reason",
                scenario="missing-reason",
                title="Explain the concrete dependency typing boundary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "adapter.py",
                        "value = vendor.value # pyright: ignore[reportAny] -- the dependency's runtime value has no published stub\n",
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        comments = scan_comments_or_none(source)
        if comments is None:
            return []
        diagnostics: list[Diagnostic] = []
        for comment in comments:
            vague_reason = _vague_reason(comment)
            if vague_reason is None:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=comment.line,
                    col=comment.col,
                    code=self.code,
                    message=(
                        f'Suppression reason "{vague_reason}" is generic; name the concrete mismatch or safety invariant.'
                        if vague_reason
                        else "Suppression has no explanation; name the concrete tool mismatch or safety invariant."
                    ),
                    severity=Severity.ERROR,
                    column_encoding=ColumnEncoding.CODEPOINTS,
                )
            )
        return diagnostics


def _vague_reason(comment: Comment) -> str | None:
    matches = tuple(_DIRECTIVE_RE.finditer(comment.body))
    scoped = [match for match in matches if not comment.standalone or match["file"] is not None]
    for match in scoped:
        reason = re.sub(r"^(?:--|—|–|-)\s*", "", match["description"].strip())
        if (not comment.standalone or match["file"] is not None) and _VAGUE_RE.fullmatch(reason) is not None:
            return reason
    if scoped and not any(re.sub(r"^(?:--|—|–|-)\s*", "", match["description"].strip()) for match in scoped):
        return ""
    return None
