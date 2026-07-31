"""SARJ048 — Importing a private name — but only when the private name is OURS.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_first_party_private_import.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ048.md
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import is_first_party_module, own_top_package


if TYPE_CHECKING:
    from pathlib import Path


class NoFirstPartyPrivateImport(Rule):
    id: str = "no-first-party-private-import"
    code: str = "SARJ048"
    has_evidence: bool = True
    description: str = (
        "Importing a private (`_`-prefixed) name or module from a FIRST-PARTY module reaches past a "
        "surface we control and can widen. Third-party privates are never flagged — that API is not ours to change."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag every private import whose defining module is first-party."""
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        own_top = own_top_package(path)
        diags = [
            Diagnostic(path=path, line=line, col=col, code=self.code, message=_message(module, name))
            for line, col, module, name in _private_imports(tree)
            if _is_ours(module, path, own_top)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _message(module: str, name: str) -> str:
    return (
        f"`{name}` is private to `{module}`, which is first-party — importing it reaches past a public "
        f"surface we own and can widen. Export it under a public name, or move the caller behind a "
        f"function `{module}` already exports. (Private imports from third-party packages are never flagged.)"
    )


def _is_ours(module: str, path: Path, own_top: str | None) -> bool:
    """Report whether `module` is a first-party module OUTSIDE the file's own package."""
    top = module.partition(".")[0]
    if own_top is not None and top == own_top:
        return False
    return is_first_party_module(module, path)


def _private_imports(tree: ast.Module) -> list[tuple[int, int, str, str]]:
    """Collect `(line, col, defining module, private name)` for every private import."""
    hits: list[tuple[int, int, str, str]] = []
    for node in nodes(tree, ast.ImportFrom, ast.Import):
        if isinstance(node, ast.ImportFrom):
            hits.extend(_from_import_hits(node))
        else:
            hits.extend(_plain_import_hits(node))
    return hits


def _from_import_hits(node: ast.ImportFrom) -> list[tuple[int, int, str, str]]:
    # `node.level` > 0 is a relative import: inside its own package by construction.
    if node.level or not node.module:
        return []
    private_segment = _private_segment(node.module)
    if private_segment is not None:
        return [(node.lineno, node.col_offset + 1, node.module, private_segment)]
    return [
        (alias.lineno, alias.col_offset + 1, node.module, name)
        for alias in node.names
        if _is_private_name(name := alias.name)
    ]


def _plain_import_hits(node: ast.Import) -> list[tuple[int, int, str, str]]:
    hits: list[tuple[int, int, str, str]] = []
    for alias in node.names:
        private_segment = _private_segment(alias.name)
        if private_segment is not None:
            hits.append((alias.lineno, alias.col_offset + 1, alias.name, private_segment))
    return hits


def _private_segment(module: str) -> str | None:
    """Return the first private component BELOW the top level of a dotted module path."""
    return next((part for part in module.split(".")[1:] if _is_private_name(part)), None)


def _is_private_name(name: str) -> bool:
    # `__version__` / `__all__` are module metadata by convention, not internals.
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
