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
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._fastapi import FastapiIndex, Route, flat_name
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_NON_JSON_RESPONSES = frozenset(
    {"FileResponse", "HTMLResponse", "PlainTextResponse", "RedirectResponse", "StreamingResponse"}
)
_TOP_LEVEL_COLLECTIONS = frozenset(
    {"dict", "Dict", "list", "List", "Mapping", "MutableMapping", "set", "Set", "tuple", "Tuple", "Sequence"}
)
_SCALARS = frozenset({"bool", "bytes", "float", "int", "str"})


@final
class FastapiClassRouterContract(Rule):
    id = "fastapi-class-router-contract"
    code = "SARJ451"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="FastAPI HTTP routes use injected `*Router.build()` owners and explicit named object response models.",
        rationale=(
            "Class-owned construction gives dependencies one reviewable composition boundary, while explicit object models "
            "keep success envelopes stable and generated clients precise."
        ),
        remediation=(
            "Inject dependencies through `*Router.__init__`, create and return a local `APIRouter` from `build()`, and declare "
            "`response_model=NamedResponse` with a matching named return annotation. Compose the application with "
            "`FastAPI.include_router(...)` instead of declaring HTTP handlers directly on it."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Tests, generated code, and hidden routes are excluded. FastAPI application construction and include_router composition are allowed.",
            "Response-model checks exclude literal or import-proven 204/205/304 statuses and proven non-JSON response classes, including raw Response.",
            "Unpacked metadata or an explicit unresolved status cannot prove a JSON response; receiver ownership remains checked while response-model inference abstains.",
            "Response classes require unshadowed native import provenance; direct provider writes/escapes, custom classes, and unresolved defaults disable JSON-model inference.",
        ),
        examples=(
            RuleExample(
                example_id="module-router",
                title="A module owns an unscoped router",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/routes.py", "from fastapi import APIRouter\nrouter = APIRouter()\n"),),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-app-route",
                title="An application declares an HTTP handler directly",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import FastAPI\napp = FastAPI()\n"
                        "@app.get('/items', response_model=ItemsResponse)\n"
                        "def items() -> ItemsResponse:\n    return ItemsResponse(items=[])\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=1,
                public=True,
                scenario="application-composition",
            ),
            RuleExample(
                example_id="app-router-composition",
                title="An application includes a class-owned router",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(ItemRouter(service).build())\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=0,
                public=True,
                scenario="application-composition",
            ),
            RuleExample(
                example_id="class-router",
                title="A class builds and returns its router",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import APIRouter\nclass ItemRouter:\n    def __init__(self, service: Service) -> None:\n        self._service = service\n    def build(self) -> APIRouter:\n        router = APIRouter()\n        return router\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        index = context.fastapi
        parents = context.parents
        findings = _router_construction_findings(path, tree, index, parents, node_index=context.node_index)
        for function in (
            node for node in context.nodes(ast.AST) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            routes = tuple(route for route in index.routes(function) if not route.is_hidden)
            findings.extend(_direct_app_route_findings(path, routes))
            for route in routes:
                problem = _response_problem(function, route, index)
                if problem is not None:
                    findings.append(Diagnostic(path, function.lineno, function.col_offset + 1, self.code, problem))
        return sorted(findings, key=lambda finding: (finding.line, finding.col, finding.message))


def _direct_app_route_findings(path: Path, routes: tuple[Route, ...]) -> list[Diagnostic]:
    decorators = {route.decorator for route in routes if route.receiver_kind == "FastAPI"}
    return [
        Diagnostic(
            path,
            decorator.lineno,
            decorator.col_offset + 1,
            FastapiClassRouterContract.code,
            "declare HTTP routes on a local APIRouter returned by `*Router.build()`, then compose with include_router",
        )
        for decorator in decorators
    ]


def _router_construction_findings(
    path: Path,
    tree: ast.Module,
    index: FastapiIndex,
    parents: Mapping[ast.AST, ast.AST],
    *,
    node_index: NodeIndex | None = None,
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for call in (node for node in walk_ast(tree, index=node_index) if isinstance(node, ast.Call)):
        if index.constructor_kind(call) != "APIRouter":
            continue
        function = _ancestor(call, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
        cls = _ancestor(call, parents, ast.ClassDef)
        if (
            isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and isinstance(cls, ast.ClassDef)
            and function.name == "build"
            and cls.name.endswith("Router")
            and _returns_local_router(function, call)
        ):
            continue
        findings.append(
            Diagnostic(
                path,
                call.lineno,
                call.col_offset + 1,
                FastapiClassRouterContract.code,
                "construct APIRouter only inside `*Router.build()` and return that local router",
            )
        )
    return findings


def _returns_local_router(function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call) -> bool:
    names = {
        target.id
        for node in function.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in _assignment_targets(node)
        if isinstance(target, ast.Name) and getattr(node, "value", None) is call
    }
    return bool(names) and any(
        isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id in names
        for node in function.body
    )


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return list(node.targets) if isinstance(node, ast.Assign) else [node.target]


def _response_problem(
    function: ast.FunctionDef | ast.AsyncFunctionDef, route: Route, index: FastapiIndex
) -> str | None:
    keywords = route.keywords
    response_class = keywords.get("response_class") or route.inherited_response_class
    if response_class is not None and flat_name(response_class) in _NON_JSON_RESPONSES:
        return None
    if not index.can_infer_json_response(route):
        return None
    response_model = keywords.get("response_model")
    if response_model is None or (isinstance(response_model, ast.Constant) and response_model.value is None):
        return "JSON operation requires explicit `response_model=NamedResponse`"
    annotation = index.resolve_annotation(function.returns)
    if annotation is None:
        return "JSON operation requires a named response return annotation matching response_model"
    if _is_collection_or_scalar(annotation):
        return (
            "successful JSON responses must use a named object envelope, not a top-level collection, mapping, or scalar"
        )
    if flat_name(annotation) != flat_name(response_model):
        return "response_model must match the named response return annotation"
    return None


def _is_collection_or_scalar(annotation: ast.expr) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return flat_name(target) in _TOP_LEVEL_COLLECTIONS | _SCALARS


def _ancestor(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST], kind: type[ast.AST] | tuple[type[ast.AST], ...]
) -> ast.AST | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, kind):
            return current
        current = parents.get(current)
    return None
