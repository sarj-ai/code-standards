"""Shared comment analysis for the comment-hygiene rules (SARJ016/049/050/051).

Two things live here, both needed by more than one rule.

**The protected class.** Nine deterministic signals that mark a comment as
carrying something the code cannot: an external reference, a version pin, a
number with a unit, a causal connective, a negation of the obvious, an
upstream-quirk word, a concurrency/invariant term, security reasoning, or a
vendor proper noun with *ascribed behaviour*. Measured over a 37,918-comment
corpus from nine repos: the nine signals protect **40/40** hand-picked best
comments and leak **~1%** of the hand-classified cruft list.

The class is an **EXEMPTION FLOOR, never a test**. `is_protected(body)` being
False says nothing at all about a comment — over pydantic / trio / attrs it
matches only 18-35% of comments a human called valuable. Every use here is of
the form "if protected, do not flag"; inverting it into "unprotected, so
delete" would flag two thirds of the best comments in Python's most carefully
commented libraries. If a future rule wants a *positive* test for value, it
needs its own measurement, not this.

**One tokenize pass per file.** `standalone_comments()` mirrors
`rule_base.parse_or_none`: a single-slot memo keyed on the source object, so
the four comment rules that all need "every comment that is alone on its line"
tokenize each file once between them rather than once each.
"""

from __future__ import annotations

import io
import re
import tokenize
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


# S1 — external reference: URL, issue/ticket key, RFC/PEP/CVE, bare GitHub issue
# number, or an email/handle domain. Ticket keys allow letters after the first
# digit (`PLATFORM-1YC`) and exclude the encoding/algorithm acronyms that share
# the shape (`UTF-8`, `SHA-256`, `ISO-8601`, `AES-256`).
_REF_RE = re.compile(
    r"https?://|\bRFC[- ]?\d+|\bPEP[- ]?\d+|\bCVE-\d{4}|"
    r"\b(?!UTF-|SHA-|ISO-|AES-|CRC-|MD-|PCM-|EOF-|API-|BASE-)[A-Z][A-Z0-9]{1,9}-\d[A-Z0-9]{0,5}\b|"
    r"(?<![&\w])#\d{2,6}\b|"
    r"@[a-z][\w.-]*\.(?:us|com|ai|io|net|org|dev)\b",
)

# S2 — version pin or comparison: ">= 0.137", "v5.0", "since Python 3.11".
_VERSION_RE = re.compile(
    r"(?:>=|<=|==|<|>)\s*v?\d+\.\d+|\bv\d+\.\d+|\b(?:since|until|as of)\s+(?:v?\d+\.\d+|Python\s*\d)",
    re.IGNORECASE,
)

# S3 — a number carrying a unit (time, size, rate, audio, percent) or an HTTP
# status code. `429` and `250 ms` are facts about the world, not about the code.
_UNITS_RE = re.compile(
    r"[~<>]?\d+(?:\.\d+)?\s?(?:ms|s\b|sec\b|seconds?\b|min\b|minutes?\b|hours?\b|days?\b|"
    r"KB|MB|MiB|GiB|kHz|Hz|bytes?\b|bit\b|-bit\b|%|px\b|rps\b|qps\b)|"
    r"\b[1-5]xx\b|\b(?:301|302|304|307|308|400|401|403|404|405|409|410|412|422|425|429|500|501|502|503|504)\b",
)

# S4 — a causal connective tying behaviour to a consequence. This is the shape
# of a *why*: the comment says what breaks if the code changes.
_CAUSAL_RE = re.compile(
    r"\b(?:because|otherwise|so that|or else|would (?:break|fail|race|deadlock|leak|clobber|loop|crash|page|stall)|"
    r"breaks?\b|so we don'?t|to avoid\b|caused\b|causes\b|gets? clobbered|"
    r"keeps? (?:us|it|them) from|doesn'?t\b.{0,24}\b(?:page|fire|break|leak|loop)|"
    r"eat into|would otherwise|trade-?offs?\b)\b",
    re.IGNORECASE,
)

# S5 — negation of the obvious, or a flagged deliberate deviation. "NOT a typo",
# "deliberately re-raises", "instead of the documented order".
_NEGATION_RE = re.compile(
    r"\b(?:must not|must never|do(?:es)? not\b|don'?t\b.{0,30}\b(?:leak|log|cache|retry|block|steal|wipe)|"
    r"never\b|deliberately|intentionally|counterintuitiv|NOT\b)|(?<!based )\bon purpose\b|"
    r"\(not\s|\binstead of\b|\brather than\b",
)

# S6 — upstream/vendor quirk, workaround provenance, or an external contract.
_UPSTREAM_RE = re.compile(
    r"\b(?:upstream|workaround|quirk|backport|vendored|regression|fixed upstream|"
    r"requires?\b|convention\b|rate.?limit|deprecat|opts? in(?:to)?\b|"
    r"raises?\b.{0,60}\b(?:when|if|unless)\b)",
    re.IGNORECASE,
)

# S7 — concurrency, ordering, or invariant vocabulary. Nothing in the code text
# can state "this must run before the lock is taken".
_INVARIANT_RE = re.compile(
    r"\b(?:invariant|idempotent|race\b|deadlock|re-?entran|atomic|thread-?safe|signal-?safe|"
    r"lexicographic(?:al(?:ly)?)?|monotonic|must (?:run|be|happen|come|stay|hit|converge|configure)|"
    r"before any\b|lost the (?:claim )?race)\b",
    re.IGNORECASE,
)

# S8 — security reasoning.
_SECURITY_RE = re.compile(
    r"\b(?:timing attack|constant-?time|replay|PII\b|redact|secret|injection|spoof|"
    r"fail-?closed|fail-?open|auth bypass|early-?exit timing)\b",
    re.IGNORECASE,
)

# S9 — a vendor proper noun with *ascribed behaviour* (possessive, or followed by
# a behavioural verb). A vendor name as the mere object of a narration verb
# ("Create the prompt for Gemini") carries nothing and is deliberately NOT
# protected — that distinction is what keeps the leak rate at ~1%.
_VENDOR_RE = re.compile(
    r"\b(?:GitHub|Slack|Twilio|LiveKit|Kamailio|Groq|OpenAI|Anthropic|Cloudflare|FastAPI|"
    r"Starlette|Sentry|Zoho|Salla|Ashby|Linear|BigQuery|Postgres|Neon|Drizzle|Vertex|Gemini|"
    r"Firestore|Stripe|Next\.js|React Compiler|pydantic|ruff|loguru|Lexical|Farasa|Orpheus|"
    r"Whisper|schemathesis)"
    r"(?:'s\b|\s+(?:requires?|returns?|expects?|allows?|rejects?|accepts?|sends?|caps?|"
    r"limits?|wraps?|silently|outputs?|stores?|treats?|doesn'?t|does not|won'?t|can'?t|"
    r"only|models)\b)",
)

_SIGNALS: dict[str, re.Pattern[str]] = {
    "ref": _REF_RE,
    "version": _VERSION_RE,
    "units": _UNITS_RE,
    "causal": _CAUSAL_RE,
    "negation": _NEGATION_RE,
    "upstream": _UPSTREAM_RE,
    "invariant": _INVARIANT_RE,
    "security": _SECURITY_RE,
    "vendor": _VENDOR_RE,
}


def protecting_signals(body: str) -> frozenset[str]:
    """Name every protected-class signal that matches `body`.

    Returns:
        The set of signal names; empty when nothing protects the comment.

    """
    return frozenset(name for name, pattern in _SIGNALS.items() if pattern.search(body))


def is_protected(body: str) -> bool:
    """Report whether a comment carries any protected-class signal.

    EXEMPTION FLOOR ONLY — see the module docstring. A False result is not
    evidence that the comment is worthless.

    Returns:
        True when at least one of the nine signals matches.

    """
    return any(pattern.search(body) for pattern in _SIGNALS.values())


def has_external_reference(body: str) -> bool:
    """Report whether a comment cites a ticket, URL, RFC/PEP/CVE, or issue number.

    Signal S1 on its own. A comment that names where the decision is recorded is
    doing the one thing the code cannot, and it is the signal that separates a
    scoping note with an owner ("EN-only for now — AR needs audio (PROD-249)")
    from an unowned admission ("hacky, fix later").

    Returns:
        True when the comment carries an external reference.

    """
    return bool(_REF_RE.search(body))


# --- tokenisation shared by the restatement detectors ----------------------

# Below this length an inflection strip would eat the word itself.
_MIN_STEM_LENGTH = 3

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Words that say nothing about *which* code a comment describes. Kept close to
# the prototype's list: shrinking it costs recall, growing it costs precision by
# letting a genuinely novel word be discounted.
STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "his",
        "her",
        "our",
        "your",
        "my",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "done",
        "doing",
        "has",
        "have",
        "had",
        "having",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "not",
        "no",
        "none",
        "to",
        "of",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "into",
        "onto",
        "out",
        "up",
        "down",
        "over",
        "under",
        "about",
        "as",
        "if",
        "then",
        "than",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "how",
        "why",
        "while",
        "we",
        "you",
        "they",
        "i",
        "he",
        "she",
        "them",
        "him",
        "us",
        "me",
        "also",
        "just",
        "only",
        "even",
        "still",
        "already",
        "again",
        "there",
        "here",
        "all",
        "any",
        "each",
        "every",
        "some",
        "via",
        "per",
        "etc",
        "eg",
        "ie",
        "vs",
        "need",
        "needs",
        "needed",
        "want",
        "wants",
        "make",
        "makes",
        "making",
        "let",
        "lets",
        "please",
        "note",
        "see",
        "above",
        "below",
    ]
)


def split_identifier(token: str) -> list[str]:
    """Split `snake_case` / `camelCase` / `SCREAMING_CASE` into lowercase parts.

    Returns:
        The identifier's word parts, lowercased.

    """
    parts: list[str] = []
    for chunk in token.split("_"):
        parts.extend(match.group(0).lower() for match in _CAMEL_RE.finditer(chunk))
    return [part for part in parts if part]


def stem(word: str) -> str:
    """Fold the common English inflections so `updates`/`updating` match `update`.

    The trailing-`e` strip is what makes the fold *symmetric*: without it
    `creates`/`creating` reduce to `creat` while `create` stays `create`, and the
    two never match — the shape that most often made a restatement look novel.

    Deliberately crude otherwise. A real stemmer would conflate more pairs, and
    every extra conflation is a chance to call a novel word a restatement.

    Returns:
        The stemmed word.

    """
    base = word
    for suffix in ("ing", "ied", "ies", "ers", "er", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM_LENGTH:
            base = word[: len(word) - len(suffix)]
            if suffix in {"ied", "ies"}:
                return base + "y"
            break
    if base.endswith("e") and len(base) - 1 >= _MIN_STEM_LENGTH:
        return base[:-1]
    return base


def content_tokens(text: str) -> list[str]:
    """Split prose into lowercase content words, dropping stopwords.

    Returns:
        The comment's content tokens, in order.

    """
    tokens: list[str] = []
    for match in _WORD_RE.finditer(text):
        tokens.extend(split_identifier(match.group(0)))
    return [token for token in tokens if token not in STOPWORDS]


def code_tokens(text: str) -> set[str]:
    """Collect every identifier part appearing in a slice of source.

    Returns:
        The lowercase identifier parts, as a set.

    """
    tokens: set[str] = set()
    for match in _WORD_RE.finditer(text):
        tokens.update(split_identifier(match.group(0)))
    return tokens


def restates(comment_tokens: Sequence[str], code: Iterable[str]) -> bool:
    """Report whether every content token of a comment already appears in the code.

    Exact or stemmed match only. Prefix matching is deliberately absent: it is
    what sank the first attempt at this shape (PR #98), where `service` matched
    `locationService` and drove the false-positive rate to ~60%.

    Returns:
        True when the comment adds no token the code does not already carry.

    """
    present = set(code)
    stems = {stem(token) for token in present}
    return all(token in present or stem(token) in stems for token in comment_tokens)


# --- one tokenize pass per file --------------------------------------------

_LAYOUT_TOKENS = frozenset({tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})
_NON_CODE_TOKENS = _LAYOUT_TOKENS | frozenset({tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER})

_Scan = tuple[list[tuple[int, int, str]], list[tuple[int, int, str]], set[int], int]

_last_scan: tuple[str, _Scan] | None = None


def _scan(source: str) -> _Scan:
    standalone: list[tuple[int, int, str]] = []
    trailing: list[tuple[int, int, str]] = []
    nested: set[int] = set()
    first_code_line = 1 << 30
    prev_end_row = 0
    depth = 0
    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type == tokenize.COMMENT:
            entry = (tok.start[0], tok.start[1], tok.string.lstrip("#").strip())
            (trailing if tok.start[0] == prev_end_row else standalone).append(entry)
            if depth > 0:
                nested.add(tok.start[0])
        elif tok.type == tokenize.OP:
            if tok.string in {"(", "[", "{"}:
                depth += 1
            elif tok.string in {")", "]", "}"}:
                depth = max(0, depth - 1)
        if tok.type not in _LAYOUT_TOKENS:
            prev_end_row = tok.end[0]
        if tok.type not in _NON_CODE_TOKENS:
            first_code_line = min(first_code_line, tok.start[0])
    return standalone, trailing, nested, first_code_line


def _scan_memo(source: str) -> _Scan:
    global _last_scan  # ruff: ignore[global-statement] — single-slot memo; the CLI runs rules per file sequentially
    if _last_scan is not None and _last_scan[0] is source:
        return _last_scan[1]
    result = _scan(source)
    _last_scan = (source, result)
    return result


def trailing_comments(source: str) -> list[tuple[int, int, str]]:
    """Return every comment that shares its line with code, as `(line, col, body)`.

    Raises out of here when `source` cannot be tokenized; see
    `standalone_comments`.

    Returns:
        The trailing comments, in source order.

    """
    return _scan_memo(source)[1]


def nested_comment_lines(source: str) -> set[int]:
    """Return the lines of comments sitting INSIDE a bracketed expression.

    A comment at bracket depth > 0 is annotating an element of a list, dict or
    call — `# config` inside pydantic's `__all__` groups the names beneath it —
    rather than signposting the structure of the file. Both readings produce the
    same one-word comment, and only the depth tells them apart.

    Returns:
        The line numbers of comments nested inside brackets.

    """
    return _scan_memo(source)[2]


def standalone_comments(source: str) -> tuple[list[tuple[int, int, str]], int]:
    """Return every own-line comment as `(line, col, body)`, plus the first code line.

    A comment is standalone when it is the only content on its line; `first code
    line` is the row of the first real code token (a large sentinel when the file
    has none). Memoized on the source *object* so the comment rules share one
    tokenize pass per file, as `rule_base.parse_or_none` does for the AST.

    A file the tokenizer rejects raises out of here rather than being silently
    treated as comment-free; every caller catches that and returns no
    diagnostics, because a rule has nothing useful to say about a file that does
    not parse.

    Returns:
        The standalone comments and the first code line's row.

    """
    standalone, _, _, first_code_line = _scan_memo(source)
    return standalone, first_code_line


def comment_runs(standalone: Sequence[tuple[int, int, str]]) -> list[list[tuple[int, int, str]]]:
    """Group standalone comments into runs of consecutive lines.

    Returns:
        One list per contiguous `#` block, in source order.

    """
    runs: list[list[tuple[int, int, str]]] = []
    for entry in sorted(standalone):
        if runs and entry[0] == runs[-1][-1][0] + 1:
            runs[-1].append(entry)
        else:
            runs.append([entry])
    return runs
