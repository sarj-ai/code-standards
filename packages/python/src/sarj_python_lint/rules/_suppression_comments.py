"""Shared comment tokenizer for the suppression-directive rules (SARJ038, SARJ054).

Comments do not survive `ast.parse`, so any rule that judges a suppression
*comment* has to lex the file. Both suppression rules need the same three facts
about every comment — its text, whether it stands alone on its line, and whether
it precedes the module's first statement — so they share one scanner rather than
drifting apart on what "file-level" means.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import io
import tokenize


# Sentinel row for "this file has no statement at all" (empty / comments-only):
# every comment then counts as preceding the first statement.
_NO_STATEMENT_LINE = 1 << 30

_LAYOUT_TOKENS = frozenset({tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})
_NON_STATEMENT_TOKENS = _LAYOUT_TOKENS | frozenset({tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER})


@dataclass(frozen=True, slots=True)
class Comment:
    """One comment token, with the context that decides whether it is file-level."""

    line: int
    col: int
    body: str
    standalone: bool
    before_first_statement: bool = False


_last_scan: tuple[str, list[Comment]] | None = None


def scan_comments(source: str) -> list[Comment]:
    """Tokenize `source` and describe every comment in it.

    A comment is standalone when no token ended on its line before it, and
    precedes the first statement when it sits above the first non-comment,
    non-layout token.

    Anything `tokenize` cannot lex propagates as `tokenize.TokenError`,
    `IndentationError` or `SyntaxError`; callers treat that as "no diagnostics".

    Memoized in a single slot, like `_comments._scan_memo` and
    `rule_base.parse_or_none`: both suppression rules ask the same question about
    the same file, and the CLI runs rules per file, so one slot removes the
    second tokenize pass. `Comment` is frozen and the returned list is read-only
    to callers.

    Returns:
        Every comment, in source order.

    """
    global _last_scan  # ruff: ignore[global-statement] — single-slot memo; the CLI runs rules per file sequentially
    if _last_scan is not None and _last_scan[0] is source:
        return _last_scan[1]
    result = _scan(source)
    _last_scan = (source, result)
    return result


def _scan(source: str) -> list[Comment]:
    comments: list[Comment] = []
    first_statement_line = _NO_STATEMENT_LINE
    prev_end_row = 0
    readline = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type == tokenize.COMMENT:
            comments.append(
                Comment(
                    line=tok.start[0],
                    col=tok.start[1] + 1,
                    body=comment_body(tok.string),
                    standalone=tok.start[0] != prev_end_row,
                )
            )
        if tok.type not in _LAYOUT_TOKENS:
            prev_end_row = tok.end[0]
        if tok.type not in _NON_STATEMENT_TOKENS:
            first_statement_line = min(first_statement_line, tok.start[0])
    return [replace(c, before_first_statement=c.line < first_statement_line) for c in comments]


def comment_body(raw: str) -> str:
    """Strip a comment token down to its directive text.

    Returns:
        The comment text without its leading `#` markers or surrounding space.

    """
    return raw.lstrip("#").strip()
