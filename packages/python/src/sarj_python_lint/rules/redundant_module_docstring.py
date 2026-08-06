"""SARJ099 — A module docstring that only re-spells its file path.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_redundant_module_docstring.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import VALUE_MARKER_RE, restates, sections
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SPECIAL_MODULES = frozenset({"__init__.py", "__main__.py"})
_SUMMARY_ONLY = frozenset({"summary"})
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")

# These words describe existence rather than purpose; unknown words are evidence
# that the docstring may say something the path cannot.
_MODULE_FILLER_STEMS = frozenset(
    stem(word)
    for word in (
        "implementation",
        "module",
        "operation",
    )
)


@final
class RedundantModuleDocstring(Rule):
    id: str = "redundant-module-docstring"
    code: str = "SARJ099"
    description: str = (
        "Module docstring only re-spells the file path — delete it, or say what "
        "the path cannot: the invariant, boundary, consumer, or compatibility constraint."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if self._excluded_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None or len(tree.body) <= 1:
            return []
        expression = tree.body[0]
        if (
            not isinstance(expression, ast.Expr)
            or not isinstance(expression.value, ast.Constant)
            or not isinstance(expression.value.value, str)
        ):
            return []
        docstring = ast.get_docstring(tree, clean=True)
        if not docstring or not self._is_plain_summary(expression, docstring):
            return []
        known = _path_stems(path) | _MODULE_FILLER_STEMS
        if not restates(docstring, known):
            return []
        return [
            Diagnostic(
                path=path,
                line=expression.lineno,
                col=expression.col_offset + 1,
                code=self.code,
                message=self.description,
                severity=Severity.WARNING,
            )
        ]

    @staticmethod
    def _excluded_path(path: Path) -> bool:
        return path.name in _SPECIAL_MODULES or path.suffix == ".pyi" or is_test_path(path)

    @staticmethod
    def _is_plain_summary(expression: ast.Expr, docstring: str) -> bool:
        if expression.end_lineno != expression.lineno or "\n" in docstring:
            return False
        if frozenset(sections(docstring)) != _SUMMARY_ONLY:
            return False
        if len(_SENTENCE_END_RE.findall(docstring)) > 1:
            return False
        return not VALUE_MARKER_RE.search(docstring) and not is_protected(docstring)


def _path_stems(path: Path) -> set[str]:
    tokens = [*split_identifier(path.stem), *split_identifier(path.parent.name)]
    return {stem(token) for token in tokens}
