"""SARJ086 — An `Args:` block that only re-spells the parameter list.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_docstring_args_restate_signature.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    arg_entries,
    arg_section,
    decorator_markers,
    identifier_stems,
    restates,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class DocstringArgsRestateSignature(Rule):
    id: str = "docstring-args-restate-signature"
    code: str = "SARJ086"
    description: str = (
        "`Args:` block adds nothing the signature does not already say — delete the section and keep the summary."
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

    def _walk(self, node: ast.AST, class_name: str | None, path: Path, diags: list[Diagnostic]) -> None:
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
        if not docstring:
            return
        block = arg_section(docstring)
        if block is None or VALUE_MARKER_RE.search(block) or is_protected(block):
            return
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        entries = arg_entries(block)
        if not entries:
            return
        known = signature_stems(node, class_name)
        for name, annotation, description in entries:
            if not description:
                return  # a machine-emitted `name (type):` stub — see the module docstring
            if not restates(description, known | identifier_stems(name) | identifier_stems(annotation)):
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
