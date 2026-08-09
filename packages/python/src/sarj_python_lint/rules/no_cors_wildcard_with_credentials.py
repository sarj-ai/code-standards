"""SARJ028 — Starlette/FastAPI CORS that echoes any Origin with credentials.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_cors_wildcard_with_credentials.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoCorsWildcardWithCredentials(Rule):
    id: str = "no-cors-wildcard-with-credentials"
    code: str = "SARJ028"
    documentation = RuleDocumentation(
        summary="Credentialed CORS must not allow a wildcard origin.",
        rationale="Reflecting any origin while allowing credentials lets an untrusted site read authenticated responses.",
        remediation="Replace the wildcard with an explicit list of trusted origins.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            'The rule requires literal `True` for `allow_credentials` and a literal `"*"` below `allow_origins`.',
            "Dynamically computed credential flags and origin collections are not resolved.",
        ),
        examples=(
            RuleExample(
                example_id="credentialed-wildcard-origin",
                title="Credentials allowed for every origin",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/main.py",
                        'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/main.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="credentialed-trusted-origin",
                title="Credentials restricted to a trusted origin",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/main.py",
                        'app.add_middleware(\n    CORSMiddleware,\n    allow_origins=["https://app.example.com"],\n    allow_credentials=True,\n)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/main.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

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
