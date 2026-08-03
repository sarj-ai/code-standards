"""Shared docstring analysis for the docstring-ceremony rules (SARJ050/084/085/086)."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from sarj_python_lint.rules._comments import split_identifier, stem


if TYPE_CHECKING:
    from collections.abc import Iterable


# Docstring filler that says nothing about *which* thing is being described.
_BASE_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "are",
        "as",
        "at",
        "based",
        "be",
        "been",
        "being",
        "by",
        "class",
        "current",
        "do",
        "does",
        "false",
        "for",
        "from",
        "function",
        "get",
        "gets",
        "given",
        "helper",
        "if",
        "in",
        "instance",
        "instances",
        "into",
        "is",
        "it",
        "its",
        "method",
        "new",
        "object",
        "objects",
        "of",
        "on",
        "or",
        "provided",
        "return",
        "returned",
        "returns",
        "s",
        "set",
        "sets",
        "should",
        "specified",
        "that",
        "the",
        "these",
        "this",
        "those",
        "to",
        "true",
        "using",
        "value",
        "values",
        "was",
        "when",
        "whether",
        "which",
        "will",
        "with",
    }
)

# Qualifiers that NARROW NOTHING.
FILLER_QUALIFIERS = frozenset(
    {
        "actual",
        "already",
        "appropriate",
        "associated",
        "available",
        "basic",
        "correct",
        "correctly",
        "corresponding",
        "default",
        "desired",
        "entire",
        "existing",
        "full",
        "general",
        "necessary",
        "optional",
        "overall",
        "particular",
        "properly",
        "relevant",
        "required",
        "simple",
        "single",
        "specific",
        "standard",
        "successfully",
        "suitable",
        "supported",
        "various",
        "whole",
    }
)

STOPWORDS = _BASE_STOPWORDS | FILLER_QUALIFIERS

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*")

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Content the signature cannot carry, so the docstring is earning its place.
VALUE_MARKER_RE = re.compile(
    r"https?://|\bRFC\s?\d|:raises|\bRaises:|>>>|\bExamples?:|^\s*\.\. |"
    r"\b(?:ms|msec|milliseconds?|seconds?|secs?|minutes?|hours?|days?|bytes?|kb|mb|gb|hz|khz|"
    r"utc|iso.?8601|e\.?164|base64|utf-?8|px|dbfs?|db)\b|%",
    re.IGNORECASE | re.MULTILINE,
)

# Decorators that consume docstrings at runtime, where deleting prose would change behavior.
PROMPT_DECORATOR_MARKERS = frozenset(
    {
        "agent",
        "api_route",
        "app",
        "blueprint",
        "cli",
        "click",
        "command",
        "delete",
        "function_tool",
        "get",
        "group",
        "mcp",
        "option",
        "patch",
        "post",
        "put",
        "route",
        "router",
        "server",
        "tool",
        "tools",
        "typer",
        "websocket",
    }
)

# Google-style section headers, each alone on its line.
_SECTION_RE = re.compile(
    r"^[ \t]*(?P<name>Args|Arguments|Parameters|Params|Keyword Args|Keyword Arguments|"
    r"Returns|Return|Yields|Yield|Raises|Attributes|Example|Examples|Note|Notes|"
    r"Warning|Warnings|Warns|See Also|References|Todo|Other Parameters|Methods)\s*:[ \t]*$",
    re.MULTILINE,
)

# One `Args:` entry: `name (type): description`, with the type parenthesis
_ARG_ENTRY_RE = re.compile(r"^[ \t]+(?P<name>\*{0,2}[A-Za-z_]\w*)[ \t]*(?:\((?P<type>[^)]*)\))?[ \t]*:(?P<desc>.*)$")

ARG_SECTIONS = ("Args", "Arguments", "Parameters", "Params", "Keyword Args", "Keyword Arguments")


def sections(docstring: str) -> dict[str, str]:
    """Split a Google-style docstring into `{"summary": ..., "<Section>": ...}`."""
    marks = [(match.start(), match.end(), match.group("name")) for match in _SECTION_RE.finditer(docstring)]
    if not marks:
        return {"summary": docstring}
    out: dict[str, str] = {"summary": docstring[: marks[0][0]]}
    for index, (_, header_end, name) in enumerate(marks):
        body_end = marks[index + 1][0] if index + 1 < len(marks) else len(docstring)
        out[name] = out.get(name, "") + docstring[header_end:body_end]
    return out


def arg_section(docstring: str) -> str | None:
    """Return the parameter-documentation block of `docstring`, if it has one."""
    found = sections(docstring)
    for name in ARG_SECTIONS:
        if name in found:
            return found[name]
    return None


def arg_entries(block: str) -> list[tuple[str, str, str]]:
    """Parse an `Args:` block into `(name, type, description)` triples."""
    entries: list[list[str]] = []
    for raw in block.splitlines():
        match = _ARG_ENTRY_RE.match(raw)
        if match is not None:
            entries.append([match.group("name"), match.group("type") or "", match.group("desc").strip()])
        elif entries and raw.strip():
            entries[-1][2] += " " + raw.strip()
    return [(name, type_, desc) for name, type_, desc in entries]


def identifier_stems(text: str) -> set[str]:
    """Collect the stemmed word parts of every identifier in `text`."""
    return {stem(part) for match in _IDENTIFIER_RE.finditer(text) for part in split_identifier(match.group(0))}


def decorator_markers(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    """Collect the lowercase word parts of every decorator on `node`."""
    markers: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        try:
            markers.update(part.lower() for part in re.split(r"\W+", ast.unparse(target)) if part)
        except AttributeError, ValueError:  # pragma: no cover — unparse is total for these nodes
            continue
    return markers


def annotation_tokens(annotation: ast.expr | None) -> list[str]:
    """Split an annotation's rendered source into lowercase word parts."""
    if annotation is None:
        return []
    try:
        rendered = ast.unparse(annotation)
    except AttributeError, ValueError:  # pragma: no cover
        return []
    return [part for token in re.split(r"\W+", rendered) if token for part in split_identifier(token)]


def signature_stems(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> set[str]:
    """Collect every stem a reader can read off the signature."""
    tokens = list(split_identifier(node.name))
    if class_name is not None:
        tokens.extend(split_identifier(class_name))
    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
        if arg is None:
            continue
        if arg.arg not in {"self", "cls"}:
            tokens.extend(split_identifier(arg.arg))
        tokens.extend(annotation_tokens(arg.annotation))
    tokens.extend(annotation_tokens(node.returns))
    return {stem(token) for token in tokens}


def restates(text: str, known: Iterable[str]) -> bool:
    """Report whether every content word of `text` is already in `known`."""
    known_stems = set(known)
    words = [match.group(0).lower() for match in WORD_RE.finditer(text)]
    content = [word for word in words if word not in STOPWORDS]
    if not content:
        return False
    return all(stem(word) in known_stems for word in content)
