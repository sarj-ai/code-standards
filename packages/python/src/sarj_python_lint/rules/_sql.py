from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SQL_LINE_END = re.compile(r"[\r\n]")
_CONTINUED_QUOTE = re.compile(r"[ \t\f\v]*(?:--[^\r\n]*)?[\r\n](?:[ \t\f\v\r\n]|--[^\r\n]*[\r\n])*'")
POSTGRES_IDENTIFIER_CONTINUATION = r"[A-Za-z0-9_$\u0080-\U0010ffff]"
POSTGRES_UNQUOTED_IDENTIFIER = rf"[A-Za-z_\u0080-\U0010ffff]{POSTGRES_IDENTIFIER_CONTINUATION}*"
SQL_WHITESPACE = " \t\r\n\f\v"
_IDENTIFIER_CONTINUATION = re.compile(POSTGRES_IDENTIFIER_CONTINUATION)
_DOLLAR_DELIMITER = re.compile(r"\$(?:[A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_\u0080-\U0010ffff]*)?\$")


def is_store_module(path: Path) -> bool:
    if is_test_path(path):
        return False
    return path.name == "store.py" or path.name.endswith("_store.py") or "stores" in path.parts


def sql_string_value(node: ast.expr, *, interpolation_placeholder: str = " ") -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = sql_string_value(node.left, interpolation_placeholder=interpolation_placeholder)
        right = sql_string_value(node.right, interpolation_placeholder=interpolation_placeholder)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                # Keep static SQL tokens on either side adjacent while ensuring
                # an interpolation can never manufacture SELECT/FROM/* itself.
                pieces.append(interpolation_placeholder)
            else:  # pragma: no cover - the parser emits only these two forms
                return None
        return "".join(pieces)
    return None


def strip_sql_noise(
    text: str,
    *,
    mask_dollar_quotes: bool = True,
    mask_double_quotes: bool = True,
    preserve_quoted_tokens: bool = False,
) -> str:
    out = list(text)
    i = 0
    while i < len(text):
        if text[i] == '"' and not mask_double_quotes:
            i = _quoted_sql_end(text, i)
            continue
        end = _sql_noise_end(text, i, mask_dollar_quotes=mask_dollar_quotes)
        if end is None:
            i += 1
            continue
        for offset in range(i, end):
            if text[offset] not in {"\n", "\r"}:
                out[offset] = " "
        if preserve_quoted_tokens and text[i] in {"'", '"', "$"}:
            out[i] = "?"
        i = end
    return "".join(out)


def _quoted_sql_end(text: str, start: int) -> int:
    quote = text[start]
    escape_string = (
        quote == "'"
        and start > 0
        and text[start - 1] in {"E", "e"}
        and (start == 1 or _IDENTIFIER_CONTINUATION.match(text, start - 2) is None)
    )
    i = start + 1
    while i < len(text):
        if escape_string and text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] != quote:
            i += 1
            continue
        i += 1
        if i < len(text) and text[i] == quote:
            i += 1
            continue
        if escape_string and (continuation := _CONTINUED_QUOTE.match(text, i)) is not None:
            i = continuation.end()
            continue
        break
    return i


def _sql_noise_end(text: str, start: int, *, mask_dollar_quotes: bool) -> int | None:
    ch = text[start]
    if ch in {"'", '"'}:
        return _quoted_sql_end(text, start)
    if text.startswith("--", start) or (ch == "#" and (start == 0 or text[start - 1].isspace())):
        end = _SQL_LINE_END.search(text, start)
        return len(text) if end is None else end.start()
    if text.startswith("/*", start):
        return _block_comment_end(text, start)
    if mask_dollar_quotes and ch == "$":
        return _dollar_quote_end(text, start)
    return None


def _block_comment_end(text: str, start: int) -> int:
    depth = 1
    i = start + 2
    while i < len(text) and depth:
        if text.startswith("/*", i):
            depth += 1
            i += 2
        elif text.startswith("*/", i):
            depth -= 1
            i += 2
        else:
            i += 1
    return i


def _dollar_quote_end(text: str, start: int) -> int | None:
    if start > 0 and _IDENTIFIER_CONTINUATION.match(text, start - 1) is not None:
        return None
    match = _DOLLAR_DELIMITER.match(text, start)
    if match is None:
        return None
    delimiter = match[0]
    close = text.find(delimiter, match.end())
    return None if close == -1 else close + len(delimiter)
