from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import re
from typing import NamedTuple

from sarj_iac_lint.json_boundary import parse_json


_HEREDOC_RE = re.compile(r"<<-?\s*([A-Za-z_]\w*)")
_MAX_BLOCK_DEPTH = 128
_PARENTHESIS_PAIR_LENGTH = 2
_SURROGATE_START = 0xD800
_SURROGATE_END = 0xDFFF


def strip_inline_comment(line: str) -> str:
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


def heredoc_body_mask(lines: list[str]) -> tuple[bool, ...]:
    return _cached_heredoc_body_mask(tuple(lines))


def mask_block_comments(source: str) -> str:
    chars = list(source)
    in_string = False
    in_comment = False
    index = 0
    while index < len(chars):
        char = chars[index]
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if in_comment:
            if char == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                in_comment = False
                index += 2
                continue
            if char != "\n":
                chars[index] = " "
            index += 1
            continue
        if in_string:
            advanced = _advance_hcl_string(chars, index)
            index = advanced.index
            in_string = advanced.in_string
            continue
        if char == '"':
            in_string = True
        elif char == "/" and following == "*":
            chars[index] = chars[index + 1] = " "
            in_comment = True
            index += 2
            continue
        index += 1
    return "".join(chars)


def masked_hcl_lines(source: str) -> list[str]:
    output: list[str] = []
    in_block_comment = False
    heredoc_term: str | None = None
    for raw_line in source.splitlines():
        if heredoc_term is not None:
            output.append("")
            if raw_line.strip() == heredoc_term:
                heredoc_term = None
            continue
        masked = _mask_hcl_line_blocks(raw_line, in_block_comment=in_block_comment)
        in_block_comment = masked.in_block_comment
        output.append(masked.line)
        if (marker := _HEREDOC_RE.search(mask_line(masked.line))) is not None:
            heredoc_term = marker.group(1)
    return output


@lru_cache(maxsize=32)
def _cached_heredoc_body_mask(lines: tuple[str, ...]) -> tuple[bool, ...]:
    mask = [False] * len(lines)
    term: str | None = None
    for idx, line in enumerate(lines):
        if term is not None:
            if line.strip() == term:
                term = None
            else:
                mask[idx] = True
            continue
        if (m := _HEREDOC_RE.search(mask_line(line))) is not None:
            term = m.group(1)
    return tuple(mask)


# Tokenize strings (including interpolations), identifier paths, operators, and structural punctuation.
_TOKEN_RE = re.compile(
    # Keep the interpolation, escape, ordinary-dollar, and ordinary-character
    # branches disjoint so hostile strings cannot induce regex backtracking.
    r'"(?:\\.|\$\$\{|\$(?!\{|\$\{)|\$\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\}|[^"$\\])*"'
    r"|[A-Za-z_][\w.\-]*"
    r"|==|!=|<=|>=|&&|\|\||[{}()\[\]=,]"
    r"|\S"
)

_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


def tokens(text: str) -> tuple[str, ...]:
    return tuple(m.group(0) for m in _TOKEN_RE.finditer(text))


def strip_outer_parentheses(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) < _PARENTHESIS_PAIR_LENGTH or value[0] != "(" or value[-1] != ")":
        return value
    leading = 0
    while leading < len(value) and value[leading] == "(":
        leading += 1
    closing = [-1] * leading
    depth = 0
    for index, part in enumerate(value):
        if part == "(":
            depth += 1
        elif part == ")":
            depth -= 1
            if depth < 0:
                return value
            if depth < leading and closing[depth] == -1:
                closing[depth] = index
    if depth != 0:
        return value
    removed = 0
    while removed < leading and closing[removed] == len(value) - removed - 1:
        removed += 1
    return value[removed : len(value) - removed]


def ungrouped_expression(value: str) -> str:
    if not value.lstrip().startswith("("):
        return value
    matches = tuple(_TOKEN_RE.finditer(value))
    parts = tuple(match.group(0) for match in matches)
    unwrapped = strip_outer_parentheses(parts)
    removed = (len(parts) - len(unwrapped)) // _PARENTHESIS_PAIR_LENGTH
    if removed == 0:
        return value
    return value[matches[removed].start() : matches[-removed - 1].end()] if unwrapped else ""


def literal_token(value: str) -> str | None:
    parts = strip_outer_parentheses(tokens(value.strip().rstrip(",")))
    return parts[0] if len(parts) == 1 else None


_HCL_STRING_RE = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:[nrt"\\]|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}))*"')
_HCL_TEMPLATE_RE = re.compile(r"\$\$\{|%%\{|(?P<dynamic>\$\{|%\{)")
_HCL_ESCAPE_RE = re.compile(r'\\(?:[nrt"\\]|(?P<short>u[0-9A-Fa-f]{4})|(?P<long>U[0-9A-Fa-f]{8}))')


def literal_string(value: str) -> str | None:
    token = literal_token(value)
    if token is None or _HCL_STRING_RE.fullmatch(token) is None:
        return None
    if "${" in token or "%{" in token:
        if any(match.group("dynamic") is not None for match in _HCL_TEMPLATE_RE.finditer(token)):
            return None
        token = token.replace("$${", "${").replace("%%{", "%{")
    try:
        if "\\" not in token:
            return token[1:-1]
        normalized = _HCL_ESCAPE_RE.sub(_json_unicode_escape, token)
        decoded = parse_json(normalized)
    except ValueError, OverflowError:
        return None
    if not isinstance(decoded, str) or any(_SURROGATE_START <= ord(char) <= _SURROGATE_END for char in decoded):
        return None
    return decoded


def _json_unicode_escape(match: re.Match[str]) -> str:
    escape = match.group("short") or match.group("long")
    if escape is None:
        return match.group(0)
    codepoint = int(escape[1:], 16)
    if _SURROGATE_START <= codepoint <= _SURROGATE_END:
        msg = "HCL escapes must encode Unicode scalar values"
        raise ValueError(msg)
    return json.dumps(chr(codepoint))[1:-1] if escape.startswith("U") else match.group(0)


class _Tok(NamedTuple):
    text: str
    line: int  # 1-based
    col: int  # 1-based


@dataclass(frozen=True, slots=True)
class Attribute:
    name: str
    value: str
    line: int
    col: int
    value_line: int = 0


@dataclass(frozen=True, slots=True)
class Block:
    type: str
    labels: tuple[str, ...]
    depth: int  # 0 for a top-level block
    line: int
    col: int
    end_line: int
    attributes: tuple[Attribute, ...]
    blocks: tuple[Block, ...]

    def attribute(self, *names: str) -> Attribute | None:
        return next((a for a in self.attributes if a.name in names), None)

    def child(self, block_type: str) -> Block | None:
        return next((b for b in self.blocks if b.type == block_type), None)


class _BodyParseResult(NamedTuple):
    attributes: tuple[Attribute, ...]
    blocks: tuple[Block, ...]
    next_index: int


class _ValueParseResult(NamedTuple):
    value: str
    next_index: int
    line: int


@dataclass(frozen=True, slots=True)
class _MaskedLine:
    line: str
    in_block_comment: bool


@dataclass(frozen=True, slots=True)
class _StringAdvance:
    index: int
    in_string: bool


@lru_cache(maxsize=32)
def document(source: str) -> Block:
    lines = [strip_inline_comment(line) for line in masked_hcl_lines(source)]
    toks = [
        _Tok(m.group(0), lineno, m.start() + 1)
        for lineno, line in enumerate(lines, start=1)
        for m in _TOKEN_RE.finditer(line)
    ]
    parsed = _parse_body(toks, 0, 0, lines)
    return Block("", (), 0, 1, 1, max(len(lines), 1), parsed.attributes, parsed.blocks)


def blocks(source: str) -> tuple[Block, ...]:
    return document(source).blocks


def _parse_body(toks: list[_Tok], i: int, depth: int, lines: list[str]) -> _BodyParseResult:
    if depth > _MAX_BLOCK_DEPTH:
        msg = f"HCL nesting exceeds the supported depth of {_MAX_BLOCK_DEPTH}"
        raise ValueError(msg)
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
            parsed_value = _read_value(toks, j + 1, lines)
            i = parsed_value.next_index
            attrs.append(Attribute(head.text, parsed_value.value, head.line, head.col, parsed_value.line))
            continue
        labels: list[str] = []
        while j < len(toks) and (toks[j].text[:1].isalnum() or toks[j].text[:1] in {'"', "_"}):
            labels.append(_block_label(toks[j].text))
            j += 1
        if j < len(toks) and toks[j].text == "{":
            parsed_body = _parse_body(toks, j + 1, depth + 1, lines)
            i = parsed_body.next_index
            end = toks[i].line if i < len(toks) else toks[-1].line
            found.append(
                Block(
                    head.text,
                    tuple(labels),
                    depth,
                    head.line,
                    head.col,
                    end,
                    parsed_body.attributes,
                    parsed_body.blocks,
                )
            )
            i += 1
            continue
        i += 1
    return _BodyParseResult(tuple(attrs), tuple(found), i)


def _block_label(token: str) -> str:
    if not token.startswith('"'):
        return token
    label = literal_string(token)
    if label is None:
        msg = "HCL block labels must be static strings with valid escapes"
        raise ValueError(msg)
    return label


def _read_value(toks: list[_Tok], i: int, lines: list[str]) -> _ValueParseResult:
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
    value_line = toks[start].line if start < len(toks) else 0
    return _ValueParseResult(_rejoin(toks, start, i, lines), i, value_line)


def _rejoin(toks: list[_Tok], start: int, end: int, lines: list[str]) -> str:
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


def _mask_hcl_line_blocks(raw_line: str, *, in_block_comment: bool) -> _MaskedLine:
    chars = list(raw_line)
    in_string = False
    index = 0
    while index < len(chars):
        char = chars[index]
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if in_block_comment:
            if char == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                in_block_comment = False
                index += 2
                continue
            chars[index] = " "
        elif in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "/" and following == "*":
            chars[index] = chars[index + 1] = " "
            in_block_comment = True
            index += 2
            continue
        index += 1
    line = "".join(chars)
    return _MaskedLine(line=line, in_block_comment=in_block_comment)


def _advance_hcl_string(chars: list[str], index: int) -> _StringAdvance:
    if chars[index] == "\\":
        return _StringAdvance(index=index + 2, in_string=True)
    return _StringAdvance(index=index + 1, in_string=chars[index] != '"')
