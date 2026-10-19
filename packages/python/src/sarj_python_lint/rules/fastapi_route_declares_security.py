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
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._fastapi import FastapiIndex, Route


_MAX_ALIAS_DEPTH = 8
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _example(*, example_id: str, title: str, source: str, matches: bool, public: bool = False) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(ExampleFile.python("app/routes.py", source),),
        focus_path=PurePosixPath("app/routes.py"),
        expected_count=1 if matches else 0,
        public=public,
    )


@final
class FastapiRouteDeclaresSecurity(Rule):
    id = "fastapi-route-declares-security"
    code = "SARJ521"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Every FastAPI route declares at least one `Security()` dependency.",
        rationale=(
            "A route without an access dependency is reachable by anyone who can reach the service, and nothing in the "
            "diff shows that its author decided that. `fastapi.Security` behaves exactly like `Depends` unless OAuth "
            "scopes are passed, so wrapping the dependency that admits callers in `Security(...)` changes no runtime "
            "behavior or OpenAPI output while making the access decision explicit and checkable."
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
                "Dependencies added at mount time with `include_router(..., dependencies=...)` or "
                "`FastAPI(dependencies=...)` in another module, routes registered with `add_api_route`, websockets, "
                "and decorators that unpack `**kwargs` are not visible to a single-file analysis."
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
        index = context.fastapi
        findings: list[Diagnostic] = []
        for function in context.nodes(*_FUNCTIONS):
            for routes in _routes_without_security(index, context.parents, function):
                decorator = routes[0].decorator
                findings.append(
                    Diagnostic(
                        context.path,
                        decorator.lineno,
                        decorator.col_offset + 1,
                        self.code,
                        f"{_label(routes)} declares no `Security()` dependency; wrap the dependency that admits callers "
                        "in `Security(...)`, or declare the route public with an explicit `Security(...)` marker",
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _routes_without_security(
    index: FastapiIndex, parents: Mapping[ast.AST, ast.AST], function: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[list[Route]]:
    # One decorator can register several methods; it is judged once, as a group.
    by_decorator: dict[int, list[Route]] = {}
    for route in index.routes(function):
        if not route.has_unpack:
            by_decorator.setdefault(id(route.decorator), []).append(route)
    if not by_decorator:
        return []
    resolver = _SecurityResolver(index, parents, function)
    if resolver.parameters_declare_security(function):
        return []
    return [
        routes
        for routes in by_decorator.values()
        if not any(resolver.route_declares_security(route) for route in routes)
    ]


def _label(routes: Sequence[Route]) -> str:
    methods = "/".join(route.method.upper() for route in routes)
    path = routes[0].path
    return f"`{methods} {path}`" if path is not None else f"`{methods}` route"


class _SecurityResolver:
    def __init__(
        self,
        index: FastapiIndex,
        parents: Mapping[ast.AST, ast.AST],
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._index = index
        self._scopes = tuple(_enclosing_scopes(function, parents))

    def route_declares_security(self, route: Route) -> bool:
        return any(
            node is not None and self._declares(node, 0)
            for node in (route.keywords.get("dependencies"), route.inherited_dependencies)
        )

    def parameters_declare_security(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        arguments = function.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        defaults = [default for default in (*arguments.defaults, *arguments.kw_defaults) if default is not None]
        return any(self._annotation_declares(parameter.annotation) for parameter in parameters) or any(
            self._is_security(default) for default in defaults
        )

    def _annotation_declares(self, annotation: ast.expr | None) -> bool:
        if annotation is None:
            return False
        parts = self._index.annotated_parts(annotation)
        if parts is not None and any(self._is_security(item) for item in parts.metadata):
            return True
        return self._index.is_imported_security_alias(annotation)

    def _is_security(self, node: ast.expr) -> bool:
        marker = self._index.marker(node)
        return marker is not None and marker.name == "Security"

    def _declares(self, node: ast.expr, depth: int) -> bool:
        if depth > _MAX_ALIAS_DEPTH:
            return False
        match node:
            case ast.Call():
                return self._is_security(node)
            case ast.List(elts=items) | ast.Tuple(elts=items) | ast.Set(elts=items):
                return any(self._declares(item, depth + 1) for item in items)
            case ast.Starred(value=value):
                return self._declares(value, depth + 1)
            case ast.BinOp(op=ast.Add(), left=left, right=right):
                return self._declares(left, depth + 1) or self._declares(right, depth + 1)
            case ast.Name(id=name):
                values = self._bound_values(name)
                return bool(values) and all(self._declares(value, depth + 1) for value in values)
            case _:
                return False

    def _bound_values(self, name: str) -> tuple[ast.expr, ...]:
        for scope in self._scopes:
            if isinstance(scope, _FUNCTIONS) and name in _parameter_names(scope):
                return ()
            values = tuple(_assigned_values(scope, name))
            if values:
                return values
        return ()


def _enclosing_scopes(
    function: ast.FunctionDef | ast.AsyncFunctionDef, parents: Mapping[ast.AST, ast.AST]
) -> Iterator[ast.AST]:
    # A decorator runs in the scope that contains the decorated function. Class bodies are visible only
    # to code written directly in them, so outer class scopes are skipped.
    first = True
    current = parents.get(function)
    while current is not None:
        if isinstance(current, _SCOPES) and (first or not isinstance(current, ast.ClassDef)):
            yield current
            first = False
        current = parents.get(current)


def _parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    arguments = function.args
    names = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
    return frozenset(argument.arg for argument in names if argument is not None)


def _assigned_values(scope: ast.AST, name: str) -> Iterator[ast.expr]:
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, _NESTED_SCOPES):
            continue
        value = _assigned_value(node, name)
        if value is not None:
            yield value
        pending.extend(ast.iter_child_nodes(node))


def _assigned_value(node: ast.AST, name: str) -> ast.expr | None:
    match node:
        case ast.Assign(targets=targets, value=value) if any(_binds(target, name) for target in targets):
            return value
        case ast.AnnAssign(target=target, value=ast.expr() as value) if _binds(target, name):
            return value
        case _:
            return None


def _binds(target: ast.expr, name: str) -> bool:
    return isinstance(target, ast.Name) and target.id == name
