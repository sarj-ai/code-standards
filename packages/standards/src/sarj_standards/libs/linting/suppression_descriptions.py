from __future__ import annotations

import ast
import io
import re
import tokenize


# Only existing coded, inline directives have a description boundary. Preserve
# the prefix byte for byte, including family, spelling, whitespace and code order.
_PREFIX = re.compile(
    r"(?:#[ ]*type:[ ]*ignore\[[a-zA-Z][a-zA-Z0-9_-]*(?:[ ]*,[ ]*[a-zA-Z][a-zA-Z0-9_-]*)*\]"
    r"|#[ ]*noqa:[ ]*[A-Za-z][A-Za-z0-9_-]*(?:[ ]*,[ ]*[A-Za-z][A-Za-z0-9_-]*)*)"
)
_REASON = re.compile(r"[ ]+(?:—|--)[ ]+[^#\[\]\\\r\n]{1,2048}\Z")
_CHECKER = re.compile(
    r"\b(?:noqa|ignore|type|ruff|flake8|pyright|basedpyright|mypy|pyre|pytype|pylint|"
    r"fmt|isort|yapf|autopep8|nosec|bandit|semgrep|pragma|disable|enable|coding)\b|\bnosem|:",
    re.IGNORECASE,
)


def equivalent(before: str, after: str) -> bool:
    if before == after:
        return False
    try:
        # Validate both sources, including actual type comments. TypeIgnore.tag
        # contains trailing prose, so comparing or erasing arbitrary tags is unsafe.
        ast.parse(before, type_comments=True)
        ast.parse(after, type_comments=True)
        return _without_descriptions(before) == _without_descriptions(after)
    except SyntaxError, ValueError, tokenize.TokenError, IndentationError:
        return False


def _without_descriptions(source: str) -> str:
    lines = io.StringIO(source).readlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        row, column = token.start
        if not lines[row - 1][:column].strip():
            continue
        match = _PREFIX.match(token.string)
        if match is None:
            continue
        reason = token.string[match.end() :]
        if reason and not _description(reason):
            continue
        # Token positions identify real comments, never string/docstring lookalikes.
        line = lines[row - 1]
        lines[row - 1] = line[:column] + match.group() + line[token.end[1] :]
    return "".join(lines)


def _description(reason: str) -> bool:
    return (
        _REASON.fullmatch(reason) is not None
        and _CHECKER.search(reason) is None
        and all(character.isprintable() for character in reason)
    )
