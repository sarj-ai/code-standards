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
    return path.name == "store.py" or path.name.endswith("_store.py") or "stores" in path.parts


def sql_string_value(node: ast.expr) -> str | None:
    """Reconstruct static SQL text, replacing runtime template holes with `?`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("?")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = sql_string_value(node.left)
        right = sql_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "SQL" and node.args:
            return sql_string_value(node.args[0])
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return sql_string_value(node.func.value)
    return None


def top_level_words(sql: str) -> list[tuple[str, int]]:
    """Return SQL words outside parentheses after values/comments are masked."""
    masked = strip_sql_noise(sql)
    words: list[tuple[str, int]] = []
    depth = 0
    i = 0
    while i < len(masked):
        char = masked[i]
        if char == "(":
            depth += 1
            i += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and (char.isalnum() or char == "_"):
            start = i
            i += 1
            while i < len(masked) and (masked[i].isalnum() or masked[i] == "_"):
                i += 1
            words.append((masked[start:i].upper(), start))
            continue
        i += 1
    return words


def has_top_level_phrase(sql: str, *phrase: str) -> bool:
    """Return whether consecutive top-level words equal `phrase`."""
    wanted = tuple(word.upper() for word in phrase)
    words = [word for word, _ in top_level_words(sql)]
    return any(tuple(words[i : i + len(wanted)]) == wanted for i in range(len(words) - len(wanted) + 1))


def has_top_level_row_cap(sql: str) -> bool:
    """Return whether LIMIT/FETCH caps the whole result, excluding ClickHouse LIMIT BY."""
    words = [word for word, _ in top_level_words(sql)]
    if any(words[index : index + 2] in (["FETCH", "FIRST"], ["FETCH", "NEXT"]) for index in range(len(words) - 1)):
        return True
    boundaries = {"FETCH", "FOR", "FORMAT", "INTO", "LIMIT", "OFFSET", "SETTINGS", "UNION"}
    for index, word in enumerate(words):
        if word != "LIMIT":
            continue
        end = next(
            (cursor for cursor in range(index + 1, len(words)) if words[cursor] in boundaries),
            len(words),
        )
        clause = words[index + 1 : end]
        if "BY" not in clause and (not clause or clause[0] not in {"ALL", "NULL"}):
            return True
    return False


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
