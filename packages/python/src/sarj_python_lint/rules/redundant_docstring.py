"""SARJ050 — A docstring that only re-spells the signature it sits under.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_redundant_docstring.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    decorator_markers,
    restates,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# `restates` ignores digit-leading tokens, so a novel literal number needs its
# own guard instead of being mistaken for a pure signature restatement.
_DIGITS_RE = re.compile(r"\d+")


def _numeric_content(node: ast.FunctionDef | ast.AsyncFunctionDef, docstring: str, class_name: str | None) -> bool:
    """Return whether the docstring names a number absent from the signature."""
    in_docstring = set(_DIGITS_RE.findall(docstring))
    if not in_docstring:
        return False
    return not in_docstring <= set(_DIGITS_RE.findall(_signature_text(node, class_name)))


def _signature_text(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> str:
    """Render the owning class, function, parameters, and annotations."""
    parts: list[str] = [node.name]
    if class_name is not None:
        parts.append(class_name)
    args = node.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
        if arg is None:
            continue
        parts.append(arg.arg)
        if arg.annotation is not None:
            parts.append(ast.unparse(arg.annotation))
    if node.returns is not None:
        parts.append(ast.unparse(node.returns))
    return " ".join(parts)


class RedundantDocstring(Rule):
    id: str = "redundant-docstring"
    code: str = "SARJ050"
    description: str = (
        "Docstring only re-spells the signature — delete the whole docstring, "
        "or replace it with what the caller cannot read off the name."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, diags)
        return sorted(diags, key=lambda d: d.line)

    def _walk(
        self,
        node: ast.AST,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, class_name, path, diags)
                self._walk(child, class_name, path, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, diags)
            else:
                self._walk(child, class_name, path, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return
        if len(node.body) == 1:
            return  # the docstring IS the body; deleting it leaves a syntax error
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        if _numeric_content(node, docstring, class_name):
            return
        if not restates(docstring, signature_stems(node, class_name)):
            return
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
