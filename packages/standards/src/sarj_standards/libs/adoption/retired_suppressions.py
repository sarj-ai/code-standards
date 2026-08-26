from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import io
import json
from pathlib import Path
import re
import tokenize
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.repository import ledger


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


_CODE_SOURCE_SUFFIXES: Final = frozenset({".hcl", ".py", ".pyi", ".tf", ".tfvars"})
_SOURCE_SUFFIXES: Final = frozenset(
    {".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx", *_CODE_SOURCE_SUFFIXES}
)
_ESLINT_DIRECTIVE: Final = re.compile(
    r"(?P<intro>(?://|/\*)\s*eslint-(?:disable(?:-next-line|-line)?|enable)\s+)"
    r"(?P<body>.*?)(?P<close>\s*\*/)?$"
)
_CODE_DIRECTIVE: Final = re.compile(r"(?P<intro>(?:#|//)\s*sarj-noqa:\s*)(?P<body>.*?)$")
_REASON: Final = re.compile(r"(?P<rules>.*?)(?P<reason>\s+(?:--|[–—])\s+.*)?$")
_ESLINT_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9_-]*"
_ESLINT_ID: Final = re.compile(rf"^(?:{_ESLINT_SEGMENT}|@?{_ESLINT_SEGMENT}(?:/{_ESLINT_SEGMENT})+)$")
_SARJ_CODE: Final = re.compile(r"^SARJ\d+$")
_ESLINT_SUPPRESSIONS: Final = "eslint-suppressions.json"
_ESLINT_CONFIG_NAMES: Final = re.compile(r"^eslint\.config\.(?:[cm]?[jt]s)$")
_PROPERTY_KEY_OFFSET: Final = 2
_JAVASCRIPT_CLOSING: Final = MappingProxyType({"(": ")", "[": "]", "{": "}"})


@dataclass(frozen=True, slots=True)
class Rewrite:
    path: Path
    contents: str


class _DirectiveState(Enum):
    NONE = auto()
    VALID = auto()
    AMBIGUOUS = auto()


@dataclass(frozen=True, slots=True)
class _CommentSpan:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Directive:
    state: _DirectiveState
    tokens: tuple[str, ...] = ()
    match: re.Match[str] | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class _JavaScriptToken:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _JavaScriptFrame:
    closing: str
    eligible: bool
    role: str = "container"


def supports(path: Path) -> bool:
    return path.suffix.lower() in _SOURCE_SUFFIXES


def plan(files: Iterable[Path]) -> tuple[Rewrite, ...]:
    shipped = ledger.load()
    retired = shipped.retired
    active = shipped.active_ids()
    eslint = {entry.id: _replacement(entry, active) for entry in retired if entry.kind == ledger.ESLINT}
    codes = {entry.id: _replacement(entry, active) for entry in retired if entry.kind == ledger.CODE}
    rewrites: list[Rewrite] = []
    for path in files:
        if not supports(path) and path.name != _ESLINT_SUPPRESSIONS:
            continue
        try:
            original = path.read_bytes().decode("utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if "sarj-doctor-ignore-retired-rules" in original:
            continue
        migrated = (
            _rewrite_eslint_suppressions(original, eslint)
            if path.name == _ESLINT_SUPPRESSIONS
            else _rewrite(path, original, eslint, codes)
        )
        if migrated != original:
            rewrites.append(Rewrite(path, migrated))
    return tuple(rewrites)


def reference_counts(path: Path, text: str) -> dict[str, int]:
    if "sarj-doctor-ignore-retired-rules" in text:
        return {}
    retired = ledger.load().retired
    entries = {entry.id: entry for entry in retired}
    counts: dict[str, int] = {}
    spans = _comment_spans(path, text)
    for span in spans:
        comment = text[span.start : span.end]
        directive = _classify_directive(path, comment)
        if directive.state is _DirectiveState.VALID:
            for token in directive.tokens:
                if token in entries:
                    counts[token] = counts.get(token, 0) + 1
        elif directive.state is _DirectiveState.AMBIGUOUS:
            _add_pattern_hits(counts, retired, comment)

    # Config objects and fixture strings can be reference sites too. Mask real
    # comments first so ordinary prose and already-classified directives are not
    # counted a second time.
    uncomments = _mask_spans(text, spans)
    for line in uncomments.splitlines():
        if not _looks_like_ambiguous_reference(line):
            continue
        _add_pattern_hits(counts, retired, line)
    return counts


def _add_pattern_hits(counts: dict[str, int], retired: tuple[ledger.Retired, ...], text: str) -> None:
    for entry in retired:
        hits = len(entry.pattern.findall(text))
        if hits:
            counts[entry.id] = counts.get(entry.id, 0) + hits


def _replacement(entry: ledger.Retired, active: frozenset[str]) -> str | None:
    if entry.status is ledger.Status.REMOVED:
        return None
    replacement = entry.replacement
    if replacement is None or replacement not in active:
        return entry.id
    if entry.kind == ledger.ESLINT and not replacement.startswith("@sarj/"):
        return entry.id
    if entry.kind == ledger.CODE and _SARJ_CODE.fullmatch(replacement) is None:
        return entry.id
    return replacement


def _rewrite_eslint_suppressions(text: str, retired: dict[str, str | None]) -> str:
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    payload = text.removeprefix("\ufeff")
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
            payload,
            object_pairs_hook=_unique_object,
        )
    except _DuplicateKeyError, json.JSONDecodeError:
        return text
    if not isinstance(parsed, _JsonObject):
        return text
    document: dict[str, dict[str, dict[str, int]]] = {}
    changed = False
    for file_name, raw_rules in parsed.values.items():
        if not isinstance(raw_rules, _JsonObject):
            return text
        rules: dict[str, dict[str, int]] = {}
        for rule_id, raw_budget in raw_rules.values.items():
            if (count := _suppression_count(raw_budget)) is None:
                return text
            target = retired.get(rule_id, rule_id)
            changed |= target != rule_id
            if target is None:
                continue
            existing = rules.get(target)
            rules[target] = {"count": count if existing is None else max(count, existing["count"])}
        document[file_name] = rules
    if not changed:
        return text
    line_ending = "\r\n" if "\r\n" in payload else "\n"
    trailing = line_ending if payload.endswith(("\n", "\r")) else ""
    rendered = json.dumps(document, ensure_ascii=False, indent=2).replace("\n", line_ending)
    return f"{bom}{rendered}{trailing}"


class _DuplicateKeyError(ValueError):
    """A JSON object repeated a key and therefore has no lossless object model."""


@dataclass(frozen=True, slots=True)
class _JsonObject:
    values: dict[str, object]


def _unique_object(pairs: list[tuple[str, object]]) -> _JsonObject:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return _JsonObject(result)


def _suppression_count(value: object) -> int | None:
    if not isinstance(value, _JsonObject) or set(value.values) != {"count"}:
        return None
    count = value.values.get("count")
    return count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None


def _rewrite(path: Path, text: str, eslint: dict[str, str | None], codes: dict[str, str | None]) -> str:
    rewritten = text
    for span in reversed(_comment_spans(path, text)):
        comment = text[span.start : span.end]
        if _is_jsx_comment_wrapper(path, text, span, comment):
            continue
        directive = _classify_directive(path, comment)
        if directive.state is not _DirectiveState.VALID:
            continue
        retired = codes if path.suffix.lower() in _CODE_SOURCE_SUFFIXES else eslint
        if not any(token in retired for token in directive.tokens):
            continue
        replacement = _rewrite_valid_directive(directive, retired)
        start = span.start
        if not replacement:
            line_start = rewritten.rfind("\n", 0, start) + 1
            prefix = rewritten[line_start:start]
            trimmed = prefix.rstrip(" \t")
            end = span.end
            if not trimmed:
                if rewritten.startswith("\r\n", end):
                    end += 2
                elif rewritten.startswith("\n", end):
                    end += 1
            rewritten = f"{rewritten[:line_start]}{trimmed}{rewritten[end:]}"
        else:
            rewritten = f"{rewritten[:start]}{replacement}{rewritten[span.end :]}"
    return _rewrite_eslint_config_keys(path, rewritten, eslint)


def _rewrite_eslint_config_keys(path: Path, text: str, retired: dict[str, str | None]) -> str:
    if _ESLINT_CONFIG_NAMES.fullmatch(path.name) is None:
        return text
    rewritten = text
    for retired_id, replacement in retired.items():
        if replacement is None or replacement == retired_id:
            continue
        matches = _eslint_rule_property_keys(rewritten, retired_id)
        replacement_matches = _eslint_rule_property_keys(rewritten, replacement)
        if matches is None or replacement_matches is None:
            return text
        if len(matches) != 1 or replacement_matches:
            continue
        start, end = matches[0]
        quote = rewritten[start]
        rewritten = f"{rewritten[:start]}{quote}{replacement}{quote}{rewritten[end:]}"
    return rewritten


def _eslint_rule_property_keys(text: str, expected: str) -> tuple[tuple[int, int], ...] | None:
    tokens = _export_default_expression_tokens(text)
    if tokens is None:
        return None
    frames: list[_JavaScriptFrame] = []
    matches: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.value in {"(", "["}:
            previous = tokens[index - 1].value if index else "default"
            eligible = (frames[-1].eligible if frames else True) and previous != ":"
            frames.append(_JavaScriptFrame(")" if token.value == "(" else "]", eligible))
            continue
        if token.value == "{":
            previous = tokens[index - 1].value if index else "default"
            property_name = (
                tokens[index - _PROPERTY_KEY_OFFSET].value
                if index >= _PROPERTY_KEY_OFFSET and previous == ":"
                else None
            )
            parent_object = next((frame for frame in reversed(frames) if frame.closing == "}"), None)
            if property_name == "rules" and parent_object is not None and parent_object.role == "config":
                role = "rules"
            elif (frames[-1].eligible if frames else True) and previous in {
                "default",
                "(",
                "[",
                ",",
            }:
                role = "config"
            else:
                role = "nested"
            frames.append(_JavaScriptFrame(closing="}", eligible=False, role=role))
            continue
        if token.value in {")", "]", "}"}:
            if not frames or frames[-1].closing != token.value:
                return None
            frames.pop()
            continue
        if _is_expected_rule_key(tokens, index, frames, expected):
            matches.append((token.start, token.end))
    return tuple(matches) if not frames else None


def _is_expected_rule_key(
    tokens: tuple[_JavaScriptToken, ...],
    index: int,
    frames: list[_JavaScriptFrame],
    expected: str,
) -> bool:
    token = tokens[index]
    if token.kind != "string" or token.value != expected:
        return False
    if not frames or frames[-1].role != "rules":
        return False
    return index + 1 < len(tokens) and tokens[index + 1].value == ":"


def _export_default_expression_tokens(text: str) -> tuple[_JavaScriptToken, ...] | None:
    tokens = _javascript_tokens(text)
    anchors = tuple(
        index
        for index in range(len(tokens) - 1)
        if tokens[index].kind == "identifier"
        and tokens[index].value == "export"
        and tokens[index + 1].kind == "identifier"
        and tokens[index + 1].value == "default"
    )
    if len(anchors) != 1:
        return None
    selected: list[_JavaScriptToken] = []
    depth = 0
    pending: list[str] = []
    for token in tokens[anchors[0] + 2 :]:
        if token.value == ";" and depth == 0:
            break
        selected.append(token)
        if token.value in _JAVASCRIPT_CLOSING:
            pending.append(_JAVASCRIPT_CLOSING[token.value])
            depth += 1
        elif token.value in {")", "]", "}"}:
            if not pending or pending.pop() != token.value:
                return None
            depth -= 1
    return tuple(selected) if not pending else None


def _javascript_tokens(text: str) -> tuple[_JavaScriptToken, ...]:
    masked = _mask_spans(text, _javascript_comment_spans(text))
    tokens: list[_JavaScriptToken] = []
    index = 0
    while index < len(masked):
        character = masked[index]
        if character.isspace():
            index += 1
            continue
        if character in {'"', "'", "`"}:
            end = index + 1
            while end < len(masked) and not (masked[end] == character and not _escaped(masked, end)):
                end += 1
            if end >= len(masked):
                return ()
            tokens.append(
                _JavaScriptToken(
                    "template" if character == "`" else "string",
                    masked[index + 1 : end],
                    index,
                    end + 1,
                )
            )
            index = end + 1
            continue
        if character.isalpha() or character in {"_", "$"}:
            end = index + 1
            while end < len(masked) and (masked[end].isalnum() or masked[end] in {"_", "$"}):
                end += 1
            tokens.append(_JavaScriptToken("identifier", masked[index:end], index, end))
            index = end
            continue
        tokens.append(_JavaScriptToken("punctuation", character, index, index + 1))
        index += 1
    return tuple(tokens)


def _is_jsx_comment_wrapper(path: Path, text: str, span: _CommentSpan, comment: str) -> bool:
    if path.suffix.lower() not in {".jsx", ".tsx"} or not comment.startswith("/*"):
        return False
    line_start = text.rfind("\n", 0, span.start) + 1
    line_end = text.find("\n", span.end)
    if line_end < 0:
        line_end = len(text)
    return text[line_start : span.start].rstrip().endswith("{") and text[span.end : line_end].lstrip().startswith("}")


def _classify_directive(path: Path, comment: str) -> _Directive:
    code = path.suffix.lower() in _CODE_SOURCE_SUFFIXES
    pattern = _CODE_DIRECTIVE if code else _ESLINT_DIRECTIVE
    marker = "sarj-noqa" if code else "eslint-"
    valid = _SARJ_CODE.fullmatch if code else _ESLINT_ID.fullmatch
    match = pattern.fullmatch(comment)
    if match is None:
        state = _DirectiveState.AMBIGUOUS if marker in comment.lower() else _DirectiveState.NONE
        return _Directive(state)
    reason_match = _REASON.fullmatch(match.group("body"))
    if reason_match is None:
        return _Directive(_DirectiveState.AMBIGUOUS)
    tokens = _comma_delimited_tokens(reason_match.group("rules"), valid)
    if not tokens:
        return _Directive(_DirectiveState.AMBIGUOUS)
    return _Directive(_DirectiveState.VALID, tokens, match, reason_match.group("reason") or "")


def _comma_delimited_tokens(body: str, valid: Callable[[str], object | None]) -> tuple[str, ...]:
    raw = tuple(part.strip() for part in body.strip().split(","))
    if not raw or any(not token or valid(token) is None for token in raw):
        return ()
    return raw


def _comment_spans(path: Path, text: str) -> tuple[_CommentSpan, ...]:
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyi"}:
        return _python_comment_spans(text)
    if suffix in {".hcl", ".tf", ".tfvars"}:
        return _hcl_comment_spans(text)
    return _javascript_comment_spans(text)


def _hcl_comment_spans(text: str) -> tuple[_CommentSpan, ...]:
    spans = list(_javascript_comment_spans(text))
    masked = _mask_spans(text, tuple(spans))
    offset = 0
    for line in masked.splitlines(keepends=True):
        quote: str | None = None
        for index, character in enumerate(line):
            if character in {'"', "'"} and (index == 0 or line[index - 1] != "\\"):
                quote = None if quote == character else character if quote is None else quote
            elif character == "#" and quote is None:
                spans.append(_CommentSpan(offset + index, offset + len(line.rstrip("\r\n"))))
                break
        offset += len(line)
    return tuple(sorted(spans, key=lambda item: item.start))


def _python_comment_spans(text: str) -> tuple[_CommentSpan, ...]:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        offsets = _line_offsets(text)
        return tuple(
            _CommentSpan(offsets[token.start[0] - 1] + token.start[1], offsets[token.end[0] - 1] + token.end[1])
            for token in tokens
            if token.type == tokenize.COMMENT
        )
    except IndentationError, SyntaxError, tokenize.TokenError:
        return ()


def _javascript_comment_spans(text: str) -> tuple[_CommentSpan, ...]:
    spans: list[_CommentSpan] = []
    index = 0
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if char == "\n":
            if quote in {"'", '"'}:
                quote = None
            index += 1
            continue
        if quote is not None:
            if char == quote and not _escaped(text, index):
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and not _escaped(text, index):
            following = text[index + 1]
            if following == "/":
                newline = text.find("\n", index + 2)
                end = len(text) if newline < 0 else newline - int(newline > 0 and text[newline - 1] == "\r")
                spans.append(_CommentSpan(index, end))
                index = len(text) if newline < 0 else newline
                continue
            if following == "*":
                closing = text.find("*/", index + 2)
                if closing < 0:
                    spans.append(_CommentSpan(index, len(text)))
                    return tuple(spans)
                spans.append(_CommentSpan(index, closing + 2))
                index = closing + 2
                continue
        index += 1
    return tuple(spans)


def _line_offsets(text: str) -> tuple[int, ...]:
    offsets = [0]
    offsets.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return tuple(offsets)


def _mask_spans(text: str, spans: tuple[_CommentSpan, ...]) -> str:
    masked = list(text)
    for span in spans:
        for index in range(span.start, span.end):
            if masked[index] not in {"\r", "\n"}:
                masked[index] = " "
    return "".join(masked)


def _escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _looks_like_ambiguous_reference(line: str) -> bool:
    normalized = line.lower()
    if "sarj" not in normalized:
        return False
    return (
        "eslint-disable" in normalized
        or "eslint-enable" in normalized
        or "sarj-noqa" in normalized
        or "--rule" in normalized
        or re.search(r"[\"']@sarj/[^\"']+[\"']\s*:", line) is not None
        or re.search(r"^\s*(?:-\s*)?(?:id|entry)\s*:\s*.*sarj", line, re.IGNORECASE) is not None
    )


def _rewrite_valid_directive(directive: _Directive, retired: dict[str, str | None]) -> str:
    match = directive.match
    if match is None:
        return ""
    migrated = tuple(
        dict.fromkeys(
            replacement for token in directive.tokens if (replacement := retired.get(token, token)) is not None
        )
    )
    if migrated:
        close = match.groupdict().get("close") or ""
        return f"{match.group('intro')}{', '.join(migrated)}{directive.reason}{close}"
    return ""
