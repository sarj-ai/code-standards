from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits

from sarj_iac_lint._hcl import document, physical_lines, strip_outer_parentheses, tokens


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_iac_lint._hcl import Attribute, Block
    from sarj_iac_lint.rule_base import Diagnostic


_DECIMAL = r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
_PLAIN_STRING = r'"[^"\\\x00-\x1f\uD800-\uDFFF]*"'
_TOKEN = re.compile(rf"[ \t]*(?P<token>true|false|{_DECIMAL}|{_PLAIN_STRING}|[()?:])")
_NUMBER = re.compile(rf"{_DECIMAL}\Z")
_TEMPLATE = re.compile(r"[$%]\{")
_MAX_TOKENS = 256
_MAX_DEPTH = 32
_MAX_EXPRESSION_LENGTH = 16_384
_MAX_NUMBER_LENGTH = 64
_MAX_EXPONENT = 100


class _ScalarKind(StrEnum):
    BOOLEAN = "boolean"
    NUMBER = "number"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class _Scalar:
    kind: _ScalarKind
    raw: str


@dataclass(frozen=True, slots=True)
class _Choice:
    condition: bool
    when_true: tuple[str, ...]
    when_false: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ChoiceBounds:
    question: int
    colon: int


def literal_conditional_edits(source: str, diagnostics: Sequence[Diagnostic]) -> list[TextEdit]:
    try:
        root = document(source)
    except ValueError:
        return []
    allowed = {(finding.line, finding.col) for finding in diagnostics}
    lines = physical_lines(source, keepends=True)
    edits: list[TextEdit] = []
    for block_index, block in enumerate(root.blocks):
        if block.type != "locals" or block.labels or block.depth != 0:
            continue
        for attribute_index, attribute in enumerate(block.attributes):
            if (attribute.line, attribute.col) not in allowed:
                continue
            edit = _attribute_edit(lines, attribute)
            if edit is not None and _matches_target_delta(
                source, root, edit, block_index=block_index, attribute_index=attribute_index
            ):
                edits.append(edit)
    return edits


def _attribute_edit(lines: list[str], attribute: Attribute) -> TextEdit | None:
    if not 1 <= attribute.line <= len(lines) or attribute.value_line != attribute.line:
        return None
    line = lines[attribute.line - 1]
    assignment = re.fullmatch(
        rf"[ \t]*(?P<name>{re.escape(attribute.name)})[ \t]*=[ \t]*"
        r"(?P<expression>.*?)(?P<trailing>[ \t]*)(?:\r?\n)?",
        line,
    )
    if assignment is None or assignment.start("name") + 1 != attribute.col:
        return None
    expression = assignment.group("expression")
    if len(expression) > _MAX_EXPRESSION_LENGTH or tokens(expression) != tokens(attribute.value):
        return None
    parts = _scan(expression)
    scalar = None if parts is None else _fold(parts)
    if scalar is None:
        return None
    offset = sum(map(len, lines[: attribute.line - 1]))
    return TextEdit(
        offset + assignment.start("expression"),
        offset + assignment.end("expression"),
        scalar.raw,
    )


def _scan(expression: str) -> tuple[str, ...] | None:
    parts: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            return tuple(parts) if not expression[position:].strip(" \t") else None
        token = match.group("token")
        if _TEMPLATE.search(token):
            return None
        parts.append(token)
        if len(parts) > _MAX_TOKENS:
            return None
        position = match.end()
    return tuple(parts)


def _fold(parts: tuple[str, ...], depth: int = 0) -> _Scalar | None:
    if depth >= _MAX_DEPTH:
        return None
    parts = strip_outer_parentheses(parts)
    if len(parts) == 1:
        return _scalar(parts[0])
    choice = _choice(parts)
    if choice is None:
        return None
    when_true = _fold(choice.when_true, depth + 1)
    when_false = _fold(choice.when_false, depth + 1)
    if when_true is None or when_false is None or when_true.kind is not when_false.kind:
        return None
    return when_true if choice.condition else when_false


def _scalar(token: str) -> _Scalar | None:
    if token in {"true", "false"}:
        return _Scalar(kind=_ScalarKind.BOOLEAN, raw=token)
    if token.startswith('"'):
        return _Scalar(kind=_ScalarKind.STRING, raw=token)
    if _NUMBER.fullmatch(token) is None or len(token) > _MAX_NUMBER_LENGTH:
        return None
    exponent = re.search(r"[eE]([+-]?[0-9]+)\Z", token)
    if exponent is not None and abs(int(exponent[1])) > _MAX_EXPONENT:
        return None
    return _Scalar(kind=_ScalarKind.NUMBER, raw=token)


def _choice(parts: tuple[str, ...]) -> _Choice | None:
    bounds = _choice_bounds(parts)
    if bounds is None:
        return None
    condition = strip_outer_parentheses(parts[: bounds.question])
    if condition not in {("true",), ("false",)}:
        return None
    return _Choice(
        condition=condition == ("true",),
        when_true=parts[bounds.question + 1 : bounds.colon],
        when_false=parts[bounds.colon + 1 :],
    )


def _choice_bounds(parts: tuple[str, ...]) -> _ChoiceBounds | None:
    depth = pending = 0
    question: int | None = None
    for index, part in enumerate(parts):
        if part == "(":
            depth += 1
        elif part == ")":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and part == "?":
            if question is None:
                question = index
            pending += 1
        elif depth == 0 and part == ":" and pending:
            pending -= 1
            if pending == 0 and question is not None:
                return _ChoiceBounds(question=question, colon=index)
    return None


def _matches_target_delta(source: str, root: Block, edit: TextEdit, *, block_index: int, attribute_index: int) -> bool:
    block = root.blocks[block_index]
    attributes = tuple(
        replace(attribute, value=edit.replacement) if index == attribute_index else attribute
        for index, attribute in enumerate(block.attributes)
    )
    blocks = tuple(
        replace(candidate, attributes=attributes) if index == block_index else candidate
        for index, candidate in enumerate(root.blocks)
    )
    expected = replace(root, blocks=blocks)
    try:
        actual = document(apply_edits(source, (edit,)))
    except ValueError:
        return False
    return actual == expected
