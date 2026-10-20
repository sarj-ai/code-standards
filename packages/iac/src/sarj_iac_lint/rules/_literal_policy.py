from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import TYPE_CHECKING

from sarj_iac_lint._hcl import Block, blocks, literal_string, strip_outer_parentheses, tokens


if TYPE_CHECKING:
    from collections.abc import Mapping

_JOIN_ARGUMENT_COUNT = 2
_MAX_LOCAL_ALIAS_DEPTH = 16
_MAX_STATIC_EXPRESSION_DEPTH = 32


@lru_cache(maxsize=32)
def balanced_blocks(source: str) -> tuple[Block, ...]:
    stack: list[str] = []
    closers = {"}": "{", "]": "[", ")": "("}
    for token in tokens(source):
        if token in {"{", "[", "("}:
            stack.append(token)
        elif token in closers and (not stack or stack.pop() != closers[token]):
            message = "unbalanced HCL delimiters"
            raise ValueError(message)
    if stack:
        message = "unclosed HCL delimiters"
        raise ValueError(message)
    return blocks(source)


def local_collections(top: tuple[Block, ...]) -> dict[str, str]:
    attributes = [attr for block in top if block.type == "locals" and not block.labels for attr in block.attributes]
    counts = Counter(attr.name for attr in attributes)
    return {attr.name: attr.value for attr in attributes if counts[attr.name] == 1}


def grant_roles(block: Block, collections: Mapping[str, str] | None = None) -> frozenset[str]:
    attr = block.attribute("role")
    if attr is None:
        return frozenset()
    value = attr.value.strip()
    literal = None if value.endswith(",") else _static_string(tokens(value), collections or {})
    if literal is not None:
        return frozenset({literal})
    if attr.value.strip() not in {"each.value", "each.key"} or (each := block.attribute("for_each")) is None:
        return frozenset()
    parts = _role_set_items(each.value, collections)
    values = [literal_string(part) for part in parts if part != ","]
    return frozenset(value for value in values if value is not None) if all(values) else frozenset()


def _static_string(
    parts: tuple[str, ...], local_values: Mapping[str, str], seen: frozenset[str] = frozenset(), depth: int = 0
) -> str | None:
    if depth >= _MAX_STATIC_EXPRESSION_DEPTH:
        return None
    parts = strip_outer_parentheses(parts)
    if len(parts) == 1:
        literal = literal_string(parts[0])
        if literal is not None:
            return literal
        alias = parts[0].removeprefix("local.") if parts[0].startswith("local.") else ""
        if alias in local_values and alias not in seen and len(seen) < _MAX_LOCAL_ALIAS_DEPTH:
            return _static_string(tokens(local_values[alias]), local_values, seen | {alias}, depth + 1)
        return None
    return _static_join(parts, local_values, seen, depth)


def _static_join(
    parts: tuple[str, ...], local_values: Mapping[str, str], seen: frozenset[str], depth: int
) -> str | None:
    if parts[:2] != ("join", "(") or parts[-1:] != (")",):
        return None
    arguments = _comma_parts(parts[2:-1])
    if len(arguments) != _JOIN_ARGUMENT_COUNT:
        return None
    separator = _static_string(arguments[0], local_values, seen, depth + 1)
    collection = arguments[1]
    if separator is None or collection[:1] != ("[",) or collection[-1:] != ("]",):
        return None
    elements = [_static_string(element, local_values, seen, depth + 1) for element in _comma_parts(collection[1:-1])]
    return (
        separator.join(element for element in elements if element is not None)
        if all(element is not None for element in elements)
        else None
    )


def _comma_parts(parts: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    values: list[tuple[str, ...]] = []
    start, depth = 0, 0
    for index, part in enumerate(parts):
        if part in {"(", "[", "{"}:
            depth += 1
        elif part in {")", "]", "}"}:
            depth -= 1
        elif part == "," and depth == 0:
            values.append(parts[start:index])
            start = index + 1
    if start < len(parts):
        values.append(parts[start:])
    return tuple(values)


def _role_set_items(expression: str, collections: Mapping[str, str] | None) -> tuple[str, ...]:
    parts = tokens(expression)
    as_set = parts[:2] == ("toset", "(") and parts[-1:] == (")",)
    if as_set:
        parts = parts[2:-1]
    if len(parts) == 1 and parts[0].startswith("local."):
        expression = collections.get(parts[0][len("local.") :], "") if collections is not None else ""
        parts = tokens(expression)
        local_set = parts[:2] == ("toset", "(") and parts[-1:] == (")",)
        if not as_set and not local_set:
            return ()
        if local_set:
            parts = parts[2:-1]
    if parts[:1] != ("[",) or parts[-1:] != ("]",):
        return ()
    return parts[1:-1]
