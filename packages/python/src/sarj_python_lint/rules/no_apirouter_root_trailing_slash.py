"""SARJ405 — APIRouter collection roots use an empty path, not ``/``.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_apirouter_root_trailing_slash.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._fastapi import FastapiIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_DOCUMENTATION_EXAMPLE_DIR_NAMES = frozenset({"docs_src"})


@final
class NoApirouterRootTrailingSlash(Rule):
    id: str = "no-apirouter-root-trailing-slash"
    code: str = "SARJ405"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="APIRouter collection-root operations should use an empty path instead of `/`.",
        rationale=(
            "A `/` path beneath an APIRouter prefix makes the prefix without its trailing slash redirect, "
            "rather than serving the canonical collection URL directly."
        ),
        remediation="Declare the APIRouter operation path as an empty string so the prefix itself is canonical.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only FastAPI and APIRouter bindings whose constructor provenance is visible in one module are resolved.",
            "Dynamic route paths are ignored because their runtime value cannot be proven.",
            "Tests, generated sources, and FastAPI documentation-source examples are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="router-root-trailing-slash",
                title="APIRouter root operation adds a trailing slash",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/items')\n\n"
                        "@router.get('/')\nasync def list_items() -> list[str]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="canonical-router-root",
                title="APIRouter root operation uses its prefix directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/items')\n\n"
                        "@router.get('')\nasync def list_items() -> list[str]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_generated(path, source)
            or any(part.lower() in _DOCUMENTATION_EXAMPLE_DIR_NAMES for part in path.parts)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        index = FastapiIndex(tree, path=path)
        decorators: dict[int, ast.Call] = {}
        for function in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef):
            for route in index.routes(function):
                if route.receiver_kind == "APIRouter" and route.path == "/":
                    decorators[id(route.decorator)] = route.decorator

        return [
            Diagnostic(
                path=path,
                line=decorator.lineno,
                col=decorator.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    "APIRouter collection-root path is `/`, so the prefix without a slash redirects — "
                    "declare the path as an empty string. Suppress with `# sarj-noqa: SARJ405`."
                ),
            )
            for decorator in sorted(decorators.values(), key=lambda node: (node.lineno, node.col_offset))
        ]
