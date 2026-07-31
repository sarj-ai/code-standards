"""SARJ016 — Comment cruft — commented-out code, section banners, header preambles.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_comment_cruft.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ016.md
"""

from __future__ import annotations

import ast
import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._comments import (
    comment_runs,
    has_external_reference,
    nested_comment_lines,
    standalone_comments,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


_LEADING_PREAMBLE_MIN = 4
_PROSE_MIN_WORDS = 3
_DUMMY_TRANSLATION_MAX_WORDS = 4

_DIRECTIVE_PREFIXES = (
    "type:",
    "noqa",
    "sarj-noqa",
    "pragma:",
    "pyright:",
    "mypy:",
    "fmt:",
    "isort:",
    "ruff:",
    "pylint:",
    "flake8:",
    "nosec",
    "nosemgrep",
    "hack",
    "xxx:",
    "-*-",
    "language=",
)

_LICENSE_RE = re.compile(
    r"copyright|license|licen[cs]ed|spdx|permission is hereby granted|"
    r"all rights reserved",
    re.IGNORECASE,
)

_BANNER_FULL_RE = re.compile(r"^[-=#*~_+.\s]{4,}$")
# `[\u2500-\u257f]` is the Unicode box-drawing block. A `────────` rule is the
# same section separator as `--------`, just prettier; 34 of them were sitting in
# the corpus under a check that only knew ASCII.
_BANNER_RUN_RE = re.compile(r"={4,}|-{4,}|#{4,}|\*{4,}|~{4,}|[\u2500-\u257f]{4,}")

# A VS Code / Visual Studio folding marker: `# region`, `# region helpers`,
# `#region Types`, `# endregion`. The title must be short and unpunctuated.
# Matching the bare word alone flagged running prose that merely opens with it —
# `# region, sector and type are HARD constraints when ...` at one first-party
# site, plus five TypeScript siblings. A marker names a region; a sentence discusses
# one, and a sentence has punctuation and more than a handful of words.
_REGION_MARKER_RE = re.compile(r"^#?(?:end)?region\b(?P<title>.*)$", re.IGNORECASE)
_REGION_TITLE_RE = re.compile(r"^[\s:\-\u2013\u2014]*\w[\w \-/&+]*$")
_REGION_TITLE_MAX_WORDS = 5

_CODE_STMT_RE = re.compile(
    r"^(?:import |from \S+ import |return\b|yield\b|await |"
    r"del |pass\b|break\b|continue\b|global |nonlocal |print\()"
)
# `assert`/`raise` double as English verbs ("assert this is true"), so they are
# only treated as code when the line also carries a code signal (an operator,
# paren, bracket, dot, or digit) — prose almost never does.
_RISKY_STMT_RE = re.compile(r"^(?:assert |raise )")
_CODE_SIGNAL_RE = re.compile(r"""[=()\[\]{}.:+\-*/%<>!&|@"']|\d""")
_CODE_HEADER_RE = re.compile(
    r"^(?:def |class |async def |if |elif |else:|for |while |with |"
    r"try:|except|finally:)"
)
_ASSIGN_OR_CALL_RE = re.compile(r"^[A-Za-z_][\w.\[\]]*\s*(?:=|:=|\+=|-=|\*=|/=)\s*\S|^[A-Za-z_][\w.]*\(")

# Pseudo-code / grammar-example markers (`%sent%`, `[opt]`, `<FunctionBody>`,
# `...`). Real commented-out code doesn't carry these — they mark an
# illustration inside a doc comment, not a line that was once executed.
_PSEUDOCODE_RE = re.compile(r"%[^%\s]+%|\[opt\]|<[^<>]+>|\.\.\.")

# Code-regeneration recipes: a commented-out call that exists *to be
# uncommented*, at which point the tool rewrites the file around it.
# `insert_assert(...)` (pytest-examples / devtools) sits directly above the
# assertion it generates; "delete it, git history remembers" is wrong advice
# because git never held it.
_CODE_REGEN_CALL_RE = re.compile(r"^insert_assert\s*\(")

# Any letter, in any script. A leading comment block without a single one is
# line art (requests' logo), not a header preamble a docstring could replace.
_HAS_LETTER_RE = re.compile(r"[^\W\d_]")

# Sentence-final punctuation. A comment line whose predecessor lacks it is the
# wrapped tail of one sentence, not a standalone claim about the code.
_SENTENCE_END_RE = re.compile(r"""[.!?:;)\]}"'`]$""")

# Step-narration lead-ins ("First, ...", "Then, ...", "Finally, ...", "Step 2:").
# A trailing comma/colon is required so English adverbs ("finally the invariant
# holds") aren't mistaken for an enumeration marker.
_STEP_NARRATION_RE = re.compile(
    r"^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?"
    r"|finally|lastly|now)\s*[,:]\s*\S",
    re.IGNORECASE,
)

# A rationale marker turns step narration into a legitimate *why* comment
# ("First, we take the outer send lock, because of Trio's standard semantics").
_RATIONALE_RE = re.compile(r"\b(?:because|since|so that|otherwise)\b", re.IGNORECASE)

# Self-admitted meta-commentary — the "why later", not the why. Owner-tagged
# directive markers are handled elsewhere (as directives) and kept.
_META_COMMENTARY_RE = re.compile(
    r"\b(?:for now|keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)"
    r"|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)"
    r"|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack"
    r"|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)"
    r"|clean (?:this|it) up|not ideal|placeholder for now)\b",
    re.IGNORECASE,
)

# A bare one-word signpost naming a region of the file (`# Constants`,
# `# Helpers`, `# Types`). It is a table of contents for a file that should have
# been split, and it goes stale silently. 22 corpus hits across two first-party
# repos, 12 of 12 sampled were true positives. Closed vocabulary on
# purpose: a one-word comment outside this list ("# Riyadh") is far more likely
# to be a genuine label for a value.
_SECTION_LABEL_WORDS = frozenset(
    {
        "actions",
        "components",
        "config",
        "configuration",
        "constant",
        "constants",
        "enums",
        "exports",
        "fixtures",
        "getters",
        "globals",
        "handler",
        "handlers",
        "helper",
        "helpers",
        "hook",
        "hooks",
        "imports",
        "interfaces",
        "main",
        "mocks",
        "models",
        "mutations",
        "props",
        "queries",
        "reducers",
        "routes",
        "schemas",
        "selectors",
        "setters",
        "setup",
        "state",
        "styles",
        "teardown",
        "type",
        "types",
        "util",
        "utilities",
        "utils",
    }
)
_SECTION_LABEL_RE = re.compile(r"^([A-Za-z]+)\s*:?\s*$")

# "Helper function to check if a path is active" — the opener announces the
# *category* of the thing below (which its `def` already states) and then
# restates its name. 6 corpus hits, 6 true positives.
_HELPER_OPENER_RE = re.compile(
    r"^(?:a\s+)?helper\s+(?:function|method|component|hook|class|type|util(?:ity)?)\b",
    re.IGNORECASE,
)

# Verbs that describe the mechanics of the code below. Shared with the `Let's …`
# gate and kept in step with the TypeScript `NARRATION_VERB_RE`.
_NARRATION_VERBS = (
    r"add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|count|"
    r"create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|"
    r"increment|init|initialise|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|"
    r"print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|"
    r"store|update|validate|wrap|write"
)

# "Let's not await the promise" — the first-person-plural walkthrough voice.
# Gated on the verb list because the third-person `lets` is a different word
# doing real work: "lets a same-day re-run find the message it already posted"
# explains a mechanism and must not be touched.
_LETS_RE = re.compile(
    rf"^let'?s\s+(?:not\s+|just\s+|now\s+|first\s+)?(?:{_NARRATION_VERBS})(?:s|es|ed|ing)?\b",
    re.IGNORECASE,
)

# Enumeration markers that narrate a sequence: `# 1. Load the config`,
# `# Phase 2: reconcile`. Flagged only when the file carries exactly one of
# them — a *run* of them is a documented algorithm walkthrough, which is the
# kind of comment this rule exists to protect.
_ENUMERATION_RE = re.compile(r"^(?:\d+[.)]\s+\S|(?:phase|step)\s+\d+\b)", re.IGNORECASE)

# Dummy translational comments: ultra-short comments that just restate the code.
_DUMMY_TRANSLATION_RE = re.compile(
    r"^(?:increment|return|returns|get|gets|set\b(?! up\b)|sets\b(?! up\b)|function to|method to)\b",
    re.IGNORECASE,
)


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_CODING_COOKIE_RE = re.compile(r"coding[:=]\s*[-_.a-zA-Z0-9]+")

# Only `>>>` arms a doctest block. A bare `...` cannot: an ASCII banner of
# dots starts with it, and exempting on that alone silently disabled the
# banner check.
_DOCTEST_PROMPT = ">>>"


def _is_coding_cookie(body: str) -> bool:
    """Report whether the comment is a PEP 263 source-encoding declaration."""
    return bool(_CODING_COOKIE_RE.search(body))


def _doctest_block_lines(standalone: Sequence[tuple[int, int, str]]) -> set[int]:
    """Collect every line of a contiguous comment run that contains a doctest prompt."""
    exempt: set[int] = set()
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if any(body.startswith(_DOCTEST_PROMPT) for _, body in block):
            exempt.update(line for line, _ in block)
        block.clear()

    for line, _, body in sorted(standalone):
        if block and line != block[-1][0] + 1:
            flush()
        block.append((line, body))
    flush()
    return exempt


def _externally_referenced_lines(standalone: Sequence[tuple[int, int, str]]) -> set[int]:
    """Collect every line of a comment run that cites a ticket, URL, RFC or issue."""
    exempt: set[int] = set()
    for run in comment_runs(standalone):
        if any(has_external_reference(body) for _, _, body in run):
            exempt.update(line for line, _, _ in run)
    return exempt


def _illustration_block_lines(standalone: Sequence[tuple[int, int, str]]) -> set[int]:
    """Collect the lines of every embedded-snippet block inside a comment run."""
    exempt: set[int] = set()
    armed = False
    prev_line: int | None = None
    for line, _, body in sorted(standalone):
        if prev_line is not None and line != prev_line + 1:
            armed = False
        prev_line = line
        if not body:
            continue
        if _is_prose_line(body):
            armed = body.endswith(":") and not _CODE_HEADER_RE.match(body)
            continue
        if armed:
            exempt.add(line)
    return exempt


def _is_directive(body: str) -> bool:
    low = body.lower()
    for prefix in _DIRECTIVE_PREFIXES:
        if not low.startswith(prefix):
            continue
        rest = low[len(prefix) :]
        if _is_word_char(prefix[-1]) and rest and _is_word_char(rest[0]):
            continue
        return True
    return False


def _is_sentence_continuation(prev_body: str | None) -> bool:
    """Report whether the previous comment line leaves a sentence unfinished."""
    return bool(prev_body) and not _SENTENCE_END_RE.search(prev_body)


def _is_section_label(body: str) -> bool:
    """Report whether the comment is a bare one-word section signpost."""
    match = _SECTION_LABEL_RE.match(body)
    return match is not None and match.group(1).lower() in _SECTION_LABEL_WORDS


def _is_redundant_narration(
    body: str,
    prev_body: str | None,
    *,
    isolated_enumeration: bool,
    nested: bool,
) -> bool:
    """Whether a comment merely narrates the code (step markers, meta-commentary)."""
    c = body.strip()
    if not c or _looks_like_code(c):
        return False
    if _RATIONALE_RE.search(c):
        return False  # "First, take the lock, because ..." carries a why
    if _is_sentence_continuation(prev_body):
        return False
    if _STEP_NARRATION_RE.search(c) or _META_COMMENTARY_RE.search(c):
        return True
    if _HELPER_OPENER_RE.match(c) or _LETS_RE.match(c):
        return True
    words = c.split()
    if (
        len(words) <= _DUMMY_TRANSLATION_MAX_WORDS
        and _DUMMY_TRANSLATION_RE.match(c)
        and not any(ch in c for ch in "():=")
    ):
        # Exclude common rationale words or test markers
        lower_c = c.lower()
        rationale_words = (
            "when",
            "because",
            "if",
            "so that",
            "due to",
            "for",
            "instead of",
            "to prevent",
            "to avoid",
            "only",
        )
        # Also exclude single-word labels like `# get` which are often group labels in tests
        if len(words) > 1 and not any(word in lower_c for word in rationale_words):
            return True
    if not nested and _is_section_label(c):
        return True
    return isolated_enumeration and bool(_ENUMERATION_RE.match(c))


def _is_heading_underline(body: str, prev_body: str | None) -> bool:
    """Report whether a punctuation-only banner underlines a texty comment line."""
    if not _BANNER_FULL_RE.match(body):
        return False
    if prev_body is None:
        return False
    return any(_is_word_char(ch) for ch in prev_body) and not _is_banner(prev_body) and not _looks_like_code(prev_body)


def _is_region_marker(body: str) -> bool:
    """Report whether the comment is a folding-region marker rather than prose."""
    match = _REGION_MARKER_RE.match(body)
    if match is None:
        return False
    title = match.group("title").strip()
    if not title:
        return True
    if not _REGION_TITLE_RE.match(title):
        return False
    return len(title.split()) <= _REGION_TITLE_MAX_WORDS


def _is_banner(body: str) -> bool:
    if not body:
        return False
    if _BANNER_FULL_RE.match(body):
        return True
    if _BANNER_RUN_RE.search(body):
        return True
    return _is_region_marker(body)


def _looks_like_code(body: str) -> bool:
    c = body.strip()
    if not c:
        return False
    if _PSEUDOCODE_RE.search(c):
        return False
    if _CODE_STMT_RE.match(c):
        return _compiles(c)
    if _RISKY_STMT_RE.match(c):
        return bool(_CODE_SIGNAL_RE.search(c)) and _compiles(c)
    if _CODE_HEADER_RE.match(c):
        return _compiles(c + "\n    pass")
    if c.startswith("@"):
        return _compiles(c + "\ndef _f():\n    pass")
    if _ASSIGN_OR_CALL_RE.match(c):
        # Implicit type condition documentation (e.g. under `else:`)
        if c.startswith(("isinstance(", "issubclass(")):
            return False
        return _is_assign_or_call(c)
    return False


def _is_prose_line(body: str) -> bool:
    """Report whether `body` reads as a natural-language sentence, not code."""
    c = body.strip()
    if not c or _is_banner(c) or _is_directive(c) or _looks_like_code(c):
        return False
    if c.endswith(":"):
        return True
    words = [w for w in re.split(r"\s+", c) if any(ch.isalpha() for ch in w)]
    return len(words) >= _PROSE_MIN_WORDS


def _compiles(snippet: str) -> bool:
    try:
        ast.parse(snippet)
    except SyntaxError:
        return False
    return True


def _is_assign_or_call(snippet: str) -> bool:
    try:
        mod = ast.parse(snippet)
    except SyntaxError:
        return False
    if len(mod.body) != 1:
        return False
    stmt = mod.body[0]
    if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)


class NoCommentCruft(Rule):
    id: str = "no-comment-cruft"
    code: str = "SARJ016"
    has_evidence: bool = True
    description: str = (
        "Comment cruft (commented-out code, section banner, or file-header "
        "preamble) — delete it; code carries the what, comments only the why."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        # A Sphinx `docs/**/conf.py` is quickstart-generated boilerplate whose
        # `# -- Section ----` banners are the tool's own convention.
        if path.name == "conf.py" and "docs" in path.parts:
            return []
        try:
            standalone, first_code_line = standalone_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags: dict[int, Diagnostic] = {}
        by_line = {line: body for line, _, body in standalone}
        skip = _doctest_block_lines(standalone) | _illustration_block_lines(standalone)
        referenced = _externally_referenced_lines(standalone)
        nested = nested_comment_lines(source)
        enumerated = [line for line, _, body in standalone if _ENUMERATION_RE.match(body)]
        for line, col, body in standalone:
            if _is_directive(body) or _is_coding_cookie(body) or line in skip:
                continue
            prev_body = by_line.get(line - 1)
            msg = self._classify(
                body,
                prev_body,
                narration_protected=line in referenced,
                isolated_enumeration=enumerated == [line],
                nested=line in nested,
            )
            if msg is not None:
                diags[line] = Diagnostic(path=path, line=line, col=col + 1, code=self.code, message=msg)
        self._flag_leading_preamble(standalone, first_code_line, path, diags)
        return [diags[k] for k in sorted(diags)]

    @staticmethod
    def _classify(
        body: str,
        prev_body: str | None,
        *,
        narration_protected: bool,
        isolated_enumeration: bool,
        nested: bool,
    ) -> str | None:
        if _CODE_REGEN_CALL_RE.match(body):
            return None
        if re.match(r"^(?:todo|fixme)\b", body, re.IGNORECASE):
            if not narration_protected:
                return "Untracked TODO/FIXME marker — add an issue ticket or context link."
            return None
        if _is_banner(body):
            if _is_heading_underline(body, prev_body):
                return None
            return "Section-banner / region comment — structure code with functions, not ASCII rules."
        if _looks_like_code(body):
            if prev_body is not None and _is_prose_line(prev_body):
                return None
            return "Commented-out code — delete it; git history remembers."
        if narration_protected:
            return None
        if _is_redundant_narration(body, prev_body, isolated_enumeration=isolated_enumeration, nested=nested):
            return "Comment narrates the code — delete it or say why, not what. Code is self-documenting."
        return None

    def _flag_leading_preamble(
        self,
        standalone: list[tuple[int, int, str]],
        first_code_line: int,
        path: Path,
        diags: dict[int, Diagnostic],
    ) -> None:
        leading: list[tuple[int, int, str]] = []
        prev_line: int | None = None
        for line, col, body in standalone:
            if line >= first_code_line:
                break
            if body.startswith("!"):
                continue
            if _is_directive(body):
                continue
            if prev_line is not None and line != prev_line + 1:
                break
            leading.append((line, col, body))
            prev_line = line
        if any(_LICENSE_RE.search(body) for _, _, body in leading):
            return
        if not any(_HAS_LETTER_RE.search(body) for _, _, body in leading):
            return  # line-art logo, not prose a module docstring could carry
        # A preamble carrying at least one prose sentence is documentation — the
        # *why* this rule asks for — regardless of which comment syntax carries
        # it. See the module docstring for the corpus evidence.
        if any(_is_prose_line(body) for _, _, body in leading):
            return
        if len(leading) >= _LEADING_PREAMBLE_MIN:
            line, col, _ = leading[0]
            if line not in diags:
                diags[line] = Diagnostic(
                    path=path,
                    line=line,
                    col=col + 1,
                    code=self.code,
                    message=(
                        f"File-header comment preamble ({len(leading)} lines) — "
                        "use a module docstring for the why, not a block of comments."
                    ),
                )
