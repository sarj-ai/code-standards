from __future__ import annotations

from pathlib import PurePosixPath
import re
import tokenize
from typing import TYPE_CHECKING, ClassVar, override

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
    parse_or_none,
)
from sarj_python_lint.rules._comments import nested_comment_lines, standalone_comments
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# A bounded whole-body grammar: decoration and joins are ceremony only when
# every substantive token is itself a phase label.
_PHASE_WORD = r"(?:arrange|act|assert(?:ion)?s?|given|when|then)(?:\s+phase)?"
_PHASE_RE = re.compile(
    rf"^(?:\d+[.)]\s*)?[-=~*_#.\s]{{0,40}}(?:{_PHASE_WORD})"
    rf"(?:\s*(?:[/&+,|]|-|->|→|and)\s*(?:{_PHASE_WORD}))*"
    rf"[-=~*_#.\s:;!–—]{{0,40}}$",
    re.IGNORECASE,
)


class TestPhaseLabelComment(Rule):
    id: str = "no-bare-test-phase-comments"
    code: str = "SARJ089"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test files must not use bare phase comments such as Arrange, Act, Assert, Given, When, or Then.",
        rationale="Phase labels narrate test structure without explaining behavior and often indicate that a test needs clearer names or smaller units.",
        remediation="Delete the label; if the phases remain hard to follow, extract a named helper or split the test.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("test-phase-label-comment",),
        limitations=(
            "Standalone comments across recognized test and test-support files are checked, including fixtures, helpers, and module sections.",
            "Trailing comments and comments inside bracketed expressions are excluded.",
            "Comments containing words beyond the bounded phase-label grammar are preserved.",
        ),
        examples=(
            RuleExample(
                example_id="bare-test-phase-comments",
                title="Bare Arrange, Act, and Assert labels",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def test_widget():\n"
                        "    # Arrange\n"
                        "    widget = make_widget()\n"
                        "    # Act\n"
                        "    result = widget.run()\n"
                        "    # Assert\n"
                        "    assert result.ok\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=3,
                public=True,
            ),
            RuleExample(
                example_id="explanatory-comment",
                title="Comment explains a consequence",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def test_widget():\n"
                        "    # A stale token here would authorize the wrong tenant.\n"
                        "    assert request_is_rejected()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or not is_test_path(path) or parse_or_none(path, source) is None:
            return []
        try:
            standalone, _ = standalone_comments(source)
            nested = nested_comment_lines(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        return [
            Diagnostic(
                path=path,
                line=line,
                col=col + 1,
                code=self.code,
                message=(
                    f"Bare test phase comment {body.strip()!r} narrates structure; delete it or replace it "
                    "with non-obvious rationale."
                ),
                severity=Severity.WARNING,
                column_encoding=ColumnEncoding.CODEPOINTS,
            )
            for line, col, body in standalone
            if line not in nested and _PHASE_RE.match(body)
        ]
