"""Dependency-free partial HCL parsing that preserves positions for diagnostics and suppressions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import NamedTuple


_HEREDOC_RE = re.compile(r"<<-?\s*([A-Za-z_]\w*)")


def strip_inline_comment(line: str) -> str:
    """Truncate `line` at the first real `#`/`//` comment, ignoring ones in strings."""
    in_str = False
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == "#" or (c == "/" and i + 1 < n and line[i + 1] == "/"):
            return line[:i]
        i += 1
    return line


def mask_line(line: str) -> str:
    """Blank double-quoted string contents and drop comments, keeping structure."""
    out: list[str] = []
    in_str = False
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
                out.append('"')
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append('"')
        elif c == "#" or (c == "/" and i + 1 < n and line[i + 1] == "/"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def heredoc_body_mask(lines: list[str]) -> list[bool]:
    """Flag lines that reside inside heredoc bodies."""
    mask = [False] * len(lines)
    term: str | None = None
    for idx, line in enumerate(lines):
        if term is not None:
            if line.strip() == term:
                term = None
            else:
                mask[idx] = True
            continue
        m = _HEREDOC_RE.search(mask_line(line))
        if m is not None:
            term = m.group(1)
    return mask


# Tokenize strings (including interpolations), identifier paths, operators, and structural punctuation.
_TOKEN_RE = re.compile(
    # Keep the interpolation, escape, ordinary-dollar, and ordinary-character
    # branches disjoint so hostile strings cannot induce regex backtracking.
    r'"(?:\\.|\$(?!\{)|\$\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\}|[^"$\\])*"'
    r"|[A-Za-z_][\w.\-]*"
    r"|==|!=|<=|>=|&&|\|\||[{}()\[\]=,]"
    r"|\S"
)

_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


class _Tok(NamedTuple):
    text: str
    line: int  # 1-based
    col: int  # 1-based


@dataclass(frozen=True, slots=True)
class Attribute:
    """An `name = value` assignment, with `value` rejoined across lines."""

    name: str
    value: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Block:
    """An HCL block and its *direct* children (no flattening across nesting)."""

    type: str
    labels: tuple[str, ...]
    depth: int  # 0 for a top-level block
    line: int
    col: int
    end_line: int
    attributes: tuple[Attribute, ...]
    blocks: tuple[Block, ...]

    def attribute(self, *names: str) -> Attribute | None:
        """Find the first direct attribute named by `names`."""
        return next((a for a in self.attributes if a.name in names), None)

    def child(self, block_type: str) -> Block | None:
        """Find the first direct sub-block of type `block_type`."""
        return next((b for b in self.blocks if b.type == block_type), None)


def blocks(source: str) -> tuple[Block, ...]:
    """Parse `source` into a tree of top-level HCL blocks."""
    raw = source.splitlines()
    hmask = heredoc_body_mask(raw)
    lines = ["" if h else strip_inline_comment(ln) for ln, h in zip(raw, hmask, strict=True)]
    toks = [
        _Tok(m.group(0), lineno, m.start() + 1)
        for lineno, line in enumerate(lines, start=1)
        for m in _TOKEN_RE.finditer(line)
    ]
    _attrs, found, _i = _parse_body(toks, 0, 0, lines)
    return found


def _parse_body(
    toks: list[_Tok], i: int, depth: int, lines: list[str]
) -> tuple[tuple[Attribute, ...], tuple[Block, ...], int]:
    attrs: list[Attribute] = []
    found: list[Block] = []
    while i < len(toks):
        head = toks[i]
        if head.text == "}":
            break
        if not head.text[:1].isalpha() and head.text[:1] != "_":
            i += 1
            continue
        j = i + 1
        if j < len(toks) and toks[j].text == "=":
            value, i = _read_value(toks, j + 1, lines)
            attrs.append(Attribute(head.text, value, head.line, head.col))
            continue
        labels: list[str] = []
        while j < len(toks) and (toks[j].text[:1].isalnum() or toks[j].text[:1] in {'"', "_"}):
            labels.append(toks[j].text.strip('"'))
            j += 1
        if j < len(toks) and toks[j].text == "{":
            sub_attrs, sub_blocks, i = _parse_body(toks, j + 1, depth + 1, lines)
            end = toks[i].line if i < len(toks) else toks[-1].line
            found.append(Block(head.text, tuple(labels), depth, head.line, head.col, end, sub_attrs, sub_blocks))
            i += 1
            continue
        i += 1
    return tuple(attrs), tuple(found), i


def _read_value(toks: list[_Tok], i: int, lines: list[str]) -> tuple[str, int]:
    """Consume one attribute value, which may span lines inside `(`/`[`/`{`."""
    start, nest = i, 0
    while i < len(toks):
        tok = toks[i]
        if tok.text in _OPENERS:
            nest += 1
        elif tok.text in _CLOSERS:
            if nest == 0:
                break
            nest -= 1
        i += 1
        # A value ends at the line break only once every bracket has closed;
        # `deletion_protection = (\n  var.env == "prod"\n)` is one value.
        if nest == 0 and (i >= len(toks) or toks[i].line != tok.line):
            break
    return _rejoin(toks, start, i, lines), i


def _rejoin(toks: list[_Tok], start: int, end: int, lines: list[str]) -> str:
    """Splice source text spanned by `toks[start:end]`, one space per line break."""
    parts: list[str] = []
    i = start
    while i < end:
        j = i
        while j < end and toks[j].line == toks[i].line:
            j += 1
        first, last = toks[i], toks[j - 1]
        parts.append(lines[first.line - 1][first.col - 1 : last.col - 1 + len(last.text)].strip())
        i = j
    return " ".join(parts)
