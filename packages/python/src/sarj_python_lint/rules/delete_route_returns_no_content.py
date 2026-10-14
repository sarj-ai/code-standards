from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

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
from sarj_python_lint.rules._route_shapes import RouteDecorator, http_status, route_decorators


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_NO_CONTENT: Final = 204
_MESSAGE = "DELETE route does not declare status_code=204; return no body and declare the 204 No Content status."


@final
class DeleteRouteReturnsNoContent(Rule):
    id = "delete-route-returns-no-content"
    code = "SARJ506"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="FastAPI DELETE routes declare status code 204 No Content.",
        rationale=(
            "Without an explicit 204, FastAPI answers a DELETE with 200 and a JSON null body. Generated clients then "
            "type the result as nullable data, and API routes disagree on what a successful removal returns."
        ),
        remediation="Declare `status_code=204` (or `status.HTTP_204_NO_CONTENT`) on the DELETE route and return None.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only DELETE-only decorators on a FastAPI or APIRouter receiver created in the same file are checked.",
            (
                "A status written as an integer, a Starlette `status.HTTP_*` name or an `HTTPStatus` member is resolved; "
                "any other status expression and decorators with `**` keyword unpacking are accepted."
            ),
            "Tests and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="implicit-200",
                title="A DELETE route answers 200 with a null body",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
                        "@router.delete('/keys/{key_id}')\nasync def revoke(key_id: str) -> None:\n    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="no-content",
                title="A DELETE route declares 204",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from fastapi import APIRouter, status\n\nrouter = APIRouter()\n\n"
                        "@router.delete('/keys/{key_id}', status_code=status.HTTP_204_NO_CONTENT)\n"
                        "async def revoke(key_id: str) -> None:\n    return None\n",
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
            if route.methods == {"delete"} and _lacks_no_content(route)
        ]


def _lacks_no_content(route: RouteDecorator) -> bool:
    status = next((keyword.value for keyword in route.decorator.keywords if keyword.arg == "status_code"), None)
    if status is None:
        return True
    resolved = http_status(status)
    return resolved is not None and resolved != _NO_CONTENT
