"""SARJ088 — A test docstring that only re-spells the test's own name and body.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_restated_test_docstring.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import (
    VALUE_MARKER_RE,
    restates,
    sections,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# The vocabulary a test docstring spends on *being a test*.
_TEST_CEREMONY = (
    "assert",
    "asserted",
    "asserts",
    "behavior",
    "behaviour",
    "case",
    "cases",
    "check",
    "checked",
    "checking",
    "checks",
    "confirm",
    "confirmed",
    "confirms",
    "correctly",
    "coverage",
    "covered",
    "covers",
    "ensure",
    "ensured",
    "ensures",
    "ensuring",
    "exercise",
    "exercises",
    "expect",
    "expected",
    "expects",
    "happy",
    "integration",
    "path",
    "properly",
    "regression",
    "scenario",
    "scenarios",
    "successful",
    "successfully",
    "test",
    "tested",
    "testing",
    "tests",
    "unit",
    "validate",
    "validated",
    "validates",
    "verified",
    "verifies",
    "verify",
    "verifying",
)

_CEREMONY_STEMS = frozenset(stem(word) for word in _TEST_CEREMONY)

# Sections other than the summary are SARJ086/087's subject.
_SUMMARY_ONLY = frozenset({"summary"})


# The keyword singletons.
_SINGLETONS: dict[object, str] = {None: "none", True: "true", False: "false"}


def _body_stems(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect the stemmed word parts of every IDENTIFIER in the test body."""
    tokens: list[str] = []
    for child in ast.walk(node):
        match child:
            case ast.Name():
                tokens.extend(split_identifier(child.id))
            case ast.Attribute():
                tokens.extend(split_identifier(child.attr))
            case ast.keyword() if child.arg is not None:
                tokens.extend(split_identifier(child.arg))
            case ast.arg():
                tokens.extend(split_identifier(child.arg))
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                tokens.extend(split_identifier(child.name))
            case ast.Constant():
                word = next((w for key, w in _SINGLETONS.items() if child.value is key), None)
                if word is not None:
                    tokens.append(word)
            case _:
                continue
    return {stem(token) for token in tokens}


def _is_test(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> bool:
    if node.name.startswith("test_") or node.name == "test":
        return True
    return class_name is not None and class_name.startswith("Test") and node.name.startswith("test")


class RestatedTestDocstring(Rule):
    id: str = "restated-test-docstring"
    code: str = "SARJ088"
    description: str = (
        "Test docstring only re-spells the test's own name and body — delete it; "
        "rename the test if the name does not already say it."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, diags)
        return sorted(diags, key=lambda diag: diag.line)

    def _walk(self, node: ast.AST, class_name: str | None, path: Path, diags: list[Diagnostic]) -> None:
        for child in children(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._check_function(child, class_name, path, diags)
            elif isinstance(child, ast.ClassDef):
                self._check_class(child, path, diags)
                self._walk(child, child.name, path, diags)
            else:
                self._walk(child, class_name, path, diags)

    def _check_class(self, node: ast.ClassDef, path: Path, diags: list[Diagnostic]) -> None:
        """Flag a `Test*` class whose docstring only re-spells its name and method names."""
        if not node.name.startswith("Test") or node.bases or node.keywords:
            return
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or not self._is_plain_summary(docstring):
            return
        known = {stem(part) for part in split_identifier(node.name)} | _CEREMONY_STEMS
        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                known |= signature_stems(child, node.name)
        if not restates(docstring, known):
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

    @staticmethod
    def _is_plain_summary(docstring: str) -> bool:
        """Report whether the docstring is a bare summary with nothing protected in it."""
        if frozenset(sections(docstring)) != _SUMMARY_ONLY:
            return False
        return not is_protected(docstring) and not VALUE_MARKER_RE.search(docstring)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        if not _is_test(node, class_name):
            return
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or not self._is_plain_summary(docstring):
            return
        known = signature_stems(node, class_name) | _body_stems(node) | _CEREMONY_STEMS
        if not restates(docstring, known):
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
