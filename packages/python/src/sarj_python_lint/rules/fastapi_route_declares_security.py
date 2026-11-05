from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._fastapi_access import SecurityResolver
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._fastapi import Route
    from sarj_python_lint.rules._fastapi_access import FastapiAccessGraph


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _example(
    *, example_id: str, title: str, source: str, matches: bool, public: bool = False, scenario: str = "primary"
) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(ExampleFile.python("app/routes.py", source),),
        focus_path=PurePosixPath("app/routes.py"),
        expected_count=1 if matches else 0,
        public=public,
        scenario=scenario,
    )


@final
class FastapiRouteDeclaresSecurity(ProjectRule):
    id = "fastapi-route-declares-security"
    code = "SARJ563"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare each FastAPI route access decision, including inherited router dependencies.",
        rationale=(
            "A route without a visible access declaration makes reviewers infer its policy from unrelated code. "
            "A Security dependency records the decision at the route or an effective router ancestor. "
            "This contract does not establish the strength of the check or replace middleware review."
        ),
        remediation=(
            "Wrap the dependency that authenticates or authorizes callers in `Security(...)`, in the decorator's "
            "`dependencies=`, on the router, or as an `Annotated` parameter. For a route that is public on purpose, "
            "declare a no-op marker dependency such as `Security(public_route)`."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "The rule proves that an access decision is declared, not that it is sufficient: a `Security()` "
                "around a sign-in check satisfies it. Each service decides which dependency is strong enough."
            ),
            (
                "Follows statically resolved include_router edges and module-level imported routers in the prepared "
                "project. Factory-returned routers, middleware, add_api_route and websockets are not modeled. "
                "Router ancestry is bounded to eight hops and 4096 visited receivers per route. "
                "Route-copy timing and arbitrary runtime mutation are not modeled. "
                "Ambiguous unpacking and mount cycles abstain; this warning is an explicit declaration contract, "
                "not proof that a route is unauthenticated."
            ),
            "Tests and generated code are excluded.",
        ),
        examples=(
            _example(
                example_id="depends-only",
                title="A route whose only access dependency uses `Depends`",
                source=(
                    "from fastapi import APIRouter, Depends\n"
                    "router = APIRouter()\n"
                    "@router.get('/items', dependencies=[Depends(require_user)])\n"
                    "def items() -> Items: ...\n"
                ),
                matches=True,
                public=True,
            ),
            _example(
                example_id="no-dependencies",
                title="A route with no dependencies at all",
                source=(
                    "from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/items')\ndef create() -> Item: ...\n"
                ),
                matches=True,
            ),
            _example(
                example_id="decorator-security",
                title="The decorator declares a `Security` dependency",
                source=(
                    "from fastapi import APIRouter, Security\n"
                    "router = APIRouter()\n"
                    "@router.get('/items', dependencies=[Security(require_permission(Permission.ITEMS_READ))])\n"
                    "def items() -> Items: ...\n"
                ),
                matches=False,
                public=True,
            ),
            _example(
                example_id="parameter-security",
                title="An `Annotated` parameter declares a `Security` dependency",
                source=(
                    "from typing import Annotated\n"
                    "from fastapi import APIRouter, Security\n"
                    "router = APIRouter()\n"
                    "@router.get('/items')\n"
                    "def items(scope: Annotated[Scope, Security(require_permission(Permission.ITEMS_READ))]) -> Items: ...\n"
                ),
                matches=False,
            ),
            _example(
                example_id="router-security",
                title="The router declares a `Security` dependency for all of its routes",
                source=(
                    "from fastapi import APIRouter, Security\n"
                    "router = APIRouter(dependencies=[Security(require_admin)])\n"
                    "@router.delete('/items/{item_id}')\n"
                    "def delete(item_id: str) -> None: ...\n"
                ),
                matches=False,
            ),
            _example(
                example_id="inherited-application-security",
                title="An included router inherits the application's Security declaration",
                source=(
                    "from fastapi import APIRouter, FastAPI, Security\n"
                    "router = APIRouter()\n@router.get('/items')\ndef items(): ...\n"
                    "app = FastAPI(dependencies=[Security(require_user)])\napp.include_router(router)\n"
                ),
                matches=False,
                public=True,
                scenario="inherited-router-access",
            ),
            _example(
                example_id="unguarded-application-mount",
                title="An included router has no inherited Security declaration",
                source=(
                    "from fastapi import APIRouter, FastAPI\n"
                    "router = APIRouter()\n@router.get('/items')\ndef items(): ...\n"
                    "app = FastAPI()\napp.include_router(router)\n"
                ),
                matches=True,
                public=True,
                scenario="inherited-router-access",
            ),
            _example(
                example_id="explicit-public-route",
                title="A public route says so with an explicit marker",
                source=(
                    "from fastapi import APIRouter, Security\n"
                    "router = APIRouter()\n"
                    "@router.get('/health', dependencies=[Security(public_route)])\n"
                    "def health() -> Health: ...\n"
                ),
                matches=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated or context.tree is None:
            return []
        graph = context.session.fastapi_access.for_context(context)
        findings: list[Diagnostic] = []
        for function in context.nodes(*_FUNCTIONS):
            for routes in _routes_without_security(context, function, graph):
                decorator = routes[0].decorator
                findings.append(
                    Diagnostic(
                        context.path,
                        decorator.lineno,
                        decorator.col_offset + 1,
                        self.code,
                        f"{_label(routes)} declares no `Security()` dependency; wrap the dependency that admits callers "
                        "in `Security(...)`, or declare the route public with an explicit `Security(...)` marker",
                        severity=Severity.WARNING,
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _routes_without_security(
    context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef, graph: FastapiAccessGraph
) -> list[list[Route]]:
    index = context.fastapi
    # One decorator can register several methods; it is judged once, as a group.
    by_decorator: dict[int, list[Route]] = {}
    for route in index.routes(function):
        if not route.has_unpack and not route.inherited_has_unpack:
            by_decorator.setdefault(id(route.decorator), []).append(route)
    if not by_decorator:
        return []
    resolver = SecurityResolver(context, mutated=graph.mutations(context))
    if resolver.parameters_declare_security(function):
        return []
    return [
        routes
        for routes in by_decorator.values()
        if not any(resolver.route_declares_security(route) for route in routes)
        and graph.protected(context.path, routes[0].receiver) is False
    ]


def _label(routes: Sequence[Route]) -> str:
    methods = "/".join(route.method.upper() for route in routes)
    path = routes[0].path
    return f"`{methods} {path}`" if path is not None else f"`{methods}` route"
