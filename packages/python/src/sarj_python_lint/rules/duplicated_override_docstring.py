"""SARJ084 — An override whose docstring is a verbatim copy of the base's.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_duplicated_override_docstring.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ084.md
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


type _Func = ast.FunctionDef | ast.AsyncFunctionDef

_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _methods(node: ast.ClassDef) -> dict[str, _Func]:
    """Index a class body's directly-defined methods by name."""
    return {child.name: child for child in node.body if isinstance(child, _FUNC_TYPES)}


def _is_overload(node: _Func) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "overload":
            return True
    return False


class DuplicatedOverrideDocstring(Rule):
    id: str = "duplicated-override-docstring"
    code: str = "SARJ084"
    has_evidence: bool = True
    description: str = (
        "Docstring is a verbatim copy of the base class's — delete it; "
        "`help()`, `inspect.getdoc` and every editor already read the base's."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        classes = nodes(tree, ast.ClassDef)
        # A name defined twice in one module is ambiguous, and the second
        # definition is what a subclass below it would actually inherit from.
        by_name = {node.name: node for node in classes}
        diags: list[Diagnostic] = []
        for node in classes:
            for base in self._resolvable_bases(node, by_name):
                self._compare(node, base, path, diags)
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _resolvable_bases(node: ast.ClassDef, by_name: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
        """Bases of `node` that this module defines under an undotted name."""
        found: list[ast.ClassDef] = []
        for base in node.bases:
            if not isinstance(base, ast.Name):
                continue
            parent = by_name.get(base.id)
            if parent is not None and parent is not node:
                found.append(parent)
        return found

    def _compare(
        self,
        node: ast.ClassDef,
        parent: ast.ClassDef,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        inherited = _methods(parent)
        for name, child in _methods(node).items():
            base_method = inherited.get(name)
            if base_method is None or _is_overload(child) or _is_overload(base_method):
                continue
            if len(child.body) == 1:
                continue  # the docstring IS the body; deleting it leaves a syntax error
            docstring = ast.get_docstring(child, clean=True)
            if not docstring or docstring != ast.get_docstring(base_method, clean=True):
                continue
            expr = child.body[0]
            diags.append(
                Diagnostic(
                    path=path,
                    line=expr.lineno,
                    col=expr.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Docstring is a verbatim copy of {parent.name}.{name}'s — delete it; "
                        "`help()`, `inspect.getdoc` and every editor already read the base's."
                    ),
                )
            )
