from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
import tokenize
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
from sarj_python_lint.rules._comments import (
    PositionedComment,
    comment_runs,
    has_external_reference,
    nested_comment_lines,
    standalone_comments,
    statement_comment_walls,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


_LEADING_PREAMBLE_MIN = 4
_PROSE_MIN_WORDS = 3
_DUMMY_TRANSLATION_MAX_WORDS = 4
_DASHED_CONTINUATION_MIN_WORDS = 2

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

# License text is legally required and therefore never comment cruft.
_LICENSE_HEADER_MAX_LINE = 8
_LICENSE_HEADER_RADIUS = 4

_BANNER_FULL_RE = re.compile(r"^[-=#*~_+.\s]{4,}$")
# `[\u2500-\u257f]` is the Unicode box-drawing block.
_BANNER_RUN_RE = re.compile(r"={4,}|-{4,}|#{4,}|\*{4,}|~{4,}|[\u2500-\u257f]{4,}")

# Recognize editor folding markers such as region and endregion.
_REGION_MARKER_RE = re.compile(r"^#?(?:end)?region\b(?P<title>.*)$", re.IGNORECASE)
_REGION_TITLE_RE = re.compile(r"^[\s:\-\u2013\u2014]*\w[\w \-/&+]*$")
_REGION_TITLE_MAX_WORDS = 5
_REGION_PROSE_VERB_RE = re.compile(
    r"^(?:is|are|was|were|comes?|defaults?|derives?|inherits?|depends?|uses?|maps?|resolves?)\b",
    re.IGNORECASE,
)

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

# Grammar-example markers protect notation that intentionally resembles commented code.
_PSEUDOCODE_RE = re.compile(r"%[^%\s]+%|\[opt\]|<[^<>]+>|\.\.\.")

# Preserve commented commands that document intentional regeneration recipes.
_CODE_REGEN_CALL_RE = re.compile(r"^insert_assert\s*\(")

# Any letter, in any script.
_HAS_LETTER_RE = re.compile(r"[^\W\d_]")

# Sentence-final punctuation.
_SENTENCE_END_RE = re.compile(r"""[.!?:;)\]}"'`]$""")

# Step-narration lead-ins ("First, ...", "Then, ...", "Finally, ...", "Step 2:").
_STEP_NARRATION_RE = re.compile(
    r"^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?"
    r"|finally|lastly|now)\s*[,:]\s*\S",
    re.IGNORECASE,
)

# A rationale marker turns step narration into a legitimate *why* comment
# ("First, we take the outer send lock, because of Trio's standard semantics").
_RATIONALE_RE = re.compile(r"\b(?:because|since|so that|otherwise)\b", re.IGNORECASE)
_RATIONALE_RUN_RE = re.compile(r"\b(?:because|since|so that|otherwise|if|unless|when|until)\b", re.IGNORECASE)

# Markdown headings and embedded heading examples are content when they sit
# inside an expression; the surrounding syntax already supplies structure.
_MARKDOWN_HEADING_RE = re.compile(r"(?:^|\s)#{1,6}\s+\S")

# Self-admitted meta-commentary — the "why later", not the why.
_META_COMMENTARY_RE = re.compile(
    r"\b(?:for now|keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)"
    r"|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)"
    r"|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack"
    r"|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)"
    r"|clean (?:this|it) up|not ideal|placeholder for now)\b",
    re.IGNORECASE,
)

_EDITORIAL_PLACEHOLDER_RE = re.compile(
    r"^(?:(?:implementation omitted|existing code here|your code here|rest of (?:the )?code (?:is )?unchanged|"
    r"same as above|placeholder implementation)\s*[.!]?|"
    r"in a real (?:app(?:lication)?|implementation),?\s+(?:this|we|you|it)\s+would\s+"
    r"(?:call|fetch|generate|download|persist|save|send|store|write)\b[^,;]*[.!]?)$",
    re.IGNORECASE,
)

# Known one-word section labels are structural signposts rather than prose.
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

# A "helper function" opener narrates mechanics without explaining intent.
_HELPER_OPENER_RE = re.compile(
    r"^(?:a\s+)?helper\s+(?:function|method|component|hook|class|type|util(?:ity)?)\b",
    re.IGNORECASE,
)

# Verbs that describe the mechanics of the code below.
_NARRATION_VERBS = (
    r"add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|count|"
    r"create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|"
    r"increment|init|initialise|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|"
    r"print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|"
    r"store|update|validate|wrap|write"
)

# "Let's not await the promise" — the first-person-plural walkthrough voice.
_LETS_RE = re.compile(
    rf"^let'?s\s+(?:not\s+|just\s+|now\s+|first\s+)?(?:{_NARRATION_VERBS})(?:s|es|ed|ing)?\b",
    re.IGNORECASE,
)

# Enumeration markers that narrate a sequence: `# 1.
_ENUMERATION_RE = re.compile(r"^(?:\d+[.)]\s+\S|(?:phase|step)\s+\d+\b)", re.IGNORECASE)

# Dummy translational comments: ultra-short comments that just restate the code.
_DUMMY_TRANSLATION_RE = re.compile(
    r"^(?:increment|return|returns|get|gets|set\b(?! up\b)|sets\b(?! up\b)|function to|method to)\b",
    re.IGNORECASE,
)


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_CODING_COOKIE_RE = re.compile(r"coding[:=]\s*[-_.a-zA-Z0-9]+")

# Only `>>>` arms a doctest block.
_DOCTEST_PROMPT = ">>>"


def _is_coding_cookie(body: str) -> bool:
    return bool(_CODING_COOKIE_RE.search(body))


def _doctest_block_lines(standalone: Sequence[PositionedComment]) -> set[int]:
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


def _externally_referenced_lines(standalone: Sequence[PositionedComment]) -> set[int]:
    exempt: set[int] = set()
    for run in comment_runs(standalone):
        if any(has_external_reference(body) for _, _, body in run):
            exempt.update(line for line, _, _ in run)
    return exempt


def _illustration_block_lines(standalone: Sequence[PositionedComment]) -> set[int]:
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


def _is_redundant_narration(
    body: str,
    prev_body: str | None,
    *,
    isolated_enumeration: bool,
    nested: bool,
) -> bool:
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
        # Exclude common rationale words and test markers.
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
        # Exclude single-word labels that commonly group tests.
        if len(words) > 1 and not any(word in lower_c for word in rationale_words):
            return True
    if not nested and _is_section_label(c):
        return True
    return isolated_enumeration and bool(_ENUMERATION_RE.match(c))


def _is_sentence_continuation(prev_body: str | None) -> bool:
    return bool(prev_body) and not _SENTENCE_END_RE.search(prev_body)


def _is_section_label(body: str) -> bool:
    match = _SECTION_LABEL_RE.match(body)
    return match is not None and match.group(1).lower() in _SECTION_LABEL_WORDS


def _is_heading_underline(body: str, prev_body: str | None) -> bool:
    if not _BANNER_FULL_RE.match(body):
        return False
    if prev_body is None:
        return False
    return any(_is_word_char(ch) for ch in prev_body) and not _is_banner(prev_body) and not _looks_like_code(prev_body)


def _is_dashed_prose_continuation(body: str, prev_body: str | None) -> bool:
    if not _is_sentence_continuation(prev_body) or _BANNER_RUN_RE.search(body) is None:
        return False
    prose = _BANNER_RUN_RE.sub(" ", body)
    words = [word for word in prose.split() if any(character.isalpha() for character in word)]
    return len(words) >= _DASHED_CONTINUATION_MIN_WORDS


def _is_banner(body: str) -> bool:
    if not body:
        return False
    if _BANNER_FULL_RE.match(body):
        return True
    if _BANNER_RUN_RE.search(body):
        return True
    return _is_region_marker(body)


def _is_region_marker(body: str) -> bool:
    match = _REGION_MARKER_RE.match(body)
    if match is None:
        return False
    title = match.group("title").strip()
    if not title:
        return True
    if _REGION_PROSE_VERB_RE.match(title):
        return False
    if not _REGION_TITLE_RE.match(title):
        return False
    return len(title.split()) <= _REGION_TITLE_MAX_WORDS


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
        return _compiles(f"{c}\n    pass")
    if c.startswith("@"):
        return _compiles(f"{c}\ndef _f():\n    pass")
    if _ASSIGN_OR_CALL_RE.match(c):
        # Implicit type condition documentation (e.g. under `else:`)
        if c.startswith(("isinstance(", "issubclass(")):
            return False
        return _is_assign_or_call(c)
    return False


def _is_prose_line(body: str) -> bool:
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


def _license_header_lines(standalone: list[PositionedComment]) -> frozenset[int]:
    anchors = [line for line, _, body in standalone if line <= _LICENSE_HEADER_MAX_LINE and _LICENSE_RE.search(body)]
    return frozenset(
        line
        for anchor in anchors
        for line in range(anchor - _LICENSE_HEADER_RADIUS, anchor + _LICENSE_HEADER_RADIUS + 1)
    )


class NoCommentCruft(Rule):
    id: str = "no-comment-cruft"
    code: str = "SARJ016"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Comment repeats code, preserves dead code, or adds a decorative section marker.",
        rationale="Mechanical narration and dead code obscure the constraints and rationale that comments should preserve.",
        remediation=(
            "Delete the cruft. If author-controlled code is unclear without narration, clarify names, types, or "
            "structure; keep only concise comments for a hidden reason or constraint."
        ),
        category=RuleCategory.MAINTAINABILITY,
        limitations=(
            "Only standalone comments are classified; trailing comments, docstrings, directives, and referenced notes are excluded.",
            "Generated files, license headers, doctests, grammar illustrations, and Sphinx configuration banners are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="commented-out-code",
                title="Dead code preserved as a comment",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("service.py", "value = load()\n# return value\nsave(value)\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="rationale-comment",
                title="Comment records an external constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "value = load()\n# Keep this ordering because Clerk caches the first lookup.\nsave(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        # A Sphinx `docs/**/conf.py` is quickstart-generated boilerplate whose
        # `# Section` banners are the tool's own convention.
        if path.name == "conf.py" and "docs" in path.parts:
            return []
        try:
            standalone, first_code_line = standalone_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags: dict[int, Diagnostic] = {}
        by_line = {line: (col, body) for line, col, body in standalone}
        skip = _doctest_block_lines(standalone) | _illustration_block_lines(standalone)
        referenced = _externally_referenced_lines(standalone)
        rationale_runs = frozenset(
            line
            for run in comment_runs(standalone)
            if len(run) > 1 and any(_RATIONALE_RUN_RE.search(body) for _, _, body in run)
            for line, _, _ in run
        )
        nested = nested_comment_lines(source)
        enumerated = [line for line, _, body in standalone if _ENUMERATION_RE.match(body)]
        license_header = _license_header_lines(standalone)
        walls = statement_comment_walls(path, source, standalone)
        wall_members = frozenset(line for members in walls.values() for line in members)
        for line, col, body in standalone:
            if line in walls:
                diags[line] = Diagnostic(
                    path=path,
                    line=line,
                    col=col + 1,
                    code=self.code,
                    message=(
                        f"Statement comment wall ({len(walls[line])} narrated steps) — "
                        "delete the walkthrough and name the operations in code; keep only constraints or rationale."
                    ),
                    column_encoding=ColumnEncoding.CODEPOINTS,
                )
                continue
            if line in wall_members:
                continue
            if _is_directive(body) or _is_coding_cookie(body) or line in skip:
                continue
            previous = by_line.get(line - 1)
            prev_body = previous[1] if previous is not None and previous[0] == col else None
            msg = self._classify(
                body,
                prev_body,
                narration_protected=line in referenced,
                isolated_enumeration=enumerated == [line],
                nested=line in nested,
                in_license_header=line in license_header,
                in_rationale_run=line in rationale_runs,
            )
            if msg is not None:
                diags[line] = Diagnostic(
                    path=path,
                    line=line,
                    col=col + 1,
                    code=self.code,
                    message=msg,
                    column_encoding=ColumnEncoding.CODEPOINTS,
                )
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
        in_license_header: bool,
        in_rationale_run: bool,
    ) -> str | None:
        if _CODE_REGEN_CALL_RE.match(body):
            return None
        if (
            _EDITORIAL_PLACEHOLDER_RE.fullmatch(body.strip())
            and _RATIONALE_RE.search(body) is None
            and not narration_protected
        ):
            return "Placeholder implementation comment — implement the behavior or use an explicit unsupported path."
        if re.match(r"^(?:todo|fixme)\b", body, re.IGNORECASE):
            if not narration_protected:
                return "Untracked TODO/FIXME marker — add an issue ticket or context link."
            return None
        if _is_banner(body):
            if nested and _MARKDOWN_HEADING_RE.search(body):
                return None
            if _is_heading_underline(body, prev_body) or _is_dashed_prose_continuation(body, prev_body):
                return None
            if in_license_header:
                return None
            return "Section-banner / region comment — structure code with functions, not ASCII rules."
        if _looks_like_code(body):
            if prev_body is not None and _is_prose_line(prev_body):
                return None
            if (
                prev_body is not None
                and _is_sentence_continuation(prev_body)
                and not _looks_like_code(prev_body)
                and not _is_banner(prev_body)
                and _is_assign_or_call(body)
            ):
                return None
            return "Commented-out code — delete it; git history remembers."
        if narration_protected:
            return None
        if in_rationale_run:
            return None
        if _is_redundant_narration(body, prev_body, isolated_enumeration=isolated_enumeration, nested=nested):
            return "Comment narrates the code — delete it or say why, not what. Code is self-documenting."
        return None

    def _flag_leading_preamble(
        self,
        standalone: list[PositionedComment],
        first_code_line: int,
        path: Path,
        diags: dict[int, Diagnostic],
    ) -> None:
        leading: list[PositionedComment] = []
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
            leading.append(PositionedComment(line, col, body))
            prev_line = line
        if any(_LICENSE_RE.search(body) for _, _, body in leading):
            return
        if not any(_HAS_LETTER_RE.search(body) for _, _, body in leading):
            return  # line-art logo, not prose a module docstring could carry
        # Keep prose preambles; only content-free headers are cruft.
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
                        "delete the ceremony; use a descriptive module path and place durable constraints near the "
                        "code they govern or in maintained documentation."
                    ),
                    column_encoding=ColumnEncoding.CODEPOINTS,
                )
