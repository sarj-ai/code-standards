from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import io
import json
from pathlib import Path
import re
import tokenize
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Literal, assert_never

from sarj_standards.libs.repository import ledger

from .configs import LEGACY_ESLINT_SUPPRESSIONS, OXLINT_SUPPRESSIONS, TYPESCRIPT_SOURCE_SUFFIXES


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping


_CODE_SOURCE_SUFFIXES: Final = frozenset({".hcl", ".py", ".pyi", ".tf", ".tfvars"})
_SOURCE_SUFFIXES: Final = frozenset({*TYPESCRIPT_SOURCE_SUFFIXES, *_CODE_SOURCE_SUFFIXES})
_LINT_DIRECTIVE: Final = re.compile(
    r"(?P<intro>(?://|/\*)\s*(?:eslint|oxlint)-(?:disable(?:-next-line|-line)?|enable)\s+)"
    r"(?P<body>.*?)(?P<close>\s*\*/)?$"
)
_CODE_DIRECTIVE: Final = re.compile(r"(?P<intro>(?:#|//)\s*sarj-noqa:\s*)(?P<body>.*?)$")
_REASON: Final = re.compile(r"(?P<rules>.*?)(?P<reason>\s+(?:--|[–—])\s+.*)?$")
_LINT_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9_-]*"
_LINT_RULE_ID: Final = re.compile(rf"^(?:{_LINT_SEGMENT}|@?{_LINT_SEGMENT}(?:/{_LINT_SEGMENT})+)$")
_SARJ_CODE: Final = re.compile(r"^SARJ\d+$")
#: Oxlint keeps ESLint's bulk-suppression shape; repositories not yet migrated still carry the ESLint file.
_LINT_SUPPRESSIONS: Final = frozenset({LEGACY_ESLINT_SUPPRESSIONS, OXLINT_SUPPRESSIONS})
_RATCHET_SUPPRESSIONS: Final = "suppression-baseline.json"
_LINT_CONFIG_NAMES: Final = re.compile(r"^(?:eslint|oxlint)\.config\.(?:[cm]?[jt]s)$")
_PROPERTY_KEY_OFFSET: Final = 2
type _JavaScriptClosing = Literal[")", "]", "}"]


_JAVASCRIPT_CLOSING: Final[Mapping[str, _JavaScriptClosing]] = MappingProxyType({"(": ")", "[": "]", "{": "}"})


@dataclass(frozen=True, slots=True)
class Rewrite:
    path: Path
    contents: str


class _JavaScriptQuote(StrEnum):
    OUTSIDE = ""
    SINGLE = "'"
    DOUBLE = '"'
    TEMPLATE = "`"


class _HclQuote(StrEnum):
    OUTSIDE = ""
    SINGLE = "'"
    DOUBLE = '"'


@dataclass(frozen=True, slots=True)
class _CommentSpan:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _NoDirective:
    kind: ClassVar[Literal["none"]] = "none"


@dataclass(frozen=True, slots=True)
class _AmbiguousDirective:
    kind: ClassVar[Literal["ambiguous"]] = "ambiguous"


type _RuleTokens = tuple[str, *tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _ValidDirective:
    kind: ClassVar[Literal["valid"]] = "valid"
    tokens: _RuleTokens
    match: re.Match[str]
    reason: str


type _Directive = _NoDirective | _AmbiguousDirective | _ValidDirective


@dataclass(frozen=True, slots=True)
class _JavaScriptToken:
    kind: Literal["identifier", "punctuation", "string", "template"]
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _JavaScriptGroup:
    closing: Literal[")", "]"]
    eligible: bool
    role: ClassVar[Literal["container"]] = "container"


@dataclass(frozen=True, slots=True)
class _JavaScriptObject:
    role: Literal["config", "rules", "nested"]
    closing: ClassVar[Literal["}"]] = "}"
    eligible: ClassVar[Literal[False]] = False


type _JavaScriptFrame = _JavaScriptGroup | _JavaScriptObject


def supports(path: Path) -> bool:
    return path.suffix.lower() in _SOURCE_SUFFIXES


def plan(files: Iterable[Path]) -> tuple[Rewrite, ...]:
    shipped = ledger.load()
    lint = _replacements(shipped, ledger.OXLINT)
    codes = _replacements(shipped, ledger.CODE)
    lint_targets, code_targets = _targets(lint), _targets(codes)
    rewrites: list[Rewrite] = []
    for path in files:
        if not supports(path) and path.name not in {*_LINT_SUPPRESSIONS, _RATCHET_SUPPRESSIONS}:
            continue
        try:
            original = path.read_bytes().decode("utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if "sarj-doctor-ignore-retired-rules" in original:
            continue
        if path.name in _LINT_SUPPRESSIONS:
            migrated = _rewrite_lint_suppressions(original, lint)
        elif path.name == _RATCHET_SUPPRESSIONS:
            migrated = _rewrite_ratchet_suppressions(original, codes)
        else:
            targets = code_targets if path.suffix.lower() in _CODE_SOURCE_SUFFIXES else lint_targets
            migrated = _rewrite_lint_config_keys(path, rewrite_directives(path, original, targets), lint)
        if migrated != original:
            rewrites.append(Rewrite(path, migrated))
    return tuple(rewrites)


def retired_lint_targets() -> dict[str, tuple[str, ...]]:
    # Retired lint rule -> its replacement; empty when the rule was removed outright.
    return _targets(_replacements(ledger.load(), ledger.OXLINT))


def _replacements(shipped: ledger.Ledger, kind: str) -> dict[str, str | None]:
    active = shipped.active_ids()
    return {entry.id: _replacement(entry, active) for entry in shipped.retired if entry.kind == kind}


def _targets(replacements: Mapping[str, str | None]) -> dict[str, tuple[str, ...]]:
    return {rule: () if replacement is None else (replacement,) for rule, replacement in replacements.items()}


def reference_counts(path: Path, text: str, *, retired: tuple[ledger.Retired, ...] | None = None) -> dict[str, int]:
    if "sarj-doctor-ignore-retired-rules" in text:
        return {}
    retired = ledger.load().retired if retired is None else retired
    if not any(entry.id in text for entry in retired):
        return {}
    entries = {entry.id: entry for entry in retired}
    counts: dict[str, int] = {}
    spans = _comment_spans(path, text)
    for span in spans:
        comment = text[span.start : span.end]
        directive = _classify_directive(path, comment)
        match directive:
            case _ValidDirective():
                for token in directive.tokens:
                    if token in entries:
                        counts[token] = counts.get(token, 0) + 1
            case _AmbiguousDirective():
                _add_pattern_hits(counts, retired, comment)
            case _NoDirective():
                pass
            case _:
                assert_never(directive)

    # Mask comments to avoid counting directives twice when scanning config and fixture references.
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
    if entry.kind == ledger.OXLINT and not replacement.startswith("@sarj/"):
        return entry.id
    if entry.kind == ledger.CODE and _SARJ_CODE.fullmatch(replacement) is None:
        return entry.id
    return replacement


def _rewrite_lint_suppressions(text: str, retired: dict[str, str | None]) -> str:
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
    pass


def _rewrite_ratchet_suppressions(text: str, retired: dict[str, str | None]) -> str:
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    payload = text.removeprefix("\ufeff")
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
            payload, object_pairs_hook=_unique_object
        )
    except _DuplicateKeyError, json.JSONDecodeError:
        return text
    if not isinstance(parsed, _JsonObject):
        return text
    version = parsed.values.get("schema_version")
    budgets = parsed.values.get("codes")
    if type(version) is not int or version != 1 or not isinstance(budgets, _JsonObject):
        return text
    if any(type(count) is not int or count < 0 for count in budgets.values.values()):
        return text
    removed = {f"sarj-noqa:{code}" for code, replacement in retired.items() if replacement is None}
    obsolete = removed.intersection(budgets.values)
    nested_changed = _remove_retired_file_selector_budgets(parsed, removed)
    if not obsolete and not nested_changed:
        return text
    for key in obsolete:
        del budgets.values[key]  # sarj-noqa: SARJ442 — migration intentionally removes retired JSON keys in place
    line_ending = "\r\n" if "\r\n" in payload else "\n"
    trailing = line_ending if payload.endswith(("\n", "\r")) else ""
    rendered = json.dumps(parsed.values, default=_json_object_values, ensure_ascii=False, indent=2)
    rendered = rendered.replace("\n", line_ending)
    return f"{bom}{rendered}{trailing}"


def _remove_retired_file_selector_budgets(document: _JsonObject, removed: set[str]) -> bool:
    files = document.values.get("files")
    if not isinstance(files, _JsonObject):
        return False
    selectors = files.values.get("selectors")
    if not isinstance(selectors, _JsonObject):
        return False
    changed = False
    for path, raw_budgets in tuple(selectors.values.items()):
        if not isinstance(raw_budgets, _JsonObject):
            continue
        obsolete = removed.intersection(raw_budgets.values)
        for selector in obsolete:
            del raw_budgets.values[selector]  # sarj-noqa: SARJ442 — migration removes retired JSON keys in place
            changed = True
        if obsolete and not raw_budgets.values:
            del selectors.values[path]  # sarj-noqa: SARJ442 — migration removes empty JSON entries in place
    return changed


def _json_object_values(value: object) -> dict[str, _DecodedJsonValue]:
    if isinstance(value, _JsonObject):
        return value.values
    raise TypeError(type(value).__name__)


@dataclass(frozen=True, slots=True)
class _JsonObject:
    values: dict[str, _DecodedJsonValue]


type _DecodedJsonValue = str | int | float | bool | list[_DecodedJsonValue] | _JsonObject | None


def _unique_object(pairs: list[tuple[str, _DecodedJsonValue]]) -> _JsonObject:
    result: dict[str, _DecodedJsonValue] = {}
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


def rewrite_directives(path: Path, text: str, targets: Mapping[str, tuple[str, ...]]) -> str:
    # Each directive rule in `targets` becomes its target rules; one left with no rule is deleted.
    if "sarj-noqa:" not in text and "eslint-" not in text and "oxlint-" not in text:
        return text
    rewritten = text
    for span in reversed(_comment_spans(path, text)):
        comment = text[span.start : span.end]
        directive = _classify_directive(path, comment)
        if not isinstance(directive, _ValidDirective) or not any(token in targets for token in directive.tokens):
            continue
        replacement = _rewrite_valid_directive(directive, targets)
        if replacement:
            rewritten = f"{rewritten[: span.start]}{replacement}{rewritten[span.end :]}"
        elif not _is_jsx_comment_wrapper(path, text, span, comment):
            rewritten = _remove_directive_line(rewritten, span, span.start)
        elif (line := _jsx_comment_line(text, span)) is not None:
            # Deleting only the comment would leave an empty `{}` expression; a line holding
            # nothing but the wrapped comment goes whole. Inline wrappers stay.
            rewritten = f"{rewritten[: line[0]]}{rewritten[line[1] :]}"
    return rewritten


def _jsx_comment_line(text: str, span: _CommentSpan) -> tuple[int, int] | None:
    line_start = text.rfind("\n", 0, span.start) + 1
    line_end = text.find("\n", span.end)
    line_end = len(text) if line_end < 0 else line_end + 1
    before, after = text[line_start : span.start].strip(), text[span.end : line_end].strip()
    return (line_start, line_end) if (before, after) == ("{", "}") else None


def _remove_directive_line(rewritten: str, span: _CommentSpan, start: int) -> str:
    line_start = rewritten.rfind("\n", 0, start) + 1
    prefix = rewritten[line_start:start]
    trimmed = prefix.rstrip(" \t")
    end = span.end
    if not trimmed:
        if rewritten.startswith("\r\n", end):
            end += 2
        elif rewritten.startswith("\n", end):
            end += 1
    return f"{rewritten[:line_start]}{trimmed}{rewritten[end:]}"


def _rewrite_lint_config_keys(path: Path, text: str, retired: dict[str, str | None]) -> str:
    if _LINT_CONFIG_NAMES.fullmatch(path.name) is None:
        return text
    rewritten = text
    for retired_id, replacement in retired.items():
        if replacement is None or replacement == retired_id:
            continue
        matches = _lint_rule_property_keys(rewritten, retired_id)
        replacement_matches = _lint_rule_property_keys(rewritten, replacement)
        if matches is None or replacement_matches is None:
            return text
        if len(matches) != 1 or replacement_matches:
            continue
        start, end = matches[0]
        quote = rewritten[start]
        rewritten = f"{rewritten[:start]}{quote}{replacement}{quote}{rewritten[end:]}"
    return rewritten


def _lint_rule_property_keys(text: str, expected: str) -> tuple[tuple[int, int], ...] | None:
    tokens = _export_default_expression_tokens(text)
    if tokens is None:
        return None
    frames: list[_JavaScriptFrame] = []
    matches: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.kind == "punctuation" and token.value in {"(", "["}:
            frames.append(_javascript_group_frame(tokens, index, frames, token))
            continue
        if token.kind == "punctuation" and token.value == "{":
            frames.append(_javascript_object_frame(tokens, index, frames))
            continue
        if token.kind == "punctuation" and token.value in {")", "]", "}"}:
            if not frames or frames[-1].closing != token.value:
                return None
            frames.pop()
            continue
        if _is_expected_rule_key(tokens, index, frames, expected):
            matches.append((token.start, token.end))
    return tuple(matches) if not frames else None


def _javascript_object_frame(
    tokens: tuple[_JavaScriptToken, ...], index: int, frames: list[_JavaScriptFrame]
) -> _JavaScriptObject:
    previous = _previous_grammar_token(tokens, index)
    property_name = (
        tokens[index - _PROPERTY_KEY_OFFSET].value if index >= _PROPERTY_KEY_OFFSET and previous == ":" else None
    )
    parent_object = next((frame for frame in reversed(frames) if isinstance(frame, _JavaScriptObject)), None)
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
    return _JavaScriptObject(role=role)


def _javascript_group_frame(
    tokens: tuple[_JavaScriptToken, ...], index: int, frames: list[_JavaScriptFrame], token: _JavaScriptToken
) -> _JavaScriptGroup:
    previous = _previous_grammar_token(tokens, index)
    eligible = (frames[-1].eligible if frames else True) and previous != ":"
    return _JavaScriptGroup(")" if token.value == "(" else "]", eligible)


def _previous_grammar_token(tokens: tuple[_JavaScriptToken, ...], index: int) -> str | None:
    if not index:
        return "default"
    previous = tokens[index - 1]
    return previous.value if previous.kind in {"identifier", "punctuation"} else None


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
    return index + 1 < len(tokens) and tokens[index + 1].kind == "punctuation" and tokens[index + 1].value == ":"


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
    pending: list[_JavaScriptClosing] = []
    for token in tokens[anchors[0] + 2 :]:
        if token.kind == "punctuation" and token.value == ";" and not pending:
            break
        selected.append(token)
        if token.kind == "punctuation" and token.value in _JAVASCRIPT_CLOSING:
            pending.append(_JAVASCRIPT_CLOSING[token.value])
        elif (
            token.kind == "punctuation"
            and token.value in {")", "]", "}"}
            and (not pending or pending.pop() != token.value)
        ):
            return None
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
            end = _javascript_string_end(masked, index, character)
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


def _javascript_string_end(masked: str, index: int, character: str) -> int:
    end = index + 1
    while end < len(masked) and not (masked[end] == character and not _escaped(masked, end)):
        end += 1
    return end


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
    pattern = _CODE_DIRECTIVE if code else _LINT_DIRECTIVE
    markers = ("sarj-noqa",) if code else ("eslint-", "oxlint-")
    valid = _SARJ_CODE.fullmatch if code else _LINT_RULE_ID.fullmatch
    match = pattern.fullmatch(comment)
    if match is None:
        lowered = comment.lower()
        return _AmbiguousDirective() if any(marker in lowered for marker in markers) else _NoDirective()
    reason_match = _REASON.fullmatch(match.group("body"))
    if reason_match is None:
        return _AmbiguousDirective()
    tokens = _comma_delimited_tokens(reason_match.group("rules"), valid)
    if tokens is None:
        return _AmbiguousDirective()
    return _ValidDirective(tokens, match, reason_match.group("reason") or "")


def _comma_delimited_tokens(body: str, valid: Callable[[str], re.Match[str] | None]) -> _RuleTokens | None:
    raw = tuple(part.strip() for part in body.strip().split(","))
    if not raw or any(not token or valid(token) is None for token in raw):
        return None
    return raw[0], *raw[1:]


def _comment_spans(path: Path, text: str) -> tuple[_CommentSpan, ...]:
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyi"}:
        return _python_comment_spans(text)
    if suffix in {".hcl", ".tf", ".tfvars"}:
        return _hcl_comment_spans(text)
    return _javascript_comment_spans(text)


def _hcl_comment_spans(text: str) -> tuple[_CommentSpan, ...]:
    if "<<" in text:
        return ()
    spans = list(_javascript_comment_spans(text))
    masked = _mask_spans(text, tuple(spans))
    offset = 0
    for line in masked.splitlines(keepends=True):
        quote = _HclQuote.OUTSIDE
        for index, character in enumerate(line):
            if character in {'"', "'"} and (index == 0 or line[index - 1] != "\\"):
                quote = (
                    _HclQuote.OUTSIDE
                    if quote.value == character
                    else _HclQuote(character)
                    if quote is _HclQuote.OUTSIDE
                    else quote
                )
            elif character == "#" and quote is _HclQuote.OUTSIDE:
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
    quote = _JavaScriptQuote.OUTSIDE
    while index < len(text):
        char = text[index]
        if char == "\n":
            if quote in {_JavaScriptQuote.SINGLE, _JavaScriptQuote.DOUBLE}:
                quote = _JavaScriptQuote.OUTSIDE
            index += 1
            continue
        if quote is not _JavaScriptQuote.OUTSIDE:
            if char == quote.value and not _escaped(text, index):
                quote = _JavaScriptQuote.OUTSIDE
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = _JavaScriptQuote(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and not _escaped(text, index):
            end = _append_javascript_comment(text, index, spans)
            if end is not None:
                index = end
                continue
        index += 1
    return tuple(spans)


def _append_javascript_comment(text: str, index: int, spans: list[_CommentSpan]) -> int | None:
    following = text[index + 1]
    if following == "/":
        newline = text.find("\n", index + 2)
        end = len(text) if newline < 0 else newline - int(newline > 0 and text[newline - 1] == "\r")
        spans.append(_CommentSpan(index, end))
        return len(text) if newline < 0 else newline
    if following == "*":
        closing = text.find("*/", index + 2)
        if closing < 0:
            spans.append(_CommentSpan(index, len(text)))
            return len(text)
        spans.append(_CommentSpan(index, closing + 2))
        return closing + 2
    return None


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
        re.search(r"(?:eslint|oxlint)-(?:disable|enable)", normalized) is not None
        or "sarj-noqa" in normalized
        or "--rule" in normalized
        or re.search(r"[\"']@sarj/[^\"']+[\"']\s*:", line) is not None
        or re.search(r"^\s*(?:-\s*)?(?:id|entry)\s*:\s*.*sarj", line, re.IGNORECASE) is not None
    )


def _rewrite_valid_directive(directive: _ValidDirective, targets: Mapping[str, tuple[str, ...]]) -> str:
    match = directive.match
    migrated = tuple(dict.fromkeys(target for token in directive.tokens for target in targets.get(token, (token,))))
    if migrated:
        close = match.groupdict().get("close") or ""
        return f"{match.group('intro')}{', '.join(migrated)}{directive.reason}{close}"
    return ""
