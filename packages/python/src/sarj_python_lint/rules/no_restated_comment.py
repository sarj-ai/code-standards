"""SARJ049 — A one-line comment that only re-spells the statement beneath it.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_restated_comment.py
"""

from __future__ import annotations

import ast
import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._comments import (
    code_tokens,
    comment_runs,
    content_tokens,
    is_protected,
    nested_comment_lines,
    restates,
    standalone_comments,
    statement_comment_walls,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MAX_WORDS = 8
_MAX_ASCII = 127
# A single content word labels a statement rather than restating it.
_MIN_CONTENT_TOKENS = 2

# Three same-indent lines form a labelled region; two remain eligible because
# they commonly represent an action followed by its assertion.
_SECTION_REGION_LINES = 3

# Directive comments, in the broad spelling — this rule sees Python only, but the
# list is kept in step with the TypeScript twin so the two cannot drift.
_DIRECTIVE_RE = re.compile(
    r"^\s*(?:todo|fixme|hack\b|xxx|note:|nb:|warning:|important:|"
    r"noqa|sarj-noqa|type:|pragma|pyright|mypy|fmt:|isort|ruff|pylint|flake8|nosec|nosemgrep|"
    r"-\*-|!/|coding[:=])",
    re.IGNORECASE,
)

# Commented-out code and section banners belong to SARJ016.
_CODEY_RE = re.compile(r"^[\w.\[\]'\"]+\s*[:=]\s*\S|^[\w.]+\(")
_CODE_KEYWORD_RE = re.compile(r"^(?:assert|return|raise|await|yield|del|import|from|print|global|nonlocal)\b")
_CODE_SIGNAL_RE = re.compile(r"[=()\[\]{}]")
_BANNERISH_RE = re.compile(r"[=\-─-╿*#~_.]{3,}|^[A-Z0-9 _:-]+$")

# Modality, lead-ins, emphasis, and negation add meaning identifiers cannot.
_MODALITY_RE = re.compile(r"\b(?:can|could|should|shall|may|might|must|will|would|cannot)\b", re.IGNORECASE)
_LEAD_IN_RE = re.compile(r":$")
_EMPHASIS_RE = re.compile(r"\*\w[^*]*\*|`[^`]+`")
_NEGATION_WORD_RE = re.compile(r"\b(?:no|not|never|neither|nor|without|none|non)\b", re.IGNORECASE)

# A positive comment can usefully translate negatively expressed code.
_CODE_NEGATION_RE = re.compile(r"\bnot\b|!=|\bis None\b|\.empty\(|assert(?:Not|False)")

# A statement whose head a comment could be restating.
_SIMPLE_STMT_RE = re.compile(
    r"^\s*(?:return\b|yield\b|raise\b|await |del |assert |"
    r"[\w.\[\]\"'()]+\s*(?:[:+\-*/|&]?=)\s*\S|[\w.]+\(|await\s+[\w.]+\()"
)
# Plain data declarations are labels; eligible statements perform an action.
_ACTION_STMT_RE = re.compile(r"[\w.\]\)]\s*\(|^\s*(?:return|raise|yield|await|del)\b")

# Anything whose *body* the comment could be labelling instead.
_BLOCK_OPENER_RE = re.compile(
    r"^\s*(?:def |class |async def|if |elif |else\s*:|for |while |with |try\s*:|except|finally\s*:|match |case |@)"
)

# Statement "shapes" used only to spot a group label: a comment whose statement
# is followed by a same-indent sibling of the same shape heads a run.
_IMPORT_SHAPE_RE = re.compile(r"^\s*(?:import\b|from\b)")
_KV_SHAPE_RE = re.compile(r"""^\s*["'][^"']+["']\s*:""")
_ASSIGN_SHAPE_RE = re.compile(r"^\s*[\w.\[\]]+\s*(?::[^=]+)?=[^=]|^\s*[\w.\[\]]+\s*:\s*\S+,?\s*$")
_ELEMENT_SHAPE_RE = re.compile(r"""^\s*["'\[{(].*,?\s*$|^\s*[\w.'"]+,\s*$""")
# Calls and assertions can form labelled sibling groups too.
_CALL_SHAPE_RE = re.compile(r"^\s*(?:await\s+)?[\w.]+\s*\(")
_ASSERT_SHAPE_RE = re.compile(r"^\s*assert\b")


def _statement_shape(line: str) -> str | None:
    if _IMPORT_SHAPE_RE.match(line):
        return "import"
    if _KV_SHAPE_RE.match(line):
        return "kv"
    if _ASSIGN_SHAPE_RE.match(line):
        return "assign"
    if _ASSERT_SHAPE_RE.match(line):
        return "assert"
    if _CALL_SHAPE_RE.match(line):
        return "call"
    if _ELEMENT_SHAPE_RE.match(line):
        return "element"
    return None


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _statement_end(lines: list[str], index: int) -> int:
    """Return the final line of a statement using bracket balance."""
    balance = 0
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        balance += line.count("(") + line.count("[") + line.count("{")
        balance -= line.count(")") + line.count("]") + line.count("}")
        if balance <= 0:
            break
        cursor += 1
    return cursor


def _is_group_label(lines: list[str], index: int) -> bool:
    """Report whether the statement at `index` is the head of a run of siblings."""
    first = lines[index]
    shape = _statement_shape(first)
    if shape is None:
        return False
    following = _statement_end(lines, index) + 1
    if following >= len(lines):
        return False
    nxt = lines[following]
    if not nxt.strip():
        return False
    return _indent_of(nxt) == _indent_of(first) and _statement_shape(nxt) == shape


def _region_size(lines: list[str], index: int) -> int:
    """Count logical same-indent lines until a blank, dedent, or next label."""
    indent = _indent_of(lines[index])
    size = 0
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() or _indent_of(line) < indent:
            break
        if _indent_of(line) == indent:
            if cursor != index and line.lstrip().startswith("#"):
                break
            size += 1
        cursor = _statement_end(lines, cursor) + 1
    return size


def _has_non_ascii_prose(body: str) -> bool:
    return any(ord(ch) > _MAX_ASCII and ch.isalpha() for ch in body)


def _is_commented_out_code(body: str) -> bool:
    """Report whether the comment body is a disabled line of Python."""
    if _CODEY_RE.match(body):
        return True
    if not _CODE_KEYWORD_RE.match(body) or not _CODE_SIGNAL_RE.search(body):
        return False
    try:
        ast.parse(body)
    except SyntaxError:
        return False
    return True


class NoRestatedComment(Rule):
    id: str = "no-restated-comment"
    code: str = "SARJ049"
    description: str = (
        "Comment restates the statement below it — delete it, or replace it "
        "with the why; the code already carries the what."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        try:
            standalone, _ = standalone_comments(source)
            nested = nested_comment_lines(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        lines = source.splitlines()
        wall_members = frozenset(
            line
            for members in statement_comment_walls(path, source, standalone).values()
            for line in members
        )
        diags: list[Diagnostic] = []
        for run in comment_runs(standalone):
            if len(run) != 1:
                continue
            line, col, body = run[0]
            if line in nested or line in wall_members:
                continue
            if self._restates_below(body, line, lines):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col + 1,
                        code=self.code,
                        message=self.description,
                    )
                )
        return diags

    @staticmethod
    def _restates_below(body: str, line: int, lines: list[str]) -> bool:
        if not body or body.endswith("?"):
            return False
        if _DIRECTIVE_RE.match(body) or _is_commented_out_code(body) or _BANNERISH_RE.search(body):
            return False
        if _has_non_ascii_prose(body) or is_protected(body):
            return False
        if _MODALITY_RE.search(body) or _LEAD_IN_RE.search(body) or _EMPHASIS_RE.search(body):
            return False
        if _NEGATION_WORD_RE.search(body):
            return False
        if len(body.split()) > _MAX_WORDS:
            return False
        tokens = content_tokens(body)
        if len(tokens) < _MIN_CONTENT_TOKENS:
            return False
        index = line  # `line` is 1-based, so this indexes the row BELOW it
        if index >= len(lines):
            return False
        code = lines[index]
        if not code.strip() or code.lstrip().startswith("#"):
            return False
        if not _SIMPLE_STMT_RE.match(code) or _BLOCK_OPENER_RE.match(code):
            return False
        if _CODE_NEGATION_RE.search(code):
            return False
        if not _ACTION_STMT_RE.search(code):
            return False
        if _is_group_label(lines, index):
            return False
        if _region_size(lines, index) >= _SECTION_REGION_LINES:
            return False
        return restates(tokens, code_tokens(code))
