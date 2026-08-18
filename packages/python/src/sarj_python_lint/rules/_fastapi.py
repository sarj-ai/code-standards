from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple


if TYPE_CHECKING:
    from pathlib import Path


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
_DEPENDENCY_MARKERS = frozenset({"Depends", "Security"})
_MAX_IMPORTED_MODULE_BYTES = 500_000
_MAX_IMPORT_HOPS = 8
_MAX_PATH_ANCESTORS = 32


@dataclass(frozen=True, slots=True)
class Route:
    decorator: ast.Call
    receiver: str
    method: str
    path: str | None
    receiver_kind: Literal["FastAPI", "APIRouter"]
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


class AnnotatedParts(NamedTuple):
    value: ast.expr
    metadata: tuple[ast.expr, ...]


class ParameterMarker(NamedTuple):
    name: str
    call: ast.Call


class _ReceiverKey(NamedTuple):
    scope: int
    name: str


class _DecoratorBinding(NamedTuple):
    receiver: str
    method: str


@dataclass(frozen=True, slots=True)
class _ImportedReference:
    module: str
    level: int
    symbol: str


def flat_name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _binding_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return f"self.{node.attr}"
    return ""


class FastapiIndex:
    def __init__(self, tree: ast.Module, *, path: Path | None = None) -> None:
        self.tree: ast.Module = tree
        self.path: Path | None = path
        self._imported_dependency_cache: dict[_ImportedReference, bool] = {}
        self._imported_module_cache: dict[Path, ast.Module | None] = {}
        self.modules: set[str] = set()
        self.module_symbols: dict[str, str] = {}
        self.http_modules: set[str] = set()
        self.annotation_modules: set[str] = set()
        self.constructors: set[str] = set()
        self.annotated: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.type_aliases: dict[str, ast.expr] = {}
        self.receivers: set[_ReceiverKey] = set()
        self.receiver_origins: dict[_ReceiverKey, _ReceiverKey] = {}
        self.receiver_kinds: dict[_ReceiverKey, Literal["FastAPI", "APIRouter"]] = {}
        self.hidden_receivers: set[_ReceiverKey] = set()
        self.decorators: dict[_ReceiverKey, _DecoratorBinding] = {}
        self.bound_names: set[_ReceiverKey] = set()
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
                self.bound_names.add(_ReceiverKey(self._node_scopes[id(node)], node.name))
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if node.args.vararg is not None:
                    arguments.append(node.args.vararg)
                if node.args.kwarg is not None:
                    arguments.append(node.args.kwarg)
                self.bound_names.update(_ReceiverKey(node.lineno, argument.arg) for argument in arguments)
            elif isinstance(node, ast.ClassDef):
                self.bound_names.add(_ReceiverKey(self._node_scopes[id(node)], node.name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.bound_names.update(
                    _ReceiverKey(self._node_scopes[id(node)], alias.asname or alias.name.split(".")[0])
                    for alias in node.names
                )
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self.bound_names.update(
                    _ReceiverKey(self._node_scopes[id(node)], name) for name in self._target_names(node.target)
                )
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars is not None:
                        self.bound_names.update(
                            _ReceiverKey(self._node_scopes[id(node)], name)
                            for name in self._target_names(item.optional_vars)
                        )
            elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                self.bound_names.add(_ReceiverKey(self._node_scopes[id(node)], node.name))
            elif isinstance(node, ast.NamedExpr):
                self.bound_names.update(
                    _ReceiverKey(self._node_scopes[id(node)], name) for name in self._target_names(node.target)
                )
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = _binding_name(node.targets[0])
                if name:
                    assignments.append((self._assignment_scope(node, name), name, node.value))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                name = _binding_name(node.target)
                if name:
                    assignments.append((self._assignment_scope(node, name), name, node.value))
            elif isinstance(node, ast.TypeAlias):
                assignments.append((self._node_scopes[id(node)], node.name.id, node.value))

        changed = True
        counts = Counter(_ReceiverKey(scope, name) for scope, name, _value in assignments)
        self.bound_names.update(counts)
        while changed:
            changed = False
            for scope, name, value in assignments:
                key = _ReceiverKey(scope, name)
                if counts[key] != 1:
                    continue
                if key in self.receivers or key in self.decorators:
                    continue
                source = self._receiver_key(scope, _binding_name(value))
                constructor_kind = self._constructor_kind(value)
                if constructor_kind is not None:
                    self.receivers.add(key)
                    self.receiver_origins[key] = key
                    self.receiver_kinds[key] = constructor_kind
                    if self._constructor_is_hidden(value):
                        self.hidden_receivers.add(key)
                    changed = True
                    continue
                if source is not None:
                    self.receivers.add(key)
                    self.receiver_origins[key] = self.receiver_origins[source]
                    self.receiver_kinds[key] = self.receiver_kinds[source]
                    if source in self.hidden_receivers:
                        self.hidden_receivers.add(key)
                    changed = True
                    continue
                if isinstance(value, ast.Attribute) and value.attr in HTTP_METHODS:
                    receiver = _binding_name(value.value)
                    if self._receiver_key(scope, receiver) is not None:
                        self.decorators[key] = _DecoratorBinding(receiver, value.attr)
                        changed = True
                        continue
                if self._is_annotated(value) or (isinstance(value, ast.Name) and value.id in self.type_aliases):
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

    def _receiver_key(self, scope: int, name: str) -> _ReceiverKey | None:
        if not name:
            return None
        current: int | None = scope
        while current is not None:
            binding = _ReceiverKey(current, name)
            if binding in self.receivers:
                return binding
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
        return self._constructor_kind(node) is not None

    def _constructor_kind(self, node: ast.expr) -> Literal["FastAPI", "APIRouter"] | None:
        if not isinstance(node, ast.Call):
            return None
        if isinstance(node.func, ast.Name):
            canonical = self.symbols.get(node.func.id)
            if canonical == "FastAPI":
                return "FastAPI"
            if canonical == "APIRouter":
                return "APIRouter"
            return None
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.modules
            and node.func.attr in {"FastAPI", "APIRouter"}
        ):
            return "FastAPI" if node.func.attr == "FastAPI" else "APIRouter"
        return None

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
                receiver = resolved.receiver
                method = resolved.method
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
            origin = self.receiver_origins[receiver_key]
            routes.extend(
                Route(
                    decorator=decorator,
                    receiver=f"{origin.scope}:{origin.name}",
                    method=route_method,
                    path=path,
                    receiver_kind=self.receiver_kinds[receiver_key],
                    inherited_hidden=receiver_key in self.hidden_receivers,
                )
                for route_method in route_methods
            )
        return tuple(routes)

    def _decorator(self, scope: int, name: str) -> _DecoratorBinding | None:
        current: int | None = scope
        while current is not None:
            binding = _ReceiverKey(current, name)
            if binding in self.decorators:
                return self.decorators[binding]
            if binding in self.bound_names:
                return None
            current = self._scope_parents[current]
        return None

    @staticmethod
    def _route_methods(decorator: ast.Call) -> tuple[str, ...]:
        value = next((keyword.value for keyword in decorator.keywords if keyword.arg == "methods"), None)
        if value is None:
            return ("get",)
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return ("*",)
        methods = {
            method
            for item in value.elts
            if isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and (method := item.value.lower()) in HTTP_METHODS - {"api_route"}
        }
        return tuple(sorted(methods)) or ("*",)

    def canonical(self, node: ast.expr) -> str:
        match node:
            case ast.Name(id=name) if name in self.modules:
                return self.module_symbols[name]
            case ast.Name(id=name):
                return self.symbols.get(name, "")
            case ast.Attribute(attr=attribute) if (
                self._root_name(node) in self.modules or self._root_name(node) in self.http_modules
            ):
                return attribute
            case _:
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

    def annotated_parts(self, node: ast.expr | None) -> AnnotatedParts | None:
        resolved = self.resolve_annotation(node)
        if not self._is_annotated(resolved) or not isinstance(resolved, ast.Subscript):
            return None
        elements = resolved.slice.elts if isinstance(resolved.slice, ast.Tuple) else [resolved.slice]
        if not elements:
            return None
        return AnnotatedParts(elements[0], tuple(elements[1:]))

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

    def marker(self, node: ast.expr) -> ParameterMarker | None:
        if not isinstance(node, ast.Call):
            return None
        canonical = self.canonical(node.func)
        if canonical not in PARAM_MARKERS:
            return None
        return ParameterMarker(canonical, node)

    def is_injection(self, node: ast.expr | None) -> bool:
        resolved = self.resolve_annotation(node)
        return isinstance(resolved, (ast.Name, ast.Attribute)) and self.canonical(resolved) in INJECTION_TYPES

    def is_imported_dependency_alias(self, node: ast.expr | None) -> bool:
        if self.path is None or node is None or isinstance(node, ast.Constant):
            return False
        reference = _imported_reference(self.tree, node)
        if reference is None or self._is_shadowed_in_enclosing_scope(node):
            return False
        if reference in self._imported_dependency_cache:
            return self._imported_dependency_cache[reference]
        target = _resolve_module_path(self.path, reference)
        if target is None:
            return False
        resolved = _module_symbol_is_dependency_alias(
            target,
            reference.symbol,
            set(),
            self._imported_module_cache,
            0,
        )
        self._imported_dependency_cache[reference] = resolved
        return resolved

    def _is_shadowed_in_enclosing_scope(self, node: ast.expr) -> bool:
        root = flat_name(node)
        if isinstance(node, ast.Attribute):
            root = self._root_name(node)
        node_scope = self._node_scopes.get(id(node), 0)
        # An annotation is evaluated outside the function whose signature owns
        # it, so begin with that function's parent scope.
        scope: int | None = self._scope_parents.get(node_scope)
        while scope is not None and scope != 0:
            if _ReceiverKey(scope, root) in self.bound_names:
                return True
            scope = self._scope_parents.get(scope)
        return False

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


def _imported_reference(tree: ast.Module, node: ast.expr) -> _ImportedReference | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value.strip(), mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.Name):
        binding = _unique_module_binding(tree, node.id)
        if not isinstance(binding, ast.ImportFrom):
            return None
        imported = next(
            (alias for alias in binding.names if alias.name != "*" and (alias.asname or alias.name) == node.id),
            None,
        )
        if imported is None:
            return None
        return _ImportedReference(binding.module or "", binding.level, imported.name)
    if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
        return None
    binding = _unique_module_binding(tree, node.value.id)
    if isinstance(binding, ast.Import):
        imported = next(
            (alias for alias in binding.names if alias.asname == node.value.id),
            None,
        )
        if imported is not None:
            return _ImportedReference(imported.name, 0, node.attr)
    if isinstance(binding, ast.ImportFrom):
        imported = next(
            (alias for alias in binding.names if alias.name != "*" and (alias.asname or alias.name) == node.value.id),
            None,
        )
        if imported is not None:
            module = ".".join(part for part in (binding.module or "", imported.name) if part)
            return _ImportedReference(module, binding.level, node.attr)
    return None


def _unique_module_binding(tree: ast.Module, name: str) -> ast.stmt | None:
    bindings = [statement for statement in tree.body if _statement_binds(statement, name)]
    return bindings[0] if len(bindings) == 1 else None


def _statement_binds(statement: ast.stmt, name: str) -> bool:
    match statement:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return statement.name == name
        case ast.Import() | ast.ImportFrom():
            return any((alias.asname or alias.name.split(".")[0]) == name for alias in statement.names)
        case ast.Assign():
            return any(name in _stored_names(target) for target in statement.targets)
        case ast.AnnAssign() | ast.AugAssign():
            return name in _stored_names(statement.target)
        case ast.TypeAlias():
            return statement.name.id == name
        case (
            ast.If()
            | ast.For()
            | ast.AsyncFor()
            | ast.While()
            | ast.With()
            | ast.AsyncWith()
            | ast.Try()
            | ast.TryStar()
            | ast.Match()
        ):
            return any(_statement_binds(child, name) for block in _owned_statement_blocks(statement) for child in block)
        case _:
            return False


def _stored_names(node: ast.expr) -> frozenset[str]:
    return frozenset(
        child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    )


def _owned_statement_blocks(statement: ast.stmt) -> tuple[list[ast.stmt], ...]:
    match statement:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return statement.body, statement.orelse
        case ast.With() | ast.AsyncWith():
            return (statement.body,)
        case ast.Try() | ast.TryStar():
            return (
                statement.body,
                statement.orelse,
                statement.finalbody,
                *(handler.body for handler in statement.handlers),
            )
        case ast.Match(cases=cases):
            return tuple(case.body for case in cases)
        case _:
            return ()


def _resolve_module_path(current: Path, reference: _ImportedReference) -> Path | None:
    current = current.resolve()
    checkout = _checkout_root(current)
    if checkout is None:
        return _resolve_module_path_without_checkout(current, reference)
    module_parts = tuple(part for part in reference.module.split(".") if part)
    candidates: set[Path] = set()
    if 0 < reference.level <= _MAX_PATH_ANCESTORS:
        base = current.parent
        for _ in range(reference.level - 1):
            base = base.parent
        module_base = base.joinpath(*module_parts)
        candidates.update(_existing_module_files(module_base, checkout))
    elif module_parts:
        first = module_parts[0]
        try:
            parent_parts = current.parent.relative_to(checkout).parts
        except ValueError:
            return None
        for index, part in enumerate(parent_parts[:_MAX_PATH_ANCESTORS]):
            if part != first:
                continue
            anchor = checkout.joinpath(*parent_parts[:index])
            candidates.update(_existing_module_files(anchor.joinpath(*module_parts), checkout))
    return next(iter(candidates)) if len(candidates) == 1 else None


def _resolve_module_path_without_checkout(current: Path, reference: _ImportedReference) -> Path | None:
    module_parts = tuple(part for part in reference.module.split(".") if part)
    candidates: set[Path] = set()
    if 0 < reference.level <= _MAX_PATH_ANCESTORS:
        package = current.parent
        if not (package / "__init__.py").is_file():
            return None
        for _ in range(reference.level - 1):
            parent = package.parent
            if not (parent / "__init__.py").is_file():
                return None
            package = parent
        candidates.update(_existing_module_files(package.joinpath(*module_parts), package))
    elif module_parts:
        first = module_parts[0]
        for depth, ancestor in enumerate(current.parent.parents):
            if depth >= _MAX_PATH_ANCESTORS:
                break
            package = ancestor / first
            if package != current.parent and not current.is_relative_to(package):
                continue
            candidates.update(_existing_module_files(ancestor.joinpath(*module_parts), ancestor))
        # A detached directory of modules is also a valid, deliberately narrow
        # import root. Do not search any of its parents for an unrelated module.
        candidates.update(_existing_module_files(current.parent.joinpath(*module_parts), current.parent))
    return next(iter(candidates)) if len(candidates) == 1 else None


def _checkout_root(current: Path) -> Path | None:
    for depth, ancestor in enumerate(current.parents):
        if depth >= _MAX_PATH_ANCESTORS:
            break
        if (ancestor / ".git").exists():
            return ancestor.resolve()
    return None


def _existing_module_files(base: Path, checkout: Path) -> frozenset[Path]:
    candidates = (base.with_suffix(".py"), base / "__init__.py")
    resolved: set[Path] = set()
    for candidate in candidates:
        if not candidate.is_file() or _has_symlink_component(candidate, checkout):
            continue
        target = candidate.resolve()
        if target.is_relative_to(checkout):
            resolved.add(target)
    return frozenset(resolved)


def _has_symlink_component(path: Path, checkout: Path) -> bool:
    try:
        relative = path.relative_to(checkout)
    except ValueError:
        return True
    current = checkout
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _module_symbol_is_dependency_alias(
    path: Path,
    symbol: str,
    seen: set[tuple[Path, str]],
    module_cache: dict[Path, ast.Module | None],
    depth: int,
) -> bool:
    if depth >= _MAX_IMPORT_HOPS:
        return False
    key = (path, symbol)
    if key in seen:
        return False
    seen.add(key)
    tree = _read_module(path, module_cache)
    if tree is None:
        return False
    binding = _unique_module_binding(tree, symbol)
    expression = _binding_expression(binding, symbol)
    if expression is not None:
        if isinstance(expression, ast.Name):
            return _module_symbol_is_dependency_alias(
                path,
                expression.id,
                seen,
                module_cache,
                depth + 1,
            )
        imported = _imported_reference(tree, expression)
        if imported is not None:
            target = _resolve_module_path(path, imported)
            return target is not None and _module_symbol_is_dependency_alias(
                target,
                imported.symbol,
                seen,
                module_cache,
                depth + 1,
            )
        index = FastapiIndex(tree)
        parts = index.annotated_parts(expression)
        if parts is None:
            return False
        markers = [marker for item in parts.metadata if (marker := index.marker(item)) is not None]
        return len(markers) == 1 and markers[0].name in _DEPENDENCY_MARKERS
    if isinstance(binding, ast.ImportFrom):
        imported = _imported_reference(tree, ast.Name(id=symbol))
        if imported is None:
            return False
        target = _resolve_module_path(path, imported)
        return target is not None and _module_symbol_is_dependency_alias(
            target,
            imported.symbol,
            seen,
            module_cache,
            depth + 1,
        )
    return False


def _binding_expression(binding: ast.stmt | None, symbol: str) -> ast.expr | None:
    if isinstance(binding, ast.Assign) and len(binding.targets) == 1:
        target = binding.targets[0]
        if isinstance(target, ast.Name) and target.id == symbol:
            return binding.value
    if isinstance(binding, ast.AnnAssign) and isinstance(binding.target, ast.Name) and binding.target.id == symbol:
        return binding.value
    if isinstance(binding, ast.TypeAlias) and binding.name.id == symbol:
        return binding.value
    return None


def _read_module(path: Path, cache: dict[Path, ast.Module | None]) -> ast.Module | None:
    if path in cache:
        return cache[path]
    try:
        if path.stat().st_size > _MAX_IMPORTED_MODULE_BYTES:
            tree = None
        else:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except OSError, SyntaxError:
        tree = None
    cache[path] = tree
    return tree
