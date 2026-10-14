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
    Severity,
)
from sarj_python_lint.rules._route_shapes import route_decorators


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MESSAGE = (
    'Collection root "/" under a router prefix answers the slashless URL with a 307 redirect that some clients do '
    'not follow or replay without the body or headers; use "" instead.'
)


@final
class NoSlashCollectionRootUnderPrefix(Rule):
    id = "no-slash-collection-root-under-prefix"
    code = "SARJ503"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A collection-root route under a literal router prefix uses an empty path instead of a slash.",
        rationale=(
            'With `APIRouter(prefix="/items")`, a "/" route serves `/items/`, so a caller of `/items` gets a 307 '
            "redirect. Some API clients do not follow it, or replay it without the body or authorization header."
        ),
        remediation='Register the collection root with path "" so `/items` is served directly.',
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only routers created in the same file with a non-empty literal string `prefix=` are checked.",
            (
                'A prefix supplied later through `include_router(..., prefix=...)` is not visible, so "/" stays '
                "accepted there. Tests and generated files are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="slash-root",
                title="The collection root is registered as a slash",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/tasks')\n\n"
                        "@router.get('/')\nasync def list_tasks() -> list[str]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="empty-root",
                title="The collection root is registered as an empty path",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/tasks')\n\n"
                        "@router.get('')\nasync def list_tasks() -> list[str]:\n    return []\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return [
            Diagnostic(
                context.path,
                route.decorator.lineno,
                route.decorator.col_offset + 1,
                self.code,
                _MESSAGE,
                severity=Severity.WARNING,
            )
            for route in route_decorators(context)
            if route.path == "/" and _is_literal_prefix(route.prefix)
        ]


def _is_literal_prefix(prefix: ast.expr | None) -> bool:
    return isinstance(prefix, ast.Constant) and isinstance(prefix.value, str) and bool(prefix.value.strip("/"))
