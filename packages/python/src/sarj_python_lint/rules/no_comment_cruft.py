"""SARJ016: flag comment cruft — commented-out code, section banners, header preambles.

Code expresses the *what*; comments are reserved for the *why*. Three comment
shapes carry no *why* and are pure noise — they are detected deterministically
here (the fuzzier "this comment merely restates the code" judgment stays in the
readability audit, not this rule):

1. Commented-out code — a standalone comment whose text parses as Python:
       # return early_result
       # for row in rows:
   Delete it; git history remembers.

2. Section-banner / region markers:
       # ============================
       # region helpers
   Structure code with functions, not ASCII rules.

3. Leading file-header preamble — a run of 4+ standalone comment lines at the
   top of the file before any code. Use a module docstring for the *why*, not a
   block of `#` lines.

Deliberately NOT flagged: trailing/standalone *prose* comments (the legitimate
"why"); code-shaped *illustrations* — a line that parses as Python but sits
under a prose lead-in (`# For example:`, a wrapped sentence) or carries
pseudo-code markers (`%sent%`, `[opt]`, `<FunctionBody>`, `...`); and directive
comments — `# type:`, `# noqa`, `# sarj-noqa`,
`# pragma:`, `# pyright:`, `# mypy:`, `# fmt:`, `# isort:`, `# ruff:`,
`# nosec`, `# TODO`, `# FIXME`, `# language=` (IDE injection), shebangs, and
coding declarations.

Also NOT flagged (famous-repo sweep hardening):
- generated files (`_paths.is_generated_source`) — their banners are the
  generator's warning header, not hand-written cruft;
- a punctuation-only "banner" directly beneath a texty comment line — that is
  an RST-style heading underline or an ASCII-diagram row inside a prose comment
  essay (trio's epoll/socket design essays), not a code-section separator;
- step narration that carries a rationale marker (`because`, `since`,
  `so that`, `otherwise`) — "First, take the lock, because ..." is a *why*.

Suppress an intentional case with `# sarj-noqa: SARJ016 — <reason>`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


_LEADING_PREAMBLE_MIN = 4
_PROSE_MIN_WORDS = 3

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
    "todo",
    "fixme",
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
_BANNER_RUN_RE = re.compile(r"={4,}|-{4,}|#{4,}|\*{4,}|~{4,}")
_REGION_RE = re.compile(r"^(?:end)?region\b", re.IGNORECASE)

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

# Step-narration lead-ins ("First, ...", "Then, ...", "Finally, ...", "Step 2:").
# A trailing comma/colon is required so English adverbs ("finally the invariant
# holds") aren't mistaken for an enumeration marker.
_STEP_NARRATION_RE = re.compile(
    r"^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?"
    r"|finally|lastly|now)\s*[,:]\s*\S|^step\s+\d+\b",
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


def _comment_body(raw: str) -> str:
    return raw.lstrip("#").strip()


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_CODING_COOKIE_RE = re.compile(r"coding[:=]\s*[-_.a-zA-Z0-9]+")

# Only `>>>` arms a doctest block. A bare `...` cannot: an ASCII banner of
# dots starts with it, and exempting on that alone silently disabled the
# banner check.
_DOCTEST_PROMPT = ">>>"


def _is_coding_cookie(body: str) -> bool:
    """Report whether the comment is a PEP 263 source-encoding declaration.

    `# encoding=utf-8` / `# -*- coding: utf-8 -*-` are read by the interpreter,
    not commentary, and `rich` carries them at the top of test modules.

    Returns:
        True when the body declares a source encoding.

    """
    return bool(_CODING_COOKIE_RE.search(body))


def _doctest_block_lines(standalone: Sequence[tuple[int, int, str]]) -> set[int]:
    """Collect every line of a contiguous comment run that contains a doctest prompt.

    A commented doctest is documentation, not dead code, but its *expected
    output* lines look exactly like commented-out code — `# URL('https://...')`
    in httpx's `_client.py` is the canonical shape. Exempting only the `>>>`
    lines would still flag the output beneath them, so the whole run goes.

    Returns:
        The line numbers belonging to a doctest comment block.

    """
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


def _is_redundant_narration(body: str) -> bool:
    """Whether a comment merely narrates the code (step markers, meta-commentary).

    Returns:
        True for step-narration lead-ins and self-admitted meta-commentary.

    """
    c = body.strip()
    if not c or _looks_like_code(c):
        return False
    if _RATIONALE_RE.search(c):
        return False  # "First, take the lock, because ..." carries a why
    return bool(_STEP_NARRATION_RE.search(c) or _META_COMMENTARY_RE.search(c))


def _is_heading_underline(body: str, prev_body: str | None) -> bool:
    """Report whether a punctuation-only banner underlines a texty comment line.

    An RST-style heading underline (`# Literature review` / `# -----------`) or
    an ASCII-diagram row directly beneath a texty row lives INSIDE a prose
    comment block — it is typography, not a code-section separator.

    Returns:
        True when the banner sits directly under a texty, non-banner comment.

    """
    if not _BANNER_FULL_RE.match(body):
        return False
    if prev_body is None:
        return False
    return any(_is_word_char(ch) for ch in prev_body) and not _is_banner(prev_body) and not _looks_like_code(prev_body)


def _is_banner(body: str) -> bool:
    if not body:
        return False
    if _BANNER_FULL_RE.match(body):
        return True
    if _BANNER_RUN_RE.search(body):
        return True
    return bool(_REGION_RE.match(body))


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
        return _is_assign_or_call(c)
    return False


def _is_prose_line(body: str) -> bool:
    """Report whether `body` reads as a natural-language sentence, not code.

    Used to spot a doc/prose comment that immediately precedes a code-shaped
    line: `# For example:` above `# result = {**a, **b}`, or a wrapped sentence
    whose second line happens to parse as an expression. Such a line is an
    illustration / prose continuation, not commented-out code.

    Returns:
        True when `body` reads as prose.

    """
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
    """Commented-out code, section banners, or a leading file-header comment block."""

    id: str = "no-comment-cruft"
    code: str = "SARJ016"
    description: str = (
        "Comment cruft (commented-out code, section banner, or file-header "
        "preamble) — delete it; code carries the what, comments only the why."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        # A Sphinx `docs/**/conf.py` is quickstart-generated boilerplate whose
        # `# -- Section ----` banners are the tool's own convention.
        if path.name == "conf.py" and "docs" in path.parts:
            return []
        try:
            standalone, first_code_line = _standalone_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags: dict[int, Diagnostic] = {}
        by_line = {line: body for line, _, body in standalone}
        doctest_lines = _doctest_block_lines(standalone)
        for line, col, body in standalone:
            if _is_directive(body) or _is_coding_cookie(body) or line in doctest_lines:
                continue
            prev_body = by_line.get(line - 1)
            msg = self._classify(body, prev_body)
            if msg is not None:
                diags[line] = Diagnostic(path=path, line=line, col=col + 1, code=self.code, message=msg)
        self._flag_leading_preamble(standalone, first_code_line, path, diags)
        return [diags[k] for k in sorted(diags)]

    @staticmethod
    def _classify(body: str, prev_body: str | None) -> str | None:
        if _is_banner(body):
            if _is_heading_underline(body, prev_body):
                return None
            return "Section-banner / region comment — structure code with functions, not ASCII rules."
        if _looks_like_code(body):
            if prev_body is not None and _is_prose_line(prev_body):
                return None
            return "Commented-out code — delete it; git history remembers."
        if _is_redundant_narration(body):
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


_LAYOUT_TOKENS = frozenset({tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})

_NON_CODE_TOKENS = _LAYOUT_TOKENS | frozenset({tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER})


def _standalone_comments(source: str) -> tuple[list[tuple[int, int, str]], int]:
    """Return (standalone comments, first code line).

    A comment is standalone when it is the only content on its line. `first code
    line` is the row of the first real code token (a large sentinel if none).

    Returns:
        The standalone comments and the first code line's row.

    """
    out: list[tuple[int, int, str]] = []
    first_code_line = 1 << 30
    prev_end_row = 0
    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type == tokenize.COMMENT and tok.start[0] != prev_end_row:
            out.append((tok.start[0], tok.start[1], _comment_body(tok.string)))
        if tok.type not in _LAYOUT_TOKENS:
            prev_end_row = tok.end[0]
        if tok.type not in _NON_CODE_TOKENS:
            first_code_line = min(first_code_line, tok.start[0])
    return out, first_code_line
