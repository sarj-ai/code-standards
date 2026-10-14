from __future__ import annotations

from functools import lru_cache

from sarj_iac_lint._hcl import Block, blocks, literal_string, tokens


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


def grant_roles(block: Block) -> frozenset[str]:
    attr = block.attribute("role")
    if attr is None:
        return frozenset()
    value = attr.value.strip()
    literal = None if value.endswith(",") else literal_string(value)
    if literal is not None:
        return frozenset({literal})
    if attr.value.strip() not in {"each.value", "each.key"} or (each := block.attribute("for_each")) is None:
        return frozenset()
    parts = tokens(each.value)
    if parts[:2] == ("toset", "(") and parts[-1:] == (")",):
        parts = parts[2:-1]
    if parts[:1] != ("[",) or parts[-1:] != ("]",):
        return frozenset()
    values = [literal_string(part) for part in parts[1:-1] if part != ","]
    return frozenset(value for value in values if value is not None) if all(values) else frozenset()
