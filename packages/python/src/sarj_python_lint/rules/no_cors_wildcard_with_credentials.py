"""SARJ028 — Starlette/FastAPI CORS that echoes any Origin with credentials.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_cors_wildcard_with_credentials.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


class NoCorsWildcardWithCredentials(Rule):
    id: str = "no-cors-wildcard-with-credentials"
    code: str = "SARJ028"
    description: str = (
        'CORS `allow_credentials=True` with `"*"` in `allow_origins` lets any site read authenticated responses.'
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            keywords = {arg: kw.value for kw in node.keywords if (arg := kw.arg) is not None}
            credentials = keywords.get("allow_credentials")
            origins = keywords.get("allow_origins")
            if credentials is None or origins is None:
                continue
            if not _is_true_literal(credentials):
                continue
            if not _contains_star_literal(origins):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        'CORS reflects any Origin (`"*"` in `allow_origins`) while '
                        "`allow_credentials=True` — any site can read authenticated "
                        "responses. Enumerate explicit trusted origins instead."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_true_literal(node: ast.expr) -> bool:
    """Report whether `node` is the literal `True` (not `1`, not a truthy expression)."""
    return isinstance(node, ast.Constant) and node.value is True


def _contains_star_literal(node: ast.expr) -> bool:
    """Report whether a `"*"` string `Constant` appears anywhere in `node`'s subtree."""
    return any(isinstance(child, ast.Constant) and child.value == "*" for child in walk(node))
