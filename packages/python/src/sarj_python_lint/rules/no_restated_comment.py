"""SARJ049 — A one-line comment that only re-spells the statement beneath it.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_restated_comment.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ049.md
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
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MAX_WORDS = 8
_MAX_ASCII = 127
# A single content word cannot *restate* a statement — it labels one. The
# famous-corpus sweep's last two false positives were exactly that shape
# (`# Hashing.` and `# Repr.` heading assertion groups in attrs/tests/
# test_slots.py:134,137), and the bare-label vocabulary that matters
# (`# Constants`, `# Helpers`) is already SARJ016's.
_MIN_CONTENT_TOKENS = 2

# Directive comments, in the broad spelling — this rule sees Python only, but the
# list is kept in step with the TypeScript twin so the two cannot drift.
_DIRECTIVE_RE = re.compile(
    r"^\s*(?:todo|fixme|hack\b|xxx|note:|nb:|warning:|important:|"
    r"noqa|sarj-noqa|type:|pragma|pyright|mypy|fmt:|isort|ruff|pylint|flake8|nosec|nosemgrep|"
    r"-\*-|!/|coding[:=])",
    re.IGNORECASE,
)

# Commented-out code and section banners belong to SARJ016; reporting them twice
# would make the finding look bigger than it is. The keyword arm was added after
# the famous-corpus sweep: `# assert v.to_python(input_value) == v`
# (pydantic-core/tests/validators/test_dict.py) is a disabled assertion sitting
# above the assertion that replaced it, and every word of it naturally appears
# on the line below.
_CODEY_RE = re.compile(r"^[\w.\[\]'\"]+\s*[:=]\s*\S|^[\w.]+\(")
_CODE_KEYWORD_RE = re.compile(r"^(?:assert|return|raise|await|yield|del|import|from|print|global|nonlocal)\b")
_CODE_SIGNAL_RE = re.compile(r"[=()\[\]{}]")
_BANNERISH_RE = re.compile(r"[=\-─-╿*#~_.]{3,}|^[A-Z0-9 _:-]+$")

# Three shapes that survived the zero-information test in the famous-corpus
# sweep and were wrong every time, each guarded at the site that produced it:
#
#  - modality. `can`, `should`, `must` state a possibility or an obligation, and
#    no arrangement of identifiers can say that. `# can also aclose`
#    (trio/_tests/test_dtls.py:283) documents that a second API reaches the same
#    state; `# Should still have a traceback:`
#    (pydantic-core/tests/test_errors.py:755) says the property survives the step
#    above, not that the line below checks it.
#  - a colon-terminated lead-in announces what follows rather than describing the
#    one line under it (the same reading SARJ016 gives `# For example:`).
#  - inline emphasis. Someone who wrote `*not*` or backticked an identifier was
#    making a point about it — `# model_fields is *not* complete on Foo`
#    (pydantic/tests/test_forward_ref.py:71).
#  - a bare negation. `no`, `not` and `never` are stopwords for the tokenizer, so
#    a comment stating a NEGATIVE property passes the zero-information test on
#    the positive spelling below it — `# no issues with confirmPassword or
#    password` over `return payload.issues.every(...)`
#    (zod/packages/zod/src/v4/classic/tests/refine.test.ts:546). Saying what is
#    absent is the one thing the code's own words cannot.
_MODALITY_RE = re.compile(r"\b(?:can|could|should|shall|may|might|must|will|would|cannot)\b", re.IGNORECASE)
_LEAD_IN_RE = re.compile(r":$")
_EMPHASIS_RE = re.compile(r"\*\w[^*]*\*|`[^`]+`")
_NEGATION_WORD_RE = re.compile(r"\b(?:no|not|never|neither|nor|without|none|non)\b", re.IGNORECASE)

# The same asymmetry, on the code's side. `not` / `no` / `none` are stopwords for
# `content_tokens`, so a comment stating a property POSITIVELY passes the
# zero-information test against a line that expresses it as a double negative —
# `# The task is queued` over `assert not kubernetes_executor.task_queue.empty()`
# (airflow-2/providers/cncf/kubernetes/.../test_kubernetes_executor.py:1022).
# Turning `not ... empty()` into "is queued" is the translation the reader wanted.
_CODE_NEGATION_RE = re.compile(r"\bnot\b|!=|\bis None\b|\.empty\(|assert(?:Not|False)")

# A statement whose head a comment could be restating.
_SIMPLE_STMT_RE = re.compile(
    r"^\s*(?:return\b|yield\b|raise\b|await |del |assert |"
    r"[\w.\[\]\"'()]+\s*(?:[:+\-*/|&]?=)\s*\S|[\w.]+\(|await\s+[\w.]+\()"
)
# The statement must *do* something — invoke a callable, or hand a value back.
# A comment above a plain data declaration is labelling the datum, and the
# first-party corpus showed that shape is a series of group labels rather than
# narration: `# Profile` over `PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"` sits
# between `# MFA/OTP` and `# Account` in the same enum at one first-party site,
# and `# Onboarding` over a lone `final_onboarding_stage=...` kwarg sits under
# `# Provider info` in the same call at another. Requiring a call
# removed all four of those without touching a single narration hit — the
# distinguishing feature was never the label, it was what it labels.
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
# The call and assert shapes were added after the famous-corpus sweep: without
# them a label heading a run of bare calls or asserts (`# Secrets` over eight
# `st.register_type_strategy(...)` lines in pydantic's hypothesis plugin,
# `# Hashing.` / `# Repr.` over attrs' assertion groups) read as a comment about
# one statement. Those are the grouping the label exists to provide.
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


def _is_group_label(lines: list[str], index: int) -> bool:
    """Report whether the statement at `index` is the head of a run of siblings."""
    first = lines[index]
    shape = _statement_shape(first)
    if shape is None:
        return False
    balance = 0
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        balance += line.count("(") + line.count("[") + line.count("{")
        balance -= line.count(")") + line.count("]") + line.count("}")
        if balance <= 0:
            break
        cursor += 1
    following = cursor + 1
    if following >= len(lines):
        return False
    nxt = lines[following]
    if not nxt.strip():
        return False
    return _indent_of(nxt) == _indent_of(first) and _statement_shape(nxt) == shape


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
    has_evidence: bool = True
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
        diags: list[Diagnostic] = []
        for run in comment_runs(standalone):
            if len(run) != 1:
                continue
            line, col, body = run[0]
            if line in nested:
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
        return restates(tokens, code_tokens(code))
