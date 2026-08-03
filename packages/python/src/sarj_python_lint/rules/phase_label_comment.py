"""SARJ089 — A bare Arrange/Act/Assert (or Given/When/Then) phase label in a test

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_phase_label_comment.py
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._comments import nested_comment_lines, standalone_comments
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# The phase vocabulary, as a whole-body match.
_PHASE_RE = re.compile(
    r"^(?:arrange|act|assert(?:ion)?s?|given|when|then|exercise|execute|verif(?:y|ication)|"
    r"cleanup|prepare|sanity(?:\s+check)?|arrange\s*[/&+]\s*act|act\s*[/&+]\s*assert|"
    r"given\s*[/&+]\s*when|when\s*[/&+]\s*then)"
    r"\s*[.:;!\-–—]*\s*$",
    re.IGNORECASE,
)


class TestPhaseLabelComment(Rule):
    id: str = "test-phase-label-comment"
    code: str = "SARJ089"
    description: str = (
        "Bare test-phase label — delete it; a test whose phases need signposting "
        "wants a named helper or a smaller test, not a comment."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or not is_test_path(path):
            return []
        try:
            standalone, _ = standalone_comments(source)
            nested = nested_comment_lines(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        return [
            Diagnostic(path=path, line=line, col=col + 1, code=self.code, message=self.description)
            for line, col, body in standalone
            if line not in nested and _PHASE_RE.match(body)
        ]
