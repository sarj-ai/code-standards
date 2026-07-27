"""SARJ049: a one-line comment that only re-spells the statement beneath it.

    # Get profile by national ID
    profile = await self._store.get_profile_by_national_id(national_id, bank_id)

Every content word of the comment is already an identifier on the line below.
It cannot go out of date usefully — it can only go out of date silently, and a
reader who scans it learns nothing they would not have learned from the code.
Delete it, or replace it with the *why* (what the caller must know, what breaks
if the order changes, which ticket decided the shape).

This is deliberately NOT part of SARJ016. bulbul enforces SARJ016 at `error`
through a caret pin, so folding a new detector into it would land uncontrolled
in a consumer's CI on the next patch release; a separate code can be enabled,
baselined and dropped on its own.

**What makes it safe.** The first attempt at this shape (PR #98, TypeScript)
corroborated by substring — `service` matched `locationService` — and produced
933 hits at a ~60% false-positive rate. Coincidental token overlap is the
failure mode, so every one of these guards is load-bearing:

- **Zero information, not "mostly".** EVERY content token must appear on the
  line. One unmatched word means the comment carries something the code does
  not, and it stays. Matching is exact-or-stemmed; there is NO prefix matching.
- **Single-line comment only.** A run of `#` lines is a paragraph, and a
  paragraph's first line sharing words with the code below is a coincidence of
  where the sentence broke.
- **Simple statement only.** A comment above a `def`, a `class`, an `if`, a
  `for` or a `try` is labelling a *region*; the words it shares with the first
  line of that region are incidental.
- **Not a group label.** When the statement below is followed by a same-indent,
  same-shape sibling, the comment heads a run (`# Constants` over eight
  assignments), and deleting it loses the grouping.
- **Not inside a bracketed expression.** A comment at bracket depth > 0 labels
  an *element* of a list, dict or call — one `State(...)` in a list of test
  cases, one entry in a `__all__` group — and the element's own words are what
  it labels. `_comments.nested_comment_lines` exists for exactly this reading.
- **No negation in the code.** The comment-side negation guard below has a
  mirror: when the CODE expresses a property negatively and the comment states
  it positively, the comment is doing a translation the code cannot.
  `# The task is queued` over `assert not kubernetes_executor.task_queue.empty()`
  (airflow) passes the zero-information test only because `not` and `no` are
  stopwords for the tokenizer.
- **Protected class exempt.** Anything carrying a ticket, URL, unit, causal
  connective or the other `_comments` signals is left alone.
- **≤8 words**, no `?` (a question is a note to a reader), no non-ASCII prose
  (the tokenizer cannot read Arabic, so the zero-information test would be
  vacuously true), no commented-out code (SARJ016 owns that), no banner shapes.

**Measured** (this implementation, not the prototype). bulbul **0**; noura-be
**29** over 20 distinct comment texts; pydantic **2**, trio **2**, attrs **0** —
and those four are genuine (`# set_inheritable` above `s1.set_inheritable(False)`,
`# get_inheritable` above `assert not s1.get_inheritable()`).

**The 33-finding sweep those numbers came from was too small to see the failure
mode.** A later sweep over home-assistant (18,069 files, 348 hits) and airflow
(7,656 files, 165) produced 513 findings; 60 were sampled at random and each read
against its source. **47 true positives, 13 false — a 21.7% false-positive rate**,
not the 0% the small corpora suggested. The two guards above are what a labelled
evaluation showed to be free (they suppress 2 of the 13 false positives and 0 of
the 47 true ones); three other candidate guards were built, measured and
*rejected* for costing more recall than they bought:

* *comment matched only through a string literal* — 7 FP but 6 TP, a wash
  (`# Set false` over `variables_set(["variables", "set", "false", "false"])`).
* *comment heads a blank-line-separated paragraph of ≥2 statements* — 9 FP, 12 TP.
* *a sibling comment nearby shares a content word* — 7 FP but **33** TP. Two
  restatements in one function usually name the same domain noun; the shared word
  is the subject matter, not a section structure.

The residual **19%** is one shape the tokenizer cannot separate: a section label
heading a block in a test body (`# test tamper sensor` over the first of six
asserts, `# Test with domain only` over the first of a three-block series). Read
as a hit rate that is **0.8% of eligible single-line comments** in both external
corpora — well under the 4.7%-of-log-calls that got SARJ055 dropped for being a
professional convention — so the shape is rare, not idiomatic. But a house
enabling this at `error` is choosing to reject a test-body section label, and
should say so out loud rather than believe the 0% number.

Getting there cost five guards, each added at the site that produced it and each
with a regression test: the code-keyword arm of the commented-out check (a
disabled `assert` above the assertion that replaced it), the call/assert
statement shapes (a label heading a run of bare calls), modality / lead-in /
emphasis, `_ACTION_STMT_RE` (a label over a data declaration — every remaining
noura false positive), and the two-content-token floor (`# Hashing.` over an
assertion group in attrs).

Suppress an intentional case with `# sarj-noqa: SARJ049 — <reason>`.
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
from sarj_python_lint.rules._paths import is_generated_source


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
_CODE_KEYWORD_RE = re.compile(
    r"^(?:assert|return|raise|await|yield|del|import|from|print|global|nonlocal)\b"
)
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
# A comment above a plain data declaration is labelling the datum, and the noura
# corpus showed that shape is a series of group labels rather than narration:
# `# Profile` over `PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"` sits between
# `# MFA/OTP` and `# Account` in the same enum
# (digital-bank/banking-be/banking_api/core/enums.py:35), and `# Onboarding` over
# a lone `final_onboarding_stage=...` kwarg sits under `# Provider info` in the
# same call (python/voice/services/session_analytics.py:127). Requiring a call
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
_ASSIGN_SHAPE_RE = re.compile(
    r"^\s*[\w.\[\]]+\s*(?::[^=]+)?=[^=]|^\s*[\w.\[\]]+\s*:\s*\S+,?\s*$"
)
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
    """Report whether the statement at `index` is the head of a run of siblings.

    `index` is 0-based into `lines`. The statement's extent is found by bracket
    balance so a multi-line call is skipped whole; if what follows is a
    same-indent statement of the same shape, the comment above labels the run
    rather than the one line.

    Returns:
        True when the comment heads a group rather than a single statement.

    """
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
    """Report whether the comment body is a disabled line of Python.

    Returns:
        True when SARJ016 already owns this comment as commented-out code.

    """
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
    """A single-line comment whose every word already appears on the line below."""

    id: str = "no-restated-comment"
    code: str = "SARJ049"
    description: str = (
        "Comment restates the statement below it — delete it, or replace it "
        "with the why; the code already carries the what."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
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
