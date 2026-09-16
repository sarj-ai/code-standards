from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


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
            if text[offset] != "\n":
                out[offset] = " "
        i = end
    return "".join(out)


def _quoted_sql_end(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] != quote:
            i += 1
            continue
        i += 1
        if i < len(text) and text[i] == quote:
            i += 1
            continue
        break
    return i


def _sql_noise_end(text: str, start: int, *, mask_dollar_quotes: bool) -> int | None:
    ch = text[start]
    if ch in {"'", '"'}:
        return _quoted_sql_end(text, start)
    if text.startswith("--", start) or (ch == "#" and (start == 0 or text[start - 1].isspace())):
        end = text.find("\n", start)
        return len(text) if end == -1 else end
    if text.startswith("/*", start):
        end = text.find("*/", start + 2)
        return len(text) if end == -1 else end + 2
    if mask_dollar_quotes and ch == "$":
        return _dollar_quote_end(text, start)
    return None


def _dollar_quote_end(text: str, start: int) -> int | None:
    delimiter_end = text.find("$", start + 1)
    if delimiter_end == -1:
        return None
    tag = text[start + 1 : delimiter_end]
    valid_tag = not tag or (
        (tag[0].isalpha() or tag[0] == "_") and all(char.isalnum() or char == "_" for char in tag[1:])
    )
    if not valid_tag:
        return None
    delimiter = text[start : delimiter_end + 1]
    close = text.find(delimiter, delimiter_end + 1)
    return None if close == -1 else close + len(delimiter)
