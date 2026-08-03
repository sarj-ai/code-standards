"""SARJ048 — Importing a private name — but only when the private name is OURS.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_first_party_private_import.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import (
    has_first_party_source,
    is_first_party_module,
    own_top_package,
    same_distribution,
)


if TYPE_CHECKING:
    from pathlib import Path


class NoFirstPartyPrivateImport(Rule):
    id: str = "no-first-party-private-import"
    code: str = "SARJ048"
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
            Diagnostic(path=path, line=hit.line, col=hit.col, code=self.code, message=_message(hit.module, hit.name))
            for hit in _private_imports(tree)
            if _is_ours(hit.module, path, own_top) and not _is_our_own_internals(hit, path)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


@dataclass(frozen=True, slots=True)
class _PrivateImport:
    """One private thing imported by one statement."""

    line: int
    col: int
    module: str
    name: str
    #: The private thing is a segment of the module path, not an imported name.
    is_segment: bool
    #: Every name this statement imports is public (vacuously true for `import x._y`).
    names_public: bool


def _is_our_own_internals(hit: _PrivateImport, path: Path) -> bool:
    """Return whether the private module is unavailable or belongs to the importer's distribution."""
    if not hit.is_segment:
        return False
    if not has_first_party_source(hit.module, path):
        return True
    return hit.names_public and same_distribution(hit.module, path)


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


def _private_imports(tree: ast.Module) -> list[_PrivateImport]:
    """Collect private symbols and submodule segments from absolute imports."""
    hits: list[_PrivateImport] = []
    for node in nodes(tree, ast.ImportFrom, ast.Import):
        if isinstance(node, ast.ImportFrom):
            hits.extend(_from_import_hits(node))
        else:
            hits.extend(_plain_import_hits(node))
    return hits


def _from_import_hits(node: ast.ImportFrom) -> list[_PrivateImport]:
    # `node.level` > 0 is a relative import: inside its own package by construction.
    if node.level or not node.module:
        return []
    private_segment = _private_segment(node.module)
    if private_segment is not None:
        return [
            _PrivateImport(
                line=node.lineno,
                col=node.col_offset + 1,
                module=node.module,
                name=private_segment,
                is_segment=True,
                names_public=not any(_is_private_name(alias.name) for alias in node.names),
            )
        ]
    return [
        _PrivateImport(
            line=alias.lineno,
            col=alias.col_offset + 1,
            module=node.module,
            name=name,
            is_segment=False,
            names_public=False,
        )
        for alias in node.names
        if _is_private_name(name := alias.name)
    ]


def _plain_import_hits(node: ast.Import) -> list[_PrivateImport]:
    hits: list[_PrivateImport] = []
    for alias in node.names:
        private_segment = _private_segment(alias.name)
        if private_segment is not None:
            hits.append(
                _PrivateImport(
                    line=alias.lineno,
                    col=alias.col_offset + 1,
                    module=alias.name,
                    name=private_segment,
                    is_segment=True,
                    names_public=True,
                )
            )
    return hits


def _private_segment(module: str) -> str | None:
    """Return the first private component BELOW the top level of a dotted module path."""
    return next((part for part in module.split(".")[1:] if _is_private_name(part)), None)


def _is_private_name(name: str) -> bool:
    # `__version__` / `__all__` are module metadata by convention, not internals.
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
