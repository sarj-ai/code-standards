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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._comments import PositionedComment, comment_runs, has_legal_notice
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._suppression_comments import Comment


_DIRECTIVE = re.compile(
    r"^(?:!|.*?coding[:=]|(?:sarj-noqa|noqa|ruff|pyright|basedpyright|type|fmt|isort|pragma|"
    r"mypy|pylint|nosec|doctest|pytest|uv|region|endregion)\s*[:\[]|(?:fmt|isort):|%%)",
    re.IGNORECASE,
)


@final
class NoTestComments(Rule):
    id = "no-test-comments"
    code = "SARJ551"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Express test behavior in names and assertions instead of ordinary comments.",
        rationale="Test prose can drift from the setup and assertion it describes; executable contracts keep the explanation checked.",
        remediation="Remove the comment, clarify the test or helper name, or express the invariant with an assertion. Preserve legal notices and required tool directives.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks real comment tokens in recognized test and test-support paths, including inline comments; string contents and docstrings are outside this policy.",
            "Ambiguous test-like filenames require collected test declarations; test and test-support directories and conftest own their source independently of declarations.",
            "Generated files, malformed source, legal notices, shebangs, encoding declarations and tool directives are excluded. Existing comment rules retain their own diagnostic ownership.",
            "This is an explicitly requested style policy, released as a warning. No automatic deletion of potentially useful rationale is offered.",
        ),
        examples=(
            RuleExample(
                example_id="comment-narrates-test",
                title="Name the tested behavior",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_save.py",
                        "def test_save():\n    # A stale save is rejected.\n    assert save_is_rejected()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_save.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="behavior-in-test-name",
                title="The assertion documents the behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_save.py", "def test_stale_save_is_rejected():\n    assert save_is_rejected()\n"
                    ),
                ),
                focus_path=PurePosixPath("tests/test_save.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or not _test_comment_source(context):
            return []
        comments = scan_comments_or_none(context.source) or ()
        legal_lines = _legal_comment_lines(comments)
        return [
            Diagnostic(
                path=context.path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message="Move this test comment's meaning into a test name, helper or assertion.",
                severity=Severity.WARNING,
            )
            for comment in comments
            if comment.body.strip()
            and comment.line not in legal_lines
            and not _DIRECTIVE.search(comment.body)
            and not has_legal_notice(comment.body)
            and not is_suppressed(context.source_lines, comment.line, self.code)
        ]


def _test_comment_source(context: PythonFileContext) -> bool:
    directory = context.path.with_name("__init__.py")
    if context.path.name == "conftest.py" or is_test_path(directory) or is_test_support_path(directory):
        return True
    return context.tree is not None and is_test_path(context.path) and any(collected_tests(context.tree.body))


def _legal_comment_lines(comments: Sequence[Comment]) -> set[int]:
    standalone = [
        PositionedComment(comment.line, comment.col, comment.body) for comment in comments if comment.standalone
    ]
    protected: set[int] = set()
    for run in comment_runs(standalone):
        if any(has_legal_notice(body) for _, _, body in run):
            protected.update(line for line, _, _ in run)
    return protected
