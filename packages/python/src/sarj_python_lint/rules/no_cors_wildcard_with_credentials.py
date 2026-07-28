"""SARJ028: detect Starlette/FastAPI CORS that echoes any Origin with credentials.

`CORSMiddleware(allow_credentials=True, allow_origins=[..., "*", ...])` tells the
browser to reflect the request's `Origin` back in
`Access-Control-Allow-Origin` AND to send `Access-Control-Allow-Credentials:
true`. Together these let *any* website read authenticated (cookie/session)
responses — a cross-origin credential-theft surface.

The rule fires on an `ast.Call` that has BOTH `allow_credentials=True`
(literal) AND an `allow_origins` value whose subtree contains a `"*"` string
literal anywhere — so it catches the bare `["*"]` form as well as the
`allowed if flag else ["*"]` conditional branch. The keyword pair is unique to
Starlette's CORSMiddleware, so matching the callee name is unnecessary (though it
would be a valid further tightening).

References:
- https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#credentialed_requests_and_wildcards

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


class NoCorsWildcardWithCredentials(Rule):
    """CORS that reflects any Origin while allowing credentials."""

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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
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
    """Report whether `node` is the literal `True` (not `1`, not a truthy expression).

    Returns:
        True only when `node` is the `True` constant.

    """
    return isinstance(node, ast.Constant) and node.value is True


def _contains_star_literal(node: ast.expr) -> bool:
    """Report whether a `"*"` string `Constant` appears anywhere in `node`'s subtree.

    Walking the whole subtree catches both `["*"]` and the `allowed if flag else
    ["*"]` conditional branch. A dynamic `allow_origins=some_var` has no `"*"`
    literal, so it does not fire.

    Returns:
        True when a `"*"` literal appears in the subtree.

    """
    return any(isinstance(child, ast.Constant) and child.value == "*" for child in ast.walk(node))
