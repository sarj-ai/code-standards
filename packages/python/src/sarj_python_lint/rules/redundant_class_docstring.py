"""SARJ085 — A class docstring that only re-spells the class name.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_redundant_class_docstring.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._comments import is_protected, split_identifier
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    decorator_markers,
    identifier_stems,
    restates,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Preserve subclass docstrings that become machine-readable schema descriptions.
_SCHEMA_BASES = frozenset(
    {
        "BaseModel",
        "BaseSettings",
        "RootModel",
        "TypedDict",
        "Enum",
        "EnumMeta",
        "Flag",
        "IntEnum",
        "IntFlag",
        "ReprEnum",
        "StrEnum",
    }
)

# `@pydantic.dataclasses.dataclass` and `@strawberry.type` place the docstring in
# a schema the same way a `BaseModel` subclass does.
_SCHEMA_DECORATOR_MARKERS = frozenset({"pydantic", "strawberry", "graphene", "msgspec"})


def _base_names(node: ast.ClassDef) -> list[str]:
    """Render each base as its final dotted part."""
    names: list[str] = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, ast.Name):
            names.append(target.id)
    return names


class RedundantClassDocstring(Rule):
    id: str = "redundant-class-docstring"
    code: str = "SARJ085"
    description: str = (
        "Class docstring only re-spells the class name — delete it, or say what "
        "the name cannot: the invariant, the lifetime, the thing it is not."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.ClassDef):
            if self._is_ceremony(node):
                expr = node.body[0]
                diags.append(
                    Diagnostic(
                        path=path,
                        line=expr.lineno,
                        col=expr.col_offset + 1,
                        code=self.code,
                        message=self.description,
                    )
                )
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _is_ceremony(node: ast.ClassDef) -> bool:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return False
        if len(node.body) == 1:
            return False  # the docstring IS the body; deleting it leaves a syntax error
        bases = _base_names(node)
        if _SCHEMA_BASES.intersection(bases):
            return False
        markers = decorator_markers(node)
        if markers & PROMPT_DECORATOR_MARKERS or markers & _SCHEMA_DECORATOR_MARKERS:
            return False
        known = {*identifier_stems(node.name)}
        for base in bases:
            known |= identifier_stems(base)
        known |= {part for base in bases for part in split_identifier(base)}
        return restates(docstring, known)
