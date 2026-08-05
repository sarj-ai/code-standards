"""Shared comment analysis for the comment-hygiene rules (SARJ016/049/050/051)."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import TYPE_CHECKING, NamedTuple

from sarj_python_lint.rule_base import parse_or_none
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path


# S1 — external references: URLs, tickets, RFCs, PEPs, CVEs, issues, and handles.
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

# S3 — numbers carrying units or HTTP status codes.
_UNITS_RE = re.compile(
    r"[~<>]?\d+(?:\.\d+)?\s?(?:ms|s\b|sec\b|seconds?\b|min\b|minutes?\b|hours?\b|days?\b|"
    r"KB|MB|MiB|GiB|kHz|Hz|bytes?\b|bit\b|-bit\b|%|px\b|rps\b|qps\b)|"
    r"\b[1-5]xx\b|\b(?:301|302|304|307|308|400|401|403|404|405|409|410|412|422|425|429|500|501|502|503|504)\b",
)

# S4 — a causal connective tying behaviour to a consequence.
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

# S7 — concurrency, ordering, or invariant vocabulary.
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

# S9 — vendor names only when paired with ascribed behavior, not mere narration.
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

# These measured high-precision signals are exemption-only; their absence never licenses deletion.


def is_protected(body: str) -> bool:
    """Apply an exemption floor; absence of a signal does not prove prose is worthless."""
    return any(pattern.search(body) for pattern in _SIGNALS.values())


def has_external_reference(body: str) -> bool:
    """Report whether a comment cites a ticket, URL, RFC/PEP/CVE, or issue number."""
    return bool(_REF_RE.search(body))


# Below this length an inflection strip would eat the word itself.
_MIN_STEM_LENGTH = 3

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Words that say nothing about *which* code a comment describes.
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
    """Split `snake_case` / `camelCase` / `SCREAMING_CASE` into lowercase parts."""
    parts: list[str] = []
    for chunk in token.split("_"):
        parts.extend(match.group(0).lower() for match in _CAMEL_RE.finditer(chunk))
    return [part for part in parts if part]


def stem(word: str) -> str:
    """Fold the common English inflections so `updates`/`updating` match `update`."""
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
    """Split prose into lowercase content words, dropping stopwords."""
    tokens: list[str] = []
    for match in _WORD_RE.finditer(text):
        tokens.extend(split_identifier(match.group(0)))
    return [token for token in tokens if token not in STOPWORDS]


def code_tokens(text: str) -> set[str]:
    """Collect every identifier part appearing in a slice of source."""
    tokens: set[str] = set()
    for match in _WORD_RE.finditer(text):
        tokens.update(split_identifier(match.group(0)))
    return tokens


def restates(comment_tokens: Sequence[str], code: Iterable[str]) -> bool:
    """Report whether every content token of a comment already appears in the code."""
    # Prefix matching is intentionally absent because it made unrelated identifiers look equivalent.
    present = set(code)
    stems = {stem(token) for token in present}
    return all(token in present or stem(token) in stems for token in comment_tokens)


_LAYOUT_TOKENS = frozenset({tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})
_NON_CODE_TOKENS = _LAYOUT_TOKENS | frozenset({tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER})

# `(line, col0, body, standalone)` for every comment, in source order.
_Ordered = list[tuple[int, int, str, bool]]


class _CommentScan[T](NamedTuple):
    comments: T
    first_code_line: int


_Scan = tuple[list[tuple[int, int, str]], list[tuple[int, int, str]], set[int], int, _Ordered]

_last_scan: tuple[str, _Scan] | None = None


def _scan(source: str) -> _Scan:
    standalone: list[tuple[int, int, str]] = []
    trailing: list[tuple[int, int, str]] = []
    ordered: _Ordered = []
    nested: set[int] = set()
    first_code_line = 1 << 30
    prev_end_row = 0
    depth = 0
    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type == tokenize.COMMENT:
            body = tok.string.lstrip("#").strip()
            entry = (tok.start[0], tok.start[1], body)
            is_standalone = tok.start[0] != prev_end_row
            (standalone if is_standalone else trailing).append(entry)
            ordered.append((tok.start[0], tok.start[1], body, is_standalone))
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
    return standalone, trailing, nested, first_code_line, ordered


def all_comments(source: str) -> _CommentScan[_Ordered]:
    """Return every comment as `(line, col0, body, standalone)`, plus the first code line."""
    _, _, _, first_code_line, ordered = _scan_memo(source)
    return _CommentScan(ordered, first_code_line)


def _scan_memo(source: str) -> _Scan:
    global _last_scan  # ruff: ignore[global-statement] — single-slot memo; the CLI runs rules per file sequentially
    if _last_scan is not None and _last_scan[0] is source:
        return _last_scan[1]
    result = _scan(source)
    _last_scan = (source, result)
    return result


def trailing_comments(source: str) -> list[tuple[int, int, str]]:
    """Return every comment that shares its line with code, as `(line, col, body)`."""
    return _scan_memo(source)[1]


def nested_comment_lines(source: str) -> set[int]:
    """Return the lines of comments sitting INSIDE a bracketed expression."""
    return _scan_memo(source)[2]


def standalone_comments(source: str) -> _CommentScan[list[tuple[int, int, str]]]:
    """Return every own-line comment as `(line, col, body)`, plus the first code line."""
    standalone, _, _, first_code_line, _ = _scan_memo(source)
    return _CommentScan(standalone, first_code_line)


def comment_runs(standalone: Sequence[tuple[int, int, str]]) -> list[list[tuple[int, int, str]]]:
    """Group standalone comments into runs of consecutive lines."""
    runs: list[list[tuple[int, int, str]]] = []
    for entry in sorted(standalone):
        if runs and entry[0] == runs[-1][-1][0] + 1:
            runs[-1].append(entry)
        else:
            runs.append([entry])
    return runs


# A comment wall is judged as a block, not as an isolated sentence.
_WALL_MIN_STATEMENTS = 4
_WALL_MIN_COMMENTS = 3
_WALL_MIN_COMMENTED_RATIO = 0.6
_WALL_MIN_WEAK_RATIO = 0.75
_WALL_MAX_WORDS = 18
_WALL_MIN_CONTENT_WORDS = 1
_WALL_MIN_MATCHED_RATIO = 0.5
_WALL_MAX_NOVEL_WORDS = 2
_WALL_DIRECTIVE_RE = re.compile(
    r"^(?:todo|fixme|hack\b|xxx|note:|nb:|warning:|important:|noqa|sarj-noqa|"
    r"type:|pragma|pyright|mypy|fmt:|isort|ruff|pylint|flake8|nosec|nosemgrep|"
    r"-\*-|!/|coding[:=])",
    re.IGNORECASE,
)
_WALL_NARRATION_RE = re.compile(
    r"^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|now|finally|lastly|"
    r"add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|"
    r"count|create|declare|define|delete|extract|fetch|filter|find|format|generate|get|"
    r"handle|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|print|"
    r"process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|"
    r"start|stop|store|update|validate|wrap|write|apply|assemble|coerce|compress|"
    r"disable|enable|lint|populate|prepare|redirect|register|resolve|run|stash|use)\b",
    re.IGNORECASE,
)
_WALL_STATEMENTS = (
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Assert,
    ast.Delete,
    ast.Expr,
    ast.Raise,
    ast.Return,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    ast.Try,
    ast.TryStar,
)


def _is_wall_statement(node: ast.stmt) -> bool:
    """Exclude docstrings while retaining executable expression statements."""
    return isinstance(node, _WALL_STATEMENTS) and not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    )


def _weak_walkthrough_comment(body: str, statement: str) -> bool:
    """Whether a comment is weak evidence inside a repeated walkthrough."""
    if (
        not body
        or body.endswith("?")
        or len(body.split()) > _WALL_MAX_WORDS
        or _WALL_DIRECTIVE_RE.match(body)
        or is_protected(body)
    ):
        return False
    words = content_tokens(body)
    if len(words) < _WALL_MIN_CONTENT_WORDS or not _WALL_NARRATION_RE.match(body):
        return False
    # The opener names the operation; the remaining words must mostly match the statement.
    known = code_tokens(statement)
    described = words[1:]
    if not described:
        return restates(words, known)
    matched = sum(1 for word in described if restates([word], known))
    novel = len(described) - matched
    return matched / len(described) >= _WALL_MIN_MATCHED_RATIO and novel <= _WALL_MAX_NOVEL_WORDS


def _owned_statement_lists(owner: ast.AST) -> tuple[list[ast.stmt], ...]:
    """Return the distinct statement blocks directly owned by an AST node."""
    if isinstance(
        owner,
        (
            ast.Module,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.With,
            ast.AsyncWith,
            ast.ExceptHandler,
        ),
    ):
        return (owner.body,)
    if isinstance(owner, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return owner.body, owner.orelse
    if isinstance(owner, (ast.Try, ast.TryStar)):
        return owner.body, owner.orelse, owner.finalbody
    if isinstance(owner, ast.match_case):
        return (owner.body,)
    return ()


def statement_comment_walls(
    path: Path,
    source: str,
    standalone: Sequence[tuple[int, int, str]],
) -> dict[int, frozenset[int]]:
    """Return `{leader: member lines}` for repeated statement narration walls."""
    tree = parse_or_none(path, source)
    if tree is None:
        return {}
    comments = {line: (col, body) for line, col, body in standalone}
    walls: dict[int, frozenset[int]] = {}
    for owner in nodes(tree, ast.AST):
        for value in _owned_statement_lists(owner):
            statements = [item for item in value if _is_wall_statement(item)]
            if len(statements) < _WALL_MIN_STATEMENTS:
                continue
            attached: list[tuple[int, int, bool]] = []
            for index, statement in enumerate(statements):
                entry = comments.get(statement.lineno - 1)
                if entry is None or entry[0] != statement.col_offset:
                    continue
                line = statement.lineno - 1
                segment = ast.get_source_segment(source, statement) or ""
                attached.append((index, line, _weak_walkthrough_comment(entry[1], segment)))
            clusters: list[list[tuple[int, int, bool]]] = []
            for item in attached:
                if clusters and item[0] <= clusters[-1][-1][0] + 2:
                    clusters[-1].append(item)
                else:
                    clusters.append([item])
            for cluster in clusters:
                span = cluster[-1][0] - cluster[0][0] + 1
                weak = [line for _index, line, is_weak in cluster if is_weak]
                if (
                    span < _WALL_MIN_STATEMENTS
                    or len(weak) < _WALL_MIN_COMMENTS
                    or len(cluster) / span < _WALL_MIN_COMMENTED_RATIO
                    or len(weak) / len(cluster) < _WALL_MIN_WEAK_RATIO
                ):
                    continue
                leader = min(weak)
                walls[leader] = frozenset(weak)
    return walls
