"""Deterministic FastAPI syntax resolution shared by route-aware rules."""

from __future__ import annotations

import ast
from dataclasses import dataclass


HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "trace", "api_route"})
PARAM_MARKERS = frozenset({"Path", "Query", "Header", "Cookie", "Body", "Form", "File", "Depends", "Security"})
SCHEMA_MARKERS = PARAM_MARKERS - {"Depends", "Security"}
INJECTION_TYPES = frozenset({"Request", "Response", "WebSocket", "HTTPConnection", "BackgroundTasks", "SecurityScopes"})
RESPONSE_TYPES = frozenset(
    {
        "Response",
        "JSONResponse",
        "HTMLResponse",
        "PlainTextResponse",
        "RedirectResponse",
        "StreamingResponse",
        "FileResponse",
    }
)


@dataclass(frozen=True, slots=True)
class Route:
    decorator: ast.Call
    receiver: str
    method: str
    path: str | None

    @property
    def keywords(self) -> dict[str, ast.expr]:
        return {keyword.arg: keyword.value for keyword in self.decorator.keywords if keyword.arg is not None}

    @property
    def has_unpack(self) -> bool:
        return any(keyword.arg is None for keyword in self.decorator.keywords)


def flat_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


class FastapiIndex:
    """Resolve only FastAPI bindings whose provenance is visible in one module."""

    def __init__(self, tree: ast.Module) -> None:
        self.modules: set[str] = set()
        self.constructors: set[str] = set()
        self.annotated: set[str] = {"Annotated"}
        self.symbols: dict[str, str] = {}
        self.type_aliases: dict[str, ast.expr] = {}
        self.receivers: set[str] = set()
        self.decorators: dict[str, tuple[str, str]] = {}
        self._read_imports(tree)
        self._read_aliases(tree)

    def _read_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fastapi":
                        self.modules.add(alias.asname or "fastapi")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in {"typing", "typing_extensions"}:
                    for alias in node.names:
                        if alias.name == "Annotated":
                            self.annotated.add(alias.asname or alias.name)
                    continue
                if module != "fastapi" and not module.startswith(("fastapi.", "starlette.")):
                    continue
                for alias in node.names:
                    local = alias.asname or alias.name
                    self.symbols[local] = alias.name
                    if alias.name in {"FastAPI", "APIRouter"}:
                        self.constructors.add(local)

    def _read_aliases(self, tree: ast.Module) -> None:
        assignments: list[tuple[str, ast.expr]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                assignments.append((node.targets[0].id, node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                assignments.append((node.target.id, node.value))
            elif isinstance(node, ast.TypeAlias):
                self.type_aliases[node.name.id] = node.value

        changed = True
        while changed:
            changed = False
            for name, value in assignments:
                if name in self.receivers or name in self.decorators:
                    continue
                if self._is_constructor_call(value) or (isinstance(value, ast.Name) and value.id in self.receivers):
                    self.receivers.add(name)
                    changed = True
                    continue
                if (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id in self.receivers
                    and value.attr in HTTP_METHODS
                ):
                    self.decorators[name] = (value.value.id, value.attr)
                    changed = True
                    continue
                if self._is_annotated(value):
                    self.type_aliases[name] = value

    def _is_constructor_call(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return node.func.id in self.constructors
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.modules
            and node.func.attr in {"FastAPI", "APIRouter"}
        )

    def routes(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[Route, ...]:
        routes: list[Route] = []
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            method = ""
            receiver = ""
            if (
                isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id in self.receivers
            ):
                receiver = decorator.func.value.id
                method = decorator.func.attr
            elif isinstance(decorator.func, ast.Name) and decorator.func.id in self.decorators:
                receiver = self.decorators[decorator.func.id][0]
                method = self.decorators[decorator.func.id][1]
            if method not in HTTP_METHODS:
                continue
            path = None
            if (
                decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                path = decorator.args[0].value
            routes.append(Route(decorator=decorator, receiver=receiver, method=method, path=path))
        return tuple(routes)

    def canonical(self, node: ast.expr) -> str:
        name = flat_name(node)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in self.modules:
            return name
        return self.symbols.get(name, name)

    def resolve_annotation(self, node: ast.expr | None) -> ast.expr | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value.strip(), mode="eval").body
            except SyntaxError:
                return None
        seen: set[str] = set()
        while isinstance(node, ast.Name) and node.id in self.type_aliases and node.id not in seen:
            seen.add(node.id)
            node = self.type_aliases[node.id]
        return node

    def annotated_parts(self, node: ast.expr | None) -> tuple[ast.expr, tuple[ast.expr, ...]] | None:
        resolved = self.resolve_annotation(node)
        if not self._is_annotated(resolved) or not isinstance(resolved, ast.Subscript):
            return None
        elements = resolved.slice.elts if isinstance(resolved.slice, ast.Tuple) else [resolved.slice]
        if not elements:
            return None
        return elements[0], tuple(elements[1:])

    def _is_annotated(self, node: ast.expr | None) -> bool:
        return isinstance(node, ast.Subscript) and flat_name(node.value) in self.annotated

    def marker(self, node: ast.expr) -> tuple[str, ast.Call] | None:
        if not isinstance(node, ast.Call):
            return None
        canonical = self.canonical(node.func)
        if canonical not in PARAM_MARKERS:
            return None
        return canonical, node

    def is_injection(self, node: ast.expr | None) -> bool:
        resolved = self.resolve_annotation(node)
        return isinstance(resolved, (ast.Name, ast.Attribute)) and self.canonical(resolved) in INJECTION_TYPES

    def is_response(self, node: ast.expr | None) -> bool:
        resolved = self.resolve_annotation(node)
        return isinstance(resolved, (ast.Name, ast.Attribute)) and self.canonical(resolved) in RESPONSE_TYPES

    def is_http_exception(self, node: ast.expr) -> bool:
        return self.canonical(node) == "HTTPException"
