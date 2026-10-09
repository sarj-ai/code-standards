from __future__ import annotations

from functools import lru_cache

from sarj_iac_lint._hcl import Block, blocks, masked_hcl_lines, strip_inline_comment, tokens


@lru_cache(maxsize=32)
def balanced_blocks(source: str) -> tuple[Block, ...]:
    stack: list[str] = []
    closers = {"}": "{", "]": "[", ")": "("}
    for token in tokens("\n".join(strip_inline_comment(line) for line in masked_hcl_lines(source))):
        if token in {"{", "[", "("}:
            stack.append(token)
        elif token in closers and (not stack or stack.pop() != closers[token]):
            message = "unbalanced HCL delimiters"
            raise ValueError(message)
    if stack:
        message = "unclosed HCL delimiters"
        raise ValueError(message)
    return blocks(source)
