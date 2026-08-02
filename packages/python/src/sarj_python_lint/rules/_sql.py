"""Extract executable SQL while masking quoted values and comments."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


def is_store_module(path: Path) -> bool:
    """Return whether a non-test path belongs to the store layer."""
    if is_test_path(path):
        return False
    return path.name.endswith("_store.py") or "stores" in path.parts


def sql_string_value(node: ast.expr) -> str | None:
    """Reconstruct a (possibly `+`-concatenated) string literal, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = sql_string_value(node.left)
        right = sql_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def strip_sql_noise(text: str) -> str:
    """Mask SQL values and comments without changing text or line lengths."""
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in {"'", '"'}:
            out[i] = " "
            i += 1
            while i < n:
                c = text[i]
                if c == ch:
                    if i + 1 < n and text[i + 1] == ch:
                        out[i] = out[i + 1] = " "
                        i += 2
                        continue
                    out[i] = " "
                    i += 1
                    break
                if c != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
                if i < n:
                    out[i] = " "
                    i += 1
            continue
        i += 1
    return "".join(out)
