from __future__ import annotations

import ast
from collections import defaultdict
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, final
from weakref import ReferenceType, ref

from sarj_python_lint.rules._ast_index import has_own_yield


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._runtime_bindings import RuntimeBindings


_RESOURCE_OWNERS = MappingProxyType(
    {
        "builtins": frozenset({"open"}),
        "io": frozenset({"open", "StringIO", "BytesIO"}),
        "tempfile": frozenset({"TemporaryFile", "NamedTemporaryFile"}),
        "httpx": frozenset({"Client", "AsyncClient"}),
        "asyncio": frozenset({"sleep", "CancelledError", "exceptions.CancelledError"}),
        "contextlib": frozenset({"ExitStack", "AsyncExitStack", "_BaseExitStack"}),
        "functools": frozenset({"cache", "lru_cache", "cached_property"}),
        "subprocess": frozenset({"Popen", "TimeoutExpired"}),
        "re": frozenset({"compile", "Match", "Pattern"}),
        "operator": frozenset({"setitem", "delitem", "iadd", "iconcat", "imul", "iand", "isub", "ixor", "ior"}),
        "unittest": frozenset({"mock.Mock", "mock.MagicMock", "mock.AsyncMock"}),
        "typing": frozenset({"final", "Literal", "Annotated", "cast", "assert_type"}),
        "typing_extensions": frozenset({"final", "Literal", "Annotated", "cast", "assert_type"}),
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


def builtin_namespace_untouched(context: PythonFileContext) -> bool:
    return not any(
        (isinstance(node, ast.Import) and any(alias.name == "builtins" for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module == "builtins")
        or (isinstance(node, ast.Name) and node.id == "__builtins__")
        for node in context.nodes(ast.Import, ast.ImportFrom, ast.Name)
    )


@final
class ResourceProvenance:
    def __init__(
        self, context: PythonFileContext, *, require_static_namespace: bool = False, borrow_context: bool = False
    ) -> None:
        self._context: PythonFileContext | ReferenceType[PythonFileContext] = (
            ref(context) if borrow_context else context
        )
        self.parents = context.parents
        self.require_static_namespace = require_static_namespace
        self.inventory = context.binding_inventory
        self.bindings = self.inventory.bindings
        self.reads = self.inventory.reads
        self._reads_by_binding: dict[str, dict[ast.AST, list[ast.Name]]] = {}
        self._runtime_reads_by_binding: dict[str, dict[ast.AST, list[ast.Name]]] = {}
        self._import_read_safety: dict[str, bool] = {}
        self.escape_cache: dict[tuple[ast.AST, bool], bool] = {}
        self.async_contract_cache: dict[ast.AsyncFunctionDef, bool] = {}
        self.import_contract_cache: dict[str, bool] = {}
        self.runtime_import_cache: dict[ast.alias, bool] = {}
        self.wildcard = self.inventory.wildcard
        # Some analyses refine mutation ownership for their own policy.
        self.mutated = set(self.inventory.mutated)
        self.external_bindings = self.inventory.external_bindings

    @property
    def context(self) -> PythonFileContext:
        context = self._context() if isinstance(self._context, ReferenceType) else self._context
        if context is None:
            msg = "The provenance file context has been released"
            raise ReferenceError(msg)
        return context

    @cached_property
    def builtin_namespace_untouched(self) -> bool:
        return builtin_namespace_untouched(self.context)

    def scope(self, node: ast.AST) -> ast.AST | None:
        return self.inventory.scope(node)

    def binding(self, name: str, at: ast.AST) -> ast.AST | None:
        scope = self.scope(at)
        while scope is not None:
            nodes = self.bindings.get(scope, {}).get(name)
            if nodes:
                return nodes[0] if len(nodes) == 1 or self._same_import_bindings(nodes) else None
            scope = self.scope(scope)
        return None

    @cached_property
    def runtime_bindings(self) -> RuntimeBindings:
        return self.context.runtime_bindings

    def runtime_binding(self, name: str, at: ast.AST) -> ast.AST | None:
        nodes = self.runtime_bindings.lookup(self.scope(at), name)
        if not nodes:
            return None
        return nodes[0] if len(nodes) == 1 or self._same_import_bindings(nodes) else None

    def runtime_import_name(self, node: ast.expr) -> str | None:
        root = _root_name(node)
        if self.wildcard or self.dynamic_namespace or root is None or root in self.mutated:
            return None
        binding = self.runtime_binding(root, node)
        if not isinstance(binding, ast.alias):
            return None
        qualified = import_name_for_binding(node, binding, self.parents.get(binding))
        if qualified is None or not self._owner_namespace_untouched(qualified.partition(".")[0]):
            return None
        if binding not in self.runtime_import_cache:
            reads = self._indexed_reads(
                root, binding, cache=self._runtime_reads_by_binding, resolve=self.runtime_binding
            )
            self.runtime_import_cache[binding] = all(self._safe_import_use(read) for read in reads)
        return qualified if self.runtime_import_cache[binding] else None

    @cached_property
    def mock_namespace_patching(self) -> bool:
        return any(
            self.runtime_import_name(node.func)
            in {
                "unittest.mock.patch",
                "unittest.mock.patch.object",
                "unittest.mock.patch.multiple",
                "unittest.mock.patch.dict",
            }
            for node in self.context.nodes(ast.Call)
        )

    @cached_property
    def imported_namespace_hazards(self) -> frozenset[Path]:
        hazards: set[Path] = set()
        for node in self.context.nodes(ast.Name, ast.Attribute):
            match node:
                case ast.Attribute(value=value, ctx=ast.Store() | ast.Del()):
                    hazards.update(self._namespace_paths(value, include_root=True))
                case ast.Name(ctx=ast.Load()) | ast.Attribute(ctx=ast.Load()) if not self._safe_import_use(node):
                    hazards.update(self._namespace_paths(node, include_root=False))
                case _:
                    pass
        return frozenset(hazards)

    @cached_property
    def _namespace_aliases(self) -> dict[str, tuple[ast.alias, ...]]:
        aliases: dict[str, list[ast.alias]] = defaultdict(list)
        for binding in self.context.nodes(ast.alias):
            parent = self.parents.get(binding)
            name = binding.asname or (
                binding.name.partition(".")[0] if isinstance(parent, ast.Import) else binding.name
            )
            aliases[name].append(binding)
        return {name: tuple(bindings) for name, bindings in aliases.items()}

    def _namespace_paths(self, expression: ast.expr, *, include_root: bool) -> set[Path]:
        attributes: list[str] = []
        root = expression
        while isinstance(root, ast.Attribute):
            attributes.append(root.attr)
            root = root.value
        if not isinstance(root, ast.Name):
            return set()
        binding = self.runtime_binding(root.id, expression)
        aliases: tuple[ast.alias, ...]
        match binding:
            case ast.alias():
                aliases = (binding,)
            case None:
                aliases = self._namespace_aliases.get(root.id, ())
            case _:
                return set()
        paths: set[Path] = set()
        for alias in aliases:
            path = self._namespace_module_path(alias, tuple(reversed(attributes)))
            if path is not None:
                paths.add(path)
            if include_root and attributes:
                base = self._namespace_module_path(alias, ())
                if base is not None:
                    paths.add(base)
        return paths

    def _namespace_module_path(self, binding: ast.alias, attributes: tuple[str, ...]) -> Path | None:
        parent = self.parents.get(binding)
        match parent:
            case ast.Import():
                prefix = binding.name if binding.asname else binding.name.partition(".")[0]
                level = 0
            case ast.ImportFrom(module=module, level=level):
                prefix = ".".join(part for part in (module, binding.name) if part)
            case _:
                return None
        module = ".".join((prefix, *attributes))
        return self.context.session.local_source.resolve_module(
            self.context.path, module, level, facts=self.context.session.first_party
        )

    def _same_import_bindings(self, nodes: Sequence[ast.AST]) -> bool:
        targets: set[tuple[str, str | None, int, str]] = set()
        for node in nodes:
            if not isinstance(node, ast.alias):
                return False
            parent = self.parents.get(node)
            match parent:
                case ast.Import():
                    targets.add(("import", None, 0, node.name))
                case ast.ImportFrom():
                    targets.add(("from", parent.module, parent.level, node.name))
                case _:
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
        if not self._import_reads_safe(root):
            return False
        return (
            isinstance(binding, ast.alias)
            and isinstance(self.scope(binding), ast.Module)
            and self.context.imports.resolved_qualified_name(node) == qualified
        )

    def _import_reads_safe(self, name: str) -> bool:
        if name not in self._import_read_safety:
            self._import_read_safety[name] = all(
                isinstance(self.parents.get(read), ast.Attribute | ast.ExceptHandler) or self._safe_import_use(read)
                for read in self.reads.get(name, ())
            )
        return self._import_read_safety[name]

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
        parent = self.parents.get(node)
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
                and self.context.imports.resolved_qualified_name(node)
                in {
                    "typing.final",
                    "typing_extensions.final",
                    "dataclasses.dataclass",
                    "functools.cache",
                    "functools.lru_cache",
                    "functools.cached_property",
                }
            )
        )

    def constructor(self, name: ast.Name, at: ast.AST) -> ast.Call | None:
        binding = self.binding(name.id, at)
        if not isinstance(binding, ast.Name):
            return None
        statement = self.parents.get(binding)
        if isinstance(statement, ast.withitem):
            owner = self.parents.get(statement)
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
        statement = self.parents.get(binding)
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
            return None
        if not isinstance(self.parents.get(statement), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
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
        return self.require_static_namespace and self.context.dynamic_namespace

    def _stable_async_definition(self, function: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef | None:
        owner = self.parents.get(function)
        if not isinstance(owner, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        if function.decorator_list or has_own_yield(function):
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
            for read in self.binding_reads(name, binding):
                alias = self._function_alias(read)
                if alias is not None:
                    pending.append(alias)
                elif not self._safe_async_read(read):
                    return False
        return True

    def _function_alias(self, read: ast.Name) -> ast.Name | None:
        parent = self.parents.get(read)
        if not isinstance(parent, ast.Assign | ast.AnnAssign) or parent.value is not read:
            return None
        if not isinstance(self.parents.get(parent), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            return None
        target = targets[0]
        return target if self.binding(target.id, target) is target else None

    def _safe_async_read(self, read: ast.Name) -> bool:
        parent = self.parents.get(read)
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

    def binding_reads(self, name: str, binding: ast.AST) -> list[ast.Name]:
        return self._indexed_reads(name, binding, cache=self._reads_by_binding, resolve=self.binding)

    def _indexed_reads(
        self,
        name: str,
        binding: ast.AST,
        *,
        cache: dict[str, dict[ast.AST, list[ast.Name]]],
        resolve: Callable[[str, ast.AST], ast.AST | None],
    ) -> list[ast.Name]:
        if name not in cache:
            grouped: dict[ast.AST, list[ast.Name]] = defaultdict(list)
            for read in self.reads.get(name, ()):
                if (owner := resolve(read.id, read)) is not None:
                    grouped[owner].append(read)
            cache[name] = grouped
        return cache[name].get(binding, [])

    def unescaped(self, name: ast.Name, at: ast.AST, *, allow_context: bool = False) -> bool:
        binding = self.binding(name.id, at)
        if self.dynamic_namespace or binding is None or name.id in self.mutated:
            return False
        key = (binding, allow_context)
        if key not in self.escape_cache:
            self.escape_cache[key] = all(
                self._method_or_context_read(read, allow_context=allow_context)
                for read in self.binding_reads(name.id, binding)
            )
        return self.escape_cache[key]

    def _method_or_context_read(self, read: ast.Name, *, allow_context: bool) -> bool:
        parent = self.parents.get(read)
        if allow_context and isinstance(parent, ast.withitem) and parent.context_expr is read:
            return True
        if (
            not isinstance(parent, ast.Attribute)
            or parent.value is not read
            or parent.attr in {"__setattr__", "__delattr__", "__getattribute__"}
        ):
            return False
        call = self.parents.get(parent)
        return isinstance(call, ast.Call) and call.func is parent

    def contains(self, owner: ast.AST | None, node: ast.AST) -> bool:
        while node in self.parents:
            node = self.parents[node]
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


def import_name_for_binding(expression: ast.expr, binding: ast.alias, parent: ast.AST | None) -> str | None:
    attributes: list[str] = []
    while isinstance(expression, ast.Attribute):
        attributes.append(expression.attr)
        expression = expression.value
    match parent:
        case ast.Import():
            prefix = binding.name if binding.asname else binding.name.partition(".")[0]
        case ast.ImportFrom(module=str(module), level=0):
            prefix = f"{module}.{binding.name}"
        case _:
            return None
    return ".".join((prefix, *reversed(attributes)))
