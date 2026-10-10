from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from functools import lru_cache
import json
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from sarj_iac_lint.json_boundary import parse_json


if TYPE_CHECKING:
    from collections.abc import Mapping


_MAX_BLOCK_DEPTH = 128
_PARENTHESIS_PAIR_LENGTH = 2
_SURROGATE_START = 0xD800
_SURROGATE_END = 0xDFFF


class _InvalidHCLSourceError(ValueError):
    """Signal a lexical or header failure that cannot produce a shared document."""


class _Span(NamedTuple):
    kind: str
    start: int
    end: int
    body_start: int = 0
    body_end: int = 0


@dataclass(frozen=True, slots=True)
class _LexicalDocument:
    values: tuple[_Span, ...]
    comments: tuple[_Span, ...]
    newlines: tuple[int, ...]
    complete: bool
    physical_newlines: tuple[int, ...]


@dataclass(slots=True)
class _TemplateFrame:
    kind: str
    start: int
    marker: str = ""
    body_start: int = 0
    braces: int = 0


_HEREDOC_START_RE = re.compile(r"<<-?([^\W\d][\w-]*)\r?\n")


@dataclass(slots=True)
class _HCLScanner:
    source: str
    index: int = 0
    complete: bool = True
    values: list[_Span] = field(default_factory=list)
    comments: list[_Span] = field(default_factory=list)
    newlines: list[int] = field(default_factory=list)
    stack: list[_TemplateFrame] = field(default_factory=list)

    def scan(self) -> _LexicalDocument:
        while self.index < len(self.source):
            if len(self.stack) > _MAX_BLOCK_DEPTH:
                message = f"HCL nesting exceeds the supported depth of {_MAX_BLOCK_DEPTH}"
                raise ValueError(message)
            frame = self.stack[-1] if self.stack else None
            if frame is not None and frame.kind in {"string", "heredoc"}:
                self._template(frame)
            else:
                self._code(frame)
        if self.stack:
            self.complete = False
            frame = self.stack[0]
            self.values.append(_Span(frame.kind, frame.start, len(self.source), frame.body_start, len(self.source)))
        physical = tuple(match.start() for match in re.finditer(r"\n", self.source))
        return _LexicalDocument(tuple(self.values), tuple(self.comments), tuple(self.newlines), self.complete, physical)

    def _template(self, frame: _TemplateFrame) -> None:
        if frame.kind == "heredoc" and self._finish_heredoc(frame):
            return
        if frame.kind == "string" and self._quoted_character(frame):
            return
        if self.source.startswith(("$${", "%%{"), self.index):
            self.index += 3
            return
        if self.source.startswith(("${", "%{"), self.index):
            self.stack.append(_TemplateFrame("expression", self.index, braces=1))
            self.index += 2
            return
        self._advance_token()

    def _advance_token(self) -> None:
        match = _TOKEN_RE.match(self.source, self.index)
        self.index = match.end() if match is not None else self.index + 1

    def _quoted_character(self, frame: _TemplateFrame) -> bool:
        char = self.source[self.index]
        if char == "\\":
            self.index += 2
            return True
        if char == '"':
            self.stack.pop()
            self.index += 1
            if not self.stack:
                self.values.append(_Span("string", frame.start, self.index))
            return True
        if char in "\r\n":
            self.complete = False
        return False

    def _finish_heredoc(self, frame: _TemplateFrame) -> bool:
        if self.index != 0 and self.source[self.index - 1] != "\n":
            return False
        end = self.source.find("\n", self.index)
        if end == -1 or self.source[self.index : end].strip() != frame.marker:
            return False
        self.stack.pop()
        if not self.stack:
            self.values.append(_Span("heredoc", frame.start, end, frame.body_start, self.index))
        self.index = end
        return True

    def _code(self, frame: _TemplateFrame | None) -> None:
        if self._comment():
            return
        if self.source[self.index] == '"':
            self.stack.append(_TemplateFrame("string", self.index))
            self.index += 1
            return
        if self._begin_heredoc():
            return
        if frame is not None:
            self._expression_character(frame)
        elif self.source[self.index] == "\n":
            self.newlines.append(self.index)
        self._advance_token()

    def _begin_heredoc(self) -> bool:
        if not self.source.startswith("<<", self.index):
            return False
        marker = _HEREDOC_START_RE.match(self.source, self.index)
        if marker is None:
            return False
        self.stack.append(_TemplateFrame("heredoc", self.index, marker[1], marker.end()))
        self.index = marker.end()
        return True

    def _expression_character(self, frame: _TemplateFrame) -> None:
        char = self.source[self.index]
        if char == "{":
            frame.braces += 1
        elif char == "}":
            frame.braces -= 1
            if frame.braces == 0:
                self.stack.pop()

    def _comment(self) -> bool:
        if self.source.startswith(("#", "//"), self.index):
            end = self.source.find("\n", self.index)
            self._finish_comment("line-comment", len(self.source) if end == -1 else end)
            return True
        if not self.source.startswith("/*", self.index):
            return False
        end = self.source.find("*/", self.index + 2)
        if end == -1:
            self.complete = False
            end = len(self.source)
        else:
            end += 2
        self._finish_comment("block-comment", end)
        return True

    def _finish_comment(self, kind: str, end: int) -> None:
        if not self.stack:
            self.comments.append(_Span(kind, self.index, end))
        self.index = end


@lru_cache(maxsize=32)
def _lexical_document(source: str) -> _LexicalDocument:
    return _HCLScanner(source).scan()


def strip_inline_comment(line: str) -> str:
    lexical = _lexical_document(line)
    return next((line[: span.start] for span in lexical.comments if span.kind == "line-comment"), line)


def mask_line(line: str) -> str:
    lexical = _lexical_document(line)
    end = next((span.start for span in lexical.comments if span.kind == "line-comment"), len(line))
    output: list[str] = []
    start = 0
    for span in lexical.values:
        if span.start >= end:
            break
        output.extend((line[start : span.start], '""' if span.kind == "string" else line[span.start : span.body_start]))
        start = span.end
    output.append(line[start:end])
    return "".join(output)


def heredoc_body_mask(lines: list[str]) -> tuple[bool, ...]:
    return _cached_heredoc_body_mask(tuple(lines))


@lru_cache(maxsize=32)
def _cached_heredoc_body_mask(lines: tuple[str, ...]) -> tuple[bool, ...]:
    source = "\n".join(lines) + "\n"
    mask = [False] * len(lines)
    for span in _lexical_document(source).values:
        if span.kind != "heredoc":
            continue
        first = bisect_left(_lexical_document(source).physical_newlines, span.body_start)
        final = bisect_left(_lexical_document(source).physical_newlines, span.body_end)
        mask[first:final] = [True] * (final - first)
    return tuple(mask)


def _mask_spans(source: str, spans: tuple[_Span, ...]) -> str:
    chars = list(source)
    for span in spans:
        for index in range(span.start, span.end):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def mask_block_comments(source: str) -> str:
    comments = tuple(span for span in _lexical_document(source).comments if span.kind == "block-comment")
    return _mask_spans(source, comments)


def masked_hcl_lines(source: str) -> list[str]:
    lexical = _lexical_document(source)
    spans = tuple(span for span in lexical.comments if span.kind == "block-comment") + tuple(
        _Span("body", span.body_start, span.end) for span in lexical.values if span.kind == "heredoc"
    )
    return [line if line.strip() else "" for line in _mask_spans(source, spans).splitlines()]


@lru_cache(maxsize=32)
def suppression_comment_lines(source: str) -> Mapping[int, str]:
    output: dict[int, str] = {}
    lexical = _lexical_document(source)
    for span in lexical.comments:
        first = bisect_left(lexical.physical_newlines, span.start) + 1
        for offset, line in enumerate(source[span.start : span.end].splitlines()):
            number = first + offset
            output[number] = output.get(number, "") + line
    return MappingProxyType(output)


@lru_cache(maxsize=32)
def header_comment_lines(source: str, *, leading_only: bool = False) -> tuple[str, ...]:
    limit = 0
    for _ in range(20):
        newline = source.find("\n", limit)
        if newline < 0:
            limit = len(source)
            break
        limit = newline + 1
    lexical = _lexical_document(source[:limit])
    output: list[str] = []
    previous_end = 0
    for span in lexical.comments:
        if span.start >= limit:
            break
        if leading_only:
            if source[previous_end : span.start].strip():
                break
        else:
            line_index = bisect_left(lexical.physical_newlines, span.start)
            line_start = lexical.physical_newlines[line_index - 1] + 1 if line_index else 0
            if source[line_start : span.start].strip():
                continue
        output.extend(source[span.start : min(span.end, limit)].splitlines())
        previous_end = span.end
    return tuple(output)


# Strings and heredocs are opaque spans; this regex handles the remaining simple tokens.
_TOKEN_RE = re.compile(r"[A-Za-z_][\w.\-]*|==|!=|<=|>=|&&|\|\||[{}()\[\]=,]|\S")


def _token_spans(text: str) -> tuple[_Span, ...]:
    lexical = _lexical_document(text)
    if not lexical.complete:
        message = "incomplete HCL value or comment"
        raise _InvalidHCLSourceError(message)
    special = sorted((*lexical.values, *lexical.comments), key=lambda span: span.start)
    result: list[_Span] = []
    start = 0
    for span in special:
        result.extend(
            _Span("token", match.start(), match.end()) for match in _TOKEN_RE.finditer(text, start, span.start)
        )
        if span.kind == "string":
            result.append(span)
        elif span.kind == "heredoc":
            result.append(
                _Span(
                    "token",
                    span.start,
                    span.body_start - 1 - int(text[span.body_start - 2 : span.body_start] == "\r\n"),
                )
            )
        start = span.end
    result.extend(_Span("token", match.start(), match.end()) for match in _TOKEN_RE.finditer(text, start))
    return tuple(result)


def tokens(text: str) -> tuple[str, ...]:
    return tuple(text[span.start : span.end] for span in _token_spans(text))


_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


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
    matches = _token_spans(value)
    parts = tuple(value[match.start : match.end] for match in matches)
    unwrapped = strip_outer_parentheses(parts)
    removed = (len(parts) - len(unwrapped)) // _PARENTHESIS_PAIR_LENGTH
    if removed == 0:
        return value
    return value[matches[removed].start : matches[-removed - 1].end] if unwrapped else ""


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
    start: int
    end: int


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


@lru_cache(maxsize=32)
def document(source: str) -> Block:
    root_end = max(len(source.splitlines()), 1)
    try:
        return _parsed_document(source, root_end)
    except _InvalidHCLSourceError:
        return Block("", (), 0, 1, 1, root_end, (), ())


def _parsed_document(source: str, root_end: int) -> Block:
    lexical = _lexical_document(source)
    toks: list[_Tok] = []
    for span in _token_spans(source):
        offset = bisect_left(lexical.physical_newlines, span.start)
        previous = lexical.physical_newlines[offset - 1] if offset else -1
        toks.append(_Tok(source[span.start : span.end], offset + 1, span.start - previous, span.start, span.end))
    projected = _mask_spans(source, lexical.comments)
    parsed = _parse_body(toks, 0, 0, projected, lexical.newlines)
    return Block("", (), 0, 1, 1, root_end, parsed.attributes, parsed.blocks)


def blocks(source: str) -> tuple[Block, ...]:
    return document(source).blocks


def _parse_body(toks: list[_Tok], i: int, depth: int, source: str, newlines: tuple[int, ...]) -> _BodyParseResult:
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
            parsed_value = _read_value(toks, j + 1, source, newlines)
            i = parsed_value.next_index
            attrs.append(Attribute(head.text, parsed_value.value, head.line, head.col, parsed_value.line))
            continue
        header = _block_header(toks, i, newlines)
        if header is None:
            i += 1
            continue
        labels, brace = header
        parsed_body = _parse_body(toks, brace + 1, depth + 1, source, newlines)
        i = parsed_body.next_index
        end = toks[i].line if i < len(toks) else toks[-1].line
        found.append(
            Block(head.text, labels, depth, head.line, head.col, end, parsed_body.attributes, parsed_body.blocks)
        )
        i += 1
    return _BodyParseResult(tuple(attrs), tuple(found), i)


def _has_newline(newlines: tuple[int, ...], start: int, end: int) -> bool:
    return bisect_left(newlines, start) != bisect_left(newlines, end)


def _block_header(toks: list[_Tok], index: int, newlines: tuple[int, ...]) -> tuple[tuple[str, ...], int] | None:
    following = index + 1
    labels: list[str] = []
    while following < len(toks) and (toks[following].text[:1].isalnum() or toks[following].text[:1] in {'"', "_"}):
        labels.append(_block_label(toks[following].text))
        following += 1
    if following >= len(toks) or toks[following].text != "{":
        return None
    if _has_newline(newlines, toks[index].start, toks[following].start):
        message = "HCL block headers cannot contain structural newlines"
        raise _InvalidHCLSourceError(message)
    return tuple(labels), following


def _block_label(token: str) -> str:
    if not token.startswith('"'):
        return token
    label = literal_string(token)
    if label is None:
        msg = "HCL block labels must be static strings with valid escapes"
        raise ValueError(msg)
    return label


def _read_value(toks: list[_Tok], i: int, source: str, newlines: tuple[int, ...]) -> _ValueParseResult:
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
        if nest == 0 and (i >= len(toks) or _has_newline(newlines, tok.end, toks[i].start)):
            break
    value_line = toks[start].line if start < len(toks) else 0
    return _ValueParseResult(_rejoin(toks, start, i, source), i, value_line)


def _rejoin(toks: list[_Tok], start: int, end: int, source: str) -> str:
    parts: list[str] = []
    index = start
    while index < end:
        following = index + 1
        while following < end and toks[following].line == toks[index].line:
            following += 1
        parts.append(source[toks[index].start : toks[following - 1].end].strip())
        index = following
    return " ".join(parts)
