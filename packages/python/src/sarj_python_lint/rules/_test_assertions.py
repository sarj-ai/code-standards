from __future__ import annotations

import ast
import re


ASSERTION_NAME_RE = re.compile(r"(^|_)(assert|expect|verify|validate)", re.IGNORECASE)

RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

RAISES_NAMES = frozenset({"raises", "warns", "fail"})

LIBRARY_ASSERTION_NAMES = frozenset(
    {
        "fnmatch_lines",
        "fnmatch_lines_random",
        "no_fnmatch_line",
        "no_re_match_line",
        "re_match_lines",
        "re_match_lines_random",
        "eq_",
        "eq_ignore_whitespace",
        "eq_regex",
        "in_",
        "is_",
        "is_false",
        "is_instance_of",
        "is_none",
        "is_not",
        "is_not_",
        "is_not_none",
        "is_true",
        "ne_",
        "not_in",
        "not_in_",
    }
)

FLUENT_ATTRS = frozenset({"expect"})


def reads_as_verification(name: str) -> bool:
    return name in LIBRARY_ASSERTION_NAMES or bool(ASSERTION_NAME_RE.search(name) or RAISES_TOKEN_RE.search(name))


def names_verification(func: ast.expr, aliases: frozenset[str] = frozenset()) -> bool:
    if isinstance(func, ast.Name):
        return func.id in aliases or reads_as_verification(func.id)
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in RAISES_NAMES or reads_as_verification(func.attr):
        return True
    return _chain_has_fluent_marker(func.value)


def _chain_has_fluent_marker(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr in FLUENT_ATTRS:
            return True
        node = node.value
    return False
