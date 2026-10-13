from __future__ import annotations

import ast
from collections import defaultdict
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._namespace_access import dynamic_namespace_access


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SCOPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
_RESOURCE_OWNERS = MappingProxyType(
    {
        "asyncio": frozenset({"sleep", "CancelledError", "exceptions.CancelledError"}),
        "contextlib": frozenset({"ExitStack", "AsyncExitStack", "_BaseExitStack"}),
        "subprocess": frozenset({"Popen", "TimeoutExpired"}),
        "re": frozenset({"compile", "Match", "Pattern"}),
        "unittest": frozenset({"mock.Mock", "mock.MagicMock", "mock.AsyncMock"}),
        "typing": frozenset({"final", "Literal", "Annotated"}),
        "typing_extensions": frozenset({"final", "Literal", "Annotated"}),
        "pydantic": frozenset(
            {
                "BaseModel",
                "main.BaseModel",
                "v1.BaseModel",
                "v1.main.BaseModel",
                "Field",
                "fields.Field",
                "v1.Field",
                "v1.fields.Field",
                "ConfigDict",
                "config.ConfigDict",
                "model_validator",
                "field_validator",
                "functional_validators.model_validator",
                "functional_validators.field_validator",
            }
        ),
    }
)


@final
class ResourceProvenance:
    def __init__(self, context: PythonFileContext, *, require_static_namespace: bool = False) -> None:
        self.context = context
        self.require_static_namespace = require_static_namespace
        self.bindings: dict[ast.AST | None, dict[str, list[ast.AST]]] = defaultdict(lambda: defaultdict(list))
        self.reads: dict[str, list[ast.Name]] = defaultdict(list)
        self._reads_by_binding: dict[str, dict[ast.AST, list[ast.Name]]] = {}
        self.escape_cache: dict[tuple[ast.AST, bool], bool] = {}
        self.async_contract_cache: dict[ast.AsyncFunctionDef, bool] = {}
        self.import_contract_cache: dict[str, bool] = {}
        self.wildcard = False
        self.mutated: set[str] = set()
        self.external_bindings: set[str] = set()
        for node in context.nodes(ast.AST):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.reads[node.id].append(node)

            for name in _bound_names(node):
                self.bindings[self.scope(node)][name].append(node)
                self.wildcard |= name == "*"
            if isinstance(node, ast.Global | ast.Nonlocal):
                self.external_bindings.update(node.names)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
                root = _root_name(node)
                if root is not None:
                    self.mutated.add(root)

    @cached_property
    def builtin_namespace_untouched(self) -> bool:
        return not any(
            (isinstance(node, ast.Import) and any(alias.name == "builtins" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "builtins")
            or (isinstance(node, ast.Name) and node.id == "__builtins__")
            for node in self.context.nodes(ast.Import, ast.ImportFrom, ast.Name)
        )

    def scope(self, node: ast.AST) -> ast.AST | None:
        parent = self.context.parents.get(node)
        while parent is not None and not isinstance(parent, _SCOPES):
            parent = self.context.parents.get(parent)
        return parent

    def binding(self, name: str, at: ast.AST) -> ast.AST | None:
        scope = self.scope(at)
        while scope is not None:
            nodes = self.bindings.get(scope, {}).get(name)
            if nodes:
                return nodes[0] if len(nodes) == 1 or self._same_import_bindings(nodes) else None
            scope = self.scope(scope)
        return None

    def _same_import_bindings(self, nodes: list[ast.AST]) -> bool:
        targets: set[tuple[str, str | None, int, str]] = set()
        for node in nodes:
            if not isinstance(node, ast.alias):
                return False
            parent = self.context.parents.get(node)
            if isinstance(parent, ast.Import):
                targets.add(("import", None, 0, node.name))
            elif isinstance(parent, ast.ImportFrom):
                targets.add(("from", parent.module, parent.level, node.name))
            else:
                return False
        return len(targets) == 1

    def imported(self, node: ast.expr, qualified: str) -> bool:
        root = _root_name(node)
        if (
            self.wildcard
            or self.dynamic_namespace
            or root is None
            or root in self.mutated
            or not self._owner_namespace_untouched(qualified.partition(".")[0])
        ):
            return False
        binding = self.binding(root, node)
        for read in self.reads.get(root, ()):
            parent = self.context.parents.get(read)
            if isinstance(parent, ast.Attribute | ast.ExceptHandler):
                continue
            if not self._safe_import_use(read):
                return False
        return (
            isinstance(binding, ast.alias)
            and isinstance(self.scope(binding), ast.Module)
            and self.context.imports.resolved_qualified_name(node) == qualified
        )

    def _owner_namespace_untouched(self, module: str) -> bool:
        if module not in _RESOURCE_OWNERS:
            return True
        if module not in self.import_contract_cache:
            self.import_contract_cache[module] = self._inspect_owner_namespace(module)
        return self.import_contract_cache[module]

    def _inspect_owner_namespace(self, module: str) -> bool:
        origins: dict[str, set[str]] = defaultdict(set)
        for node in self.context.nodes(ast.Import, ast.ImportFrom):
            for name, target in _owner_import_targets(node, module).items():
                origins[name].add(target)
        if not self.mutated.isdisjoint(origins):
            return False
        owners = frozenset(f"{module}.{name}" for name in _RESOURCE_OWNERS[module])
        return all(
            self._safe_import_use(node)
            for node in self.context.nodes(ast.Name, ast.Attribute)
            if self._owner_reference(node, origins, owners)
        )

    def _owner_reference(
        self, node: ast.Name | ast.Attribute, origins: dict[str, set[str]], owners: frozenset[str]
    ) -> bool:
        if not isinstance(node.ctx, ast.Load):
            return False
        if isinstance(node, ast.Name):
            return node.id in origins
        return any(
            qualified == owner or qualified.startswith(owner + ".") or owner.startswith(qualified + ".")
            for qualified in _owner_attribute_targets(node, origins)
            for owner in owners
        )

    def _safe_import_use(self, node: ast.Name | ast.Attribute) -> bool:
        parent = self.context.parents.get(node)
        return (
            (isinstance(parent, ast.Attribute) and parent.value is node)
            or (isinstance(parent, ast.Call) and parent.func is node)
            or (isinstance(parent, ast.ExceptHandler) and parent.type is node)
            or (isinstance(parent, ast.ClassDef) and node in parent.bases)
            or (isinstance(parent, ast.Subscript) and parent.value is node)
            or (isinstance(parent, ast.arg | ast.AnnAssign) and parent.annotation is node)
            or (isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is node)
            or (
                isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and node in parent.decorator_list
                and self.context.imports.resolved_qualified_name(node) in {"typing.final", "typing_extensions.final"}
            )
        )

    def constructor(self, name: ast.Name, at: ast.AST) -> ast.Call | None:
        binding = self.binding(name.id, at)
        if not isinstance(binding, ast.Name):
            return None
        statement = self.context.parents.get(binding)
        if isinstance(statement, ast.withitem):
            owner = self.context.parents.get(statement)
            if (
                binding is statement.optional_vars
                and self.contains(owner, at)
                and isinstance(statement.context_expr, ast.Call)
            ):
                return statement.context_expr
            return None
        value = self.assignment_value(binding, at)
        return value if isinstance(value, ast.Call) else None

    def assignment_value(self, binding: ast.Name, at: ast.AST) -> ast.expr | None:
        statement = self.context.parents.get(binding)
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
            return None
        if not isinstance(self.context.parents.get(statement), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        return statement.value if statement.lineno < getattr(at, "lineno", 0) else None

    def async_function(self, value: ast.expr, at: ast.AST) -> ast.AsyncFunctionDef | None:
        if self.dynamic_namespace:
            return None
        seen: set[str] = set()
        while isinstance(value, ast.Name) and value.id not in seen:
            seen.add(value.id)
            if value.id in self.mutated:
                return None
            binding = self.binding(value.id, at)
            if isinstance(binding, ast.AsyncFunctionDef):
                return self._stable_async_definition(binding)
            if not isinstance(binding, ast.Name):
                return None
            resolved = self.assignment_value(binding, at)
            if resolved is None:
                return None
            value, at = resolved, binding
        return None

    @cached_property
    def dynamic_namespace(self) -> bool:
        return self.require_static_namespace and dynamic_namespace_access(
            self.context.nodes(ast.AST), self.context.imports, self.context.parents
        )

    def _stable_async_definition(self, function: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef | None:
        owner = self.context.parents.get(function)
        if not isinstance(owner, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        if function.decorator_list or any(isinstance(node, ast.Yield | ast.YieldFrom) for node in ast.walk(function)):
            return None
        if function not in self.async_contract_cache:
            self.async_contract_cache[function] = self._async_aliases_untouched(function)
        return function if self.async_contract_cache[function] else None

    def _async_aliases_untouched(self, function: ast.AsyncFunctionDef) -> bool:
        pending: list[ast.AsyncFunctionDef | ast.Name] = [function]
        seen: set[ast.AST] = set()
        while pending:
            binding = pending.pop()
            if binding in seen:
                continue
            seen.add(binding)
            name = binding.id if isinstance(binding, ast.Name) else binding.name
            if name in self.mutated or name in self.external_bindings:
                return False
            for read in self._binding_reads(name, binding):
                alias = self._function_alias(read)
                if alias is not None:
                    pending.append(alias)
                elif not self._safe_async_read(read):
                    return False
        return True

    def _function_alias(self, read: ast.Name) -> ast.Name | None:
        parent = self.context.parents.get(read)
        if not isinstance(parent, ast.Assign | ast.AnnAssign) or parent.value is not read:
            return None
        if not isinstance(self.context.parents.get(parent), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            return None
        target = targets[0]
        return target if self.binding(target.id, target) is target else None

    def _safe_async_read(self, read: ast.Name) -> bool:
        parent = self.context.parents.get(read)
        if not isinstance(parent, ast.Call):
            return False
        if parent.func is read:
            return True
        if not parent.args or parent.args[0] is not read or not isinstance(parent.func, ast.Attribute):
            return False
        receiver = parent.func.value
        if parent.func.attr not in {"callback", "push_async_callback"} or not isinstance(receiver, ast.Name):
            return False
        if not self.unescaped(receiver, parent, allow_context=True):
            return False
        constructor = self.constructor(receiver, parent)
        return (
            constructor is not None
            and not constructor.args
            and not constructor.keywords
            and any(self.imported(constructor.func, f"contextlib.{kind}") for kind in ("ExitStack", "AsyncExitStack"))
        )

    def _binding_reads(self, name: str, binding: ast.AST) -> list[ast.Name]:
        if name not in self._reads_by_binding:
            grouped: dict[ast.AST, list[ast.Name]] = defaultdict(list)
            for read in self.reads.get(name, ()):
                if (owner := self.binding(read.id, read)) is not None:
                    grouped[owner].append(read)
            self._reads_by_binding[name] = grouped
        return self._reads_by_binding[name].get(binding, [])

    def unescaped(self, name: ast.Name, at: ast.AST, *, allow_context: bool = False) -> bool:
        binding = self.binding(name.id, at)
        if self.dynamic_namespace or binding is None or name.id in self.mutated:
            return False
        key = (binding, allow_context)
        if key not in self.escape_cache:
            self.escape_cache[key] = all(
                self._method_or_context_read(read, allow_context=allow_context)
                for read in self._binding_reads(name.id, binding)
            )
        return self.escape_cache[key]

    def _method_or_context_read(self, read: ast.Name, *, allow_context: bool) -> bool:
        parent = self.context.parents.get(read)
        if allow_context and isinstance(parent, ast.withitem) and parent.context_expr is read:
            return True
        if (
            not isinstance(parent, ast.Attribute)
            or parent.value is not read
            or parent.attr in {"__setattr__", "__delattr__", "__getattribute__"}
        ):
            return False
        call = self.context.parents.get(parent)
        return isinstance(call, ast.Call) and call.func is parent

    def contains(self, owner: ast.AST | None, node: ast.AST) -> bool:
        while node in self.context.parents:
            node = self.context.parents[node]
            if node is owner:
                return True
        return False


def _owner_import_targets(node: ast.Import | ast.ImportFrom, module: str) -> dict[str, str]:
    if isinstance(node, ast.ImportFrom):
        return _owner_from_targets(node, module)
    targets: dict[str, str] = {}
    for alias in node.names:
        if alias.name == module or alias.name.startswith(module + "."):
            targets[alias.asname or alias.name.partition(".")[0]] = alias.name if alias.asname else module
    return targets


def _owner_from_targets(node: ast.ImportFrom, module: str) -> dict[str, str]:
    if node.module is None or not (node.module == module or node.module.startswith(module + ".")):
        return {}
    owners = frozenset(f"{module}.{name}" for name in _RESOURCE_OWNERS[module])
    targets: dict[str, str] = {}
    for alias in node.names:
        target = f"{node.module}.{alias.name}"
        if any(owner == target or owner.startswith(target + ".") for owner in owners):
            targets[alias.asname or alias.name] = target
    return targets


def _owner_attribute_targets(node: ast.Attribute, origins: dict[str, set[str]]) -> frozenset[str]:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return frozenset()
    suffix = ".".join(reversed(parts))
    return frozenset(f"{origin}.{suffix}" for origin in origins.get(current.id, ()))


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
            return (name,)
        case ast.alias():
            return (node.asname or node.name.partition(".")[0],)
        case (
            ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
        ):
            return (name,)
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return tuple(names)
        case _:
            return ()
