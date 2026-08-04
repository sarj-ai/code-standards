"""Deterministic FastAPI syntax resolution shared by route-aware rules."""

from __future__ import annotations

import ast
from collections import Counter
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
        "ORJSONResponse",
        "UJSONResponse",
    }
)


@dataclass(frozen=True, slots=True)
class Route:
    decorator: ast.Call
    receiver: str
    method: str
    path: str | None
    inherited_hidden: bool = False

    @property
    def keywords(self) -> dict[str, ast.expr]:
        return {keyword.arg: keyword.value for keyword in self.decorator.keywords if keyword.arg is not None}

    @property
    def has_unpack(self) -> bool:
        return any(keyword.arg is None for keyword in self.decorator.keywords)

    @property
    def is_hidden(self) -> bool:
        if self.inherited_hidden:
            return True
        value = self.keywords.get("include_in_schema")
        return isinstance(value, ast.Constant) and value.value is False


def flat_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _binding_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return f"self.{node.attr}"
    return ""


class FastapiIndex:
    """Resolve only FastAPI bindings whose provenance is visible in one module."""

    def __init__(self, tree: ast.Module) -> None:
        self.modules: set[str] = set()
        self.module_symbols: dict[str, str] = {}
        self.http_modules: set[str] = set()
        self.annotation_modules: set[str] = set()
        self.constructors: set[str] = set()
        self.annotated: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.type_aliases: dict[str, ast.expr] = {}
        self.receivers: set[tuple[int, str]] = set()
        self.receiver_origins: dict[tuple[int, str], tuple[int, str]] = {}
        self.hidden_receivers: set[tuple[int, str]] = set()
        self.decorators: dict[tuple[int, str], tuple[str, str]] = {}
        self.bound_names: set[tuple[int, str]] = set()
        self._node_scopes: dict[int, int] = {}
        self._node_classes: dict[int, int | None] = {}
        self._route_scopes: dict[int, int] = {}
        self._scope_parents: dict[int, int | None] = {0: None}
        self._index_scopes(tree)
        self._read_imports(tree)
        self._read_aliases(tree)

    def _index_scopes(self, tree: ast.Module) -> None:
        def visit(node: ast.AST, scope: int, class_owner: int | None) -> None:
            self._node_scopes[id(node)] = scope
            if isinstance(node, ast.ClassDef):
                class_owner = node.lineno
                self._scope_parents[node.lineno] = scope
                scope = node.lineno
            self._node_classes[id(node)] = class_owner
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._route_scopes[id(node)] = scope
                self._scope_parents[node.lineno] = scope
                scope = node.lineno
            for child in ast.iter_child_nodes(node):
                visit(child, scope, class_owner)

        visit(tree, 0, None)

    def _read_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if self._node_scopes[id(node)] != 0:
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if alias.name == "fastapi" or alias.name.startswith(("fastapi.", "starlette.")):
                        self.modules.add(local)
                        self.module_symbols[local] = alias.name.rsplit(".", 1)[-1]
                    if alias.name in {"typing", "typing_extensions"}:
                        self.annotation_modules.add(local)
                    if alias.name == "http":
                        self.http_modules.add(local)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in {"typing", "typing_extensions"}:
                    for alias in node.names:
                        if alias.name == "Annotated":
                            self.annotated.add(alias.asname or alias.name)
                    continue
                if module == "http":
                    for alias in node.names:
                        if alias.name == "HTTPStatus":
                            self.symbols[alias.asname or alias.name] = "HTTPStatus"
                    continue
                if module != "fastapi" and not module.startswith(("fastapi.", "starlette.")):
                    continue
                for alias in node.names:
                    local = alias.asname or alias.name
                    self.symbols[local] = alias.name
                    if alias.name in {"FastAPI", "APIRouter"}:
                        self.constructors.add(local)

    def _read_aliases(self, tree: ast.Module) -> None:
        assignments: list[tuple[int, str, ast.expr]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.bound_names.add((self._node_scopes[id(node)], node.name))
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if node.args.vararg is not None:
                    arguments.append(node.args.vararg)
                if node.args.kwarg is not None:
                    arguments.append(node.args.kwarg)
                self.bound_names.update((node.lineno, argument.arg) for argument in arguments)
            elif isinstance(node, ast.ClassDef):
                self.bound_names.add((self._node_scopes[id(node)], node.name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.bound_names.update(
                    (self._node_scopes[id(node)], alias.asname or alias.name.split(".")[0]) for alias in node.names
                )
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self.bound_names.update((self._node_scopes[id(node)], name) for name in self._target_names(node.target))
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars is not None:
                        self.bound_names.update(
                            (self._node_scopes[id(node)], name) for name in self._target_names(item.optional_vars)
                        )
            elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                self.bound_names.add((self._node_scopes[id(node)], node.name))
            elif isinstance(node, ast.NamedExpr):
                self.bound_names.update((self._node_scopes[id(node)], name) for name in self._target_names(node.target))
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = _binding_name(node.targets[0])
                if name:
                    assignments.append((self._assignment_scope(node, name), name, node.value))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                name = _binding_name(node.target)
                if name:
                    assignments.append((self._assignment_scope(node, name), name, node.value))
            elif isinstance(node, ast.TypeAlias):
                self.type_aliases[node.name.id] = node.value

        changed = True
        counts = Counter((scope, name) for scope, name, _value in assignments)
        self.bound_names.update(counts)
        while changed:
            changed = False
            for scope, name, value in assignments:
                key = (scope, name)
                if counts[key] != 1:
                    continue
                if key in self.receivers or key in self.decorators:
                    continue
                source = self._receiver_key(scope, _binding_name(value))
                if self._is_constructor_call(value) or source is not None:
                    self.receivers.add(key)
                    self.receiver_origins[key] = key if source is None else self.receiver_origins[source]
                    if self._constructor_is_hidden(value) or (source is not None and source in self.hidden_receivers):
                        self.hidden_receivers.add(key)
                    changed = True
                    continue
                if isinstance(value, ast.Attribute) and value.attr in HTTP_METHODS:
                    receiver = _binding_name(value.value)
                    if self._receiver_key(scope, receiver) is not None:
                        self.decorators[key] = (receiver, value.attr)
                        changed = True
                        continue
                if self._is_annotated(value):
                    self.type_aliases[name] = value

    def _target_names(self, node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(name for item in node.elts for name in self._target_names(item))
        return ()

    def _assignment_scope(self, node: ast.Assign | ast.AnnAssign, name: str) -> int:
        if name.startswith("self."):
            return self._node_classes[id(node)] or self._node_scopes[id(node)]
        return self._node_scopes[id(node)]

    def _receiver_key(self, scope: int, name: str) -> tuple[int, str] | None:
        if not name:
            return None
        current: int | None = scope
        while current is not None:
            binding = (current, name)
            if binding in self.receivers:
                return binding
            if binding in self.bound_names:
                return None
            current = self._scope_parents[current]
        return None

    def _decorator(self, scope: int, name: str) -> tuple[str, str] | None:
        current: int | None = scope
        while current is not None:
            binding = (current, name)
            if binding in self.decorators:
                return self.decorators[binding]
            if binding in self.bound_names:
                return None
            current = self._scope_parents[current]
        return None

    def _constructor_is_hidden(self, node: ast.expr) -> bool:
        if not self._is_constructor_call(node) or not isinstance(node, ast.Call):
            return False
        value = next((keyword.value for keyword in node.keywords if keyword.arg == "include_in_schema"), None)
        return isinstance(value, ast.Constant) and value.value is False

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
        scope = self._route_scopes.get(id(function), 0)
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            method = ""
            receiver = ""
            receiver_key = None
            if isinstance(decorator.func, ast.Attribute):
                receiver = _binding_name(decorator.func.value)
                lookup_scope = self._node_classes[id(function)] if receiver.startswith("self.") else scope
                receiver_key = self._receiver_key(lookup_scope or scope, receiver)
                if receiver_key is not None:
                    method = decorator.func.attr
            elif isinstance(decorator.func, ast.Name) and (resolved := self._decorator(scope, decorator.func.id)):
                receiver, method = resolved
                receiver_key = self._receiver_key(scope, receiver)
            if method not in HTTP_METHODS or receiver_key is None:
                continue
            path_node = (
                decorator.args[0]
                if decorator.args
                else next((keyword.value for keyword in decorator.keywords if keyword.arg == "path"), None)
            )
            path = path_node.value if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str) else None
            route_methods = self._route_methods(decorator) if method == "api_route" else (method,)
            origin_scope, origin_name = self.receiver_origins[receiver_key]
            routes.extend(
                Route(
                    decorator=decorator,
                    receiver=f"{origin_scope}:{origin_name}",
                    method=route_method,
                    path=path,
                    inherited_hidden=receiver_key in self.hidden_receivers,
                )
                for route_method in route_methods
            )
        return tuple(routes)

    @staticmethod
    def _route_methods(decorator: ast.Call) -> tuple[str, ...]:
        value = next((keyword.value for keyword in decorator.keywords if keyword.arg == "methods"), None)
        if value is None:
            return ("get",)
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return ("*",)
        methods = {
            item.value.lower()
            for item in value.elts
            if isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value.lower() in HTTP_METHODS - {"api_route"}
        }
        return tuple(sorted(methods)) or ("*",)

    def canonical(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            if node.id in self.modules:
                return self.module_symbols[node.id]
            return self.symbols.get(node.id, "")
        if isinstance(node, ast.Attribute) and self._root_name(node) in self.modules:
            return node.attr
        if isinstance(node, ast.Attribute) and self._root_name(node) in self.http_modules:
            return node.attr
        return ""

    @staticmethod
    def _root_name(node: ast.Attribute) -> str:
        value: ast.expr = node
        while isinstance(value, ast.Attribute):
            value = value.value
        return value.id if isinstance(value, ast.Name) else ""

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
        if not isinstance(node, ast.Subscript):
            return False
        value = node.value
        if isinstance(value, ast.Name):
            return value.id in self.annotated
        return (
            isinstance(value, ast.Attribute)
            and value.attr == "Annotated"
            and self._root_name(value) in self.annotation_modules
        )

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

    def response_name(self, node: ast.expr | None) -> str:
        resolved = self.resolve_annotation(node)
        if not isinstance(resolved, (ast.Name, ast.Attribute)):
            return ""
        name = self.canonical(resolved)
        return name if name in RESPONSE_TYPES else ""

    def is_http_exception(self, node: ast.expr) -> bool:
        return self.canonical(node) == "HTTPException"
