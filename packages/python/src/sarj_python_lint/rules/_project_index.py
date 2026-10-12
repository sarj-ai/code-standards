from __future__ import annotations

import ast
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from functools import cached_property
from itertools import chain
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint._source import read_python_source, symbol_prefilter_source
from sarj_python_lint.rules._ast_index import NodeIndex, children, nodes, walk as walk_ast
from sarj_python_lint.rules._first_party import FirstPartyFacts, project_root
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence, Set as AbstractSet
    from typing import Self


_SKIP_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "vendor",
        "vendored",
        "venv",
    }
)
_MAX_ROOTS = 8
_MAX_DIRS_PER_ROOT = 3_000
_MAX_FILES_PER_ROOT = 10_000
_MAX_FILE_BYTES = 500_000
_MAX_SOURCE_CHARS_PER_ROOT = 50_000_000
_MAX_VALUE_ORIGIN_STATES = 4_096
_NEW_TYPE_MIN_ARGS = 2
_CLASS_VALUE_NODES = (ast.Name, ast.Attribute)
_BUILTIN_TYPE_PROVIDERS = frozenset({"dict", "frozenset", "list", "set", "tuple", "type"})
_GENERIC_TYPE_SOURCES = frozenset({"typing", "typing_extensions", "collections.abc"})
_TYPE_PROVIDER_NAMESPACES = _GENERIC_TYPE_SOURCES | {"collections", "builtins"}
_TYPE_HELPER_CALLS = frozenset(
    {
        "TypeVar",
        "TypeVarTuple",
        "ParamSpec",
        "NewType",
        "NamedTuple",
        "TypedDict",
        "TypeAliasType",
        "cast",
        "final",
        "override",
        "overload",
        "get_type_hints",
        "get_args",
        "get_origin",
        "assert_type",
        "assert_never",
        "reveal_type",
        "runtime_checkable",
        "dataclass_transform",
    }
)
_GENERIC_TYPE_PROVIDERS = frozenset(
    {
        "AsyncGenerator",
        "AsyncIterable",
        "AsyncIterator",
        "Awaitable",
        "Callable",
        "ClassVar",
        "Collection",
        "Container",
        "Coroutine",
        "Dict",
        "Final",
        "FrozenSet",
        "Generator",
        "Generic",
        "Iterable",
        "Iterator",
        "List",
        "Mapping",
        "MutableMapping",
        "MutableSequence",
        "MutableSet",
        "NotRequired",
        "Optional",
        "Protocol",
        "ReadOnly",
        "Required",
        "Sequence",
        "Set",
        "Tuple",
        "Type",
        "Union",
    }
)
_TYPE_CONTEXT_PARENTS = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Module,
    ast.Lambda,
    ast.arg,
    ast.AnnAssign,
    ast.Call,
)


@dataclass(frozen=True, slots=True)
class SymbolRef:
    module: str
    name: str


@dataclass(frozen=True, slots=True)
class ClassSummary:
    symbol: SymbolRef
    fields: Mapping[str, ast.expr]
    bases: tuple[SymbolRef, ...]
    is_enum: bool


@dataclass(frozen=True, slots=True)
class SourceUnit:
    path: Path
    module: str | None
    source: str
    tree: ast.Module | None
    imports: Mapping[str, SymbolRef]


@dataclass(frozen=True, slots=True)
class LoadedSource:
    path: Path
    source: str


@dataclass(frozen=True, slots=True)
class _ClassValueUse:
    reference: ast.Name | ast.Attribute
    type_or_constructor: bool
    namespace_value: bool


@dataclass(frozen=True, slots=True)
class _TypeProviderFacts:
    imports: ImportIndex
    opaque: bool


def imports_outside(tree: ast.Module | None, modules: frozenset[str]) -> bool:
    if tree is None:
        return True
    for node in walk_ast(tree):
        if isinstance(node, ast.Import) and any(alias.name not in modules for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.level != 0 or node.module not in modules):
            return True
    return False


@final
class ProjectIndexSet:
    def __init__(self, units: Mapping[Path, SourceUnit], roots: Sequence[Path] = ()) -> None:
        self._units = MappingProxyType(dict(units))
        self._roots = tuple(roots)
        self._namespace_mutation: dict[str, bool] = {}
        self._canonical_values: dict[SymbolRef, tuple[SymbolRef, ...]] = {}
        self._type_providers: dict[ast.Module, _TypeProviderFacts] = {}
        self._bound_value_prefixes: dict[str, bool] = {}
        self._value_origins_incomplete = False
        by_module = {unit.module: unit for unit in units.values() if unit.module is not None}
        self._by_module = MappingProxyType(by_module)
        classes: dict[SymbolRef, ClassSummary] = {}
        nominals: dict[str, set[SymbolRef]] = {}
        _collect_unit_symbols(units, classes, nominals)
        self._classes = MappingProxyType(classes)
        self._nominals = MappingProxyType({key: frozenset(value) for key, value in nominals.items()})

    @classmethod
    def build(
        cls,
        paths: Sequence[Path],
        loaded: Mapping[Path, str],
        *,
        facts: FirstPartyFacts | None = None,
    ) -> Self:
        roots = _project_roots(paths, facts=facts)
        sources: dict[Path, str] = {}
        for path, source in loaded.items():
            try:
                sources[path.resolve()] = source
            except OSError:
                continue
        for root in roots:
            _load_root_sources(root, sources)
        return cls(_units(sources, roots), roots)

    @classmethod
    def single(cls, path: Path, source: str) -> Self:
        return cls(_units({path: source}))

    def with_unit(self, unit: SourceUnit) -> Self:
        return type(self)({**self._units, unit.path: unit}, self._roots)

    def unit(self, path: Path) -> SourceUnit | None:
        direct = self._units.get(path)
        if direct is not None:
            return direct
        try:
            return self._units.get(path.resolve())
        except OSError:
            return None

    def unit_or_source(self, path: Path, source: str, tree: ast.Module) -> SourceUnit | None:
        indexed = self.unit(path)
        if indexed is not None:
            return indexed
        module = _module_name(path, self._roots)
        if module is None:
            return None
        return SourceUnit(
            path=path,
            module=module,
            source=source,
            tree=tree,
            imports=MappingProxyType(_imports(module, tree, is_package=path.name == "__init__.py")),
        )

    def nominal_for_field(self, name: str) -> SymbolRef | None:
        matches = self._nominals.get(name)
        return next(iter(matches)) if matches is not None and len(matches) == 1 else None

    @staticmethod
    def resolve(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
        if unit.module is None:
            return None
        if isinstance(expression, ast.Name):
            return unit.imports.get(expression.id) or SymbolRef(unit.module, expression.id)
        if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
            root = unit.imports.get(expression.value.id)
            if root is not None:
                return SymbolRef(root.module, expression.attr) if not root.name else None
        return None

    def class_for(self, unit: SourceUnit, expression: ast.expr) -> ClassSummary | None:
        symbol = self.resolve(unit, expression)
        return self._classes.get(symbol) if symbol is not None else None

    def annotation_contains_enum(self, unit: SourceUnit, annotation: ast.expr) -> bool:
        for member in walk_ast(annotation):
            if not isinstance(member, (ast.Name, ast.Attribute)):
                continue
            symbol = self.resolve(unit, member)
            summary = self._classes.get(symbol) if symbol is not None else None
            if summary is not None and summary.is_enum:
                return True
        return False

    def source_unit(self, module: str) -> SourceUnit | None:
        return self._by_module.get(module)

    def nominal_membership_is_dynamic(self, symbol: SymbolRef) -> bool:
        if symbol.module not in self._namespace_mutation:
            unit = self.source_unit(symbol.module)
            self._namespace_mutation[symbol.module] = (
                unit is None
                or unit.tree is None
                or dynamic_namespace_access(
                    walk_ast(unit.tree), ImportIndex.from_tree(unit.tree), NodeIndex(unit.tree).parents
                )
            )
        return self._namespace_mutation[symbol.module] or symbol in self._escaped_nominal_classes

    @cached_property
    def _escaped_nominal_classes(self) -> frozenset[SymbolRef]:
        escaped: set[SymbolRef] = set()
        namespaces = self._runtime_namespaces
        if self._value_origins_incomplete:
            return frozenset(self._classes)
        for unit in self._units.values():
            if len(escaped) == len(self._classes):
                break
            escaped.update(self._unit_escaped_classes(unit, namespaces, already_escaped=escaped))
            if self._value_origins_incomplete:
                return frozenset(self._classes)
        return frozenset(escaped)

    @cached_property
    def _runtime_origins(self) -> Mapping[str, Mapping[str, frozenset[SymbolRef]]]:
        origins: dict[str, dict[str, set[SymbolRef]]] = {}
        for unit in self._units.values():
            if unit.module is None or unit.tree is None:
                continue
            bindings = origins.setdefault(unit.module, {})
            for name, targets in _runtime_import_origins(unit).items():
                bindings.setdefault(name, set()).update(targets)
        return MappingProxyType(
            {
                module: MappingProxyType({name: frozenset(targets) for name, targets in bindings.items()})
                for module, bindings in origins.items()
            }
        )

    @cached_property
    def _runtime_namespaces(self) -> Mapping[str, frozenset[SymbolRef]]:
        values = {name: set(targets) for name, targets in _class_namespaces(self._classes).items()}
        for module in self._runtime_origins:
            for prefix in _module_prefixes(module):
                values.setdefault(prefix, set())
        links: dict[str, set[str]] = {}
        for module, bindings in self._runtime_origins.items():
            for origin in chain.from_iterable(bindings.values()):
                for target in self._canonical_value_symbols(origin):
                    _link_namespace_value(module, target, self._classes, values, links)
                if self._value_origins_incomplete:
                    return _namespace_closure(values, links)
        return _namespace_closure(values, links)

    def _canonical_value_symbols(self, symbol: SymbolRef) -> tuple[SymbolRef, ...]:
        if self._value_origins_incomplete:
            return ()
        if not self._has_value_origin(symbol):
            return (symbol,)
        cached = self._canonical_values.get(symbol)
        if cached is None:
            cached = tuple(self._value_symbol_origins(symbol))
            self._canonical_values[symbol] = cached
        return cached

    def _has_value_origin(self, symbol: SymbolRef) -> bool:
        bindings = self._runtime_origins.get(symbol.module, {})
        if bindings.get(symbol.name) or bindings.get("*"):
            return True
        if symbol.module not in self._bound_value_prefixes:
            parts = symbol.module.split(".")
            bound = False
            for size in range(len(parts) - 1, 0, -1):
                prefix = self._runtime_origins.get(".".join(parts[:size]), {})
                if prefix.get(parts[size]) or prefix.get("*"):
                    bound = True
                    break
            self._bound_value_prefixes[symbol.module] = bound
        return self._bound_value_prefixes[symbol.module]

    def _value_symbol_origins(self, symbol: SymbolRef) -> Iterator[SymbolRef]:
        pending: list[tuple[SymbolRef, Mapping[tuple[str, str], int]]] = [(symbol, {})]
        remaining = _MAX_VALUE_ORIGIN_STATES
        while pending:
            if remaining == 0:
                # An incomplete escape inventory cannot prove any owned class closed.
                self._value_origins_incomplete = True
                return
            remaining -= 1
            current, seen = pending.pop()
            yield current
            parts = _qualified_symbol(current).split(".")
            for size in range(len(parts) - 1, 0, -1):
                module, name = ".".join(parts[:size]), parts[size]
                suffix = parts[size + 1 :]
                previous = seen.get((module, name))
                if previous is not None and len(suffix) >= previous:
                    continue
                bindings = self._runtime_origins.get(module, {})
                origins = bindings.get(name, ())
                stars = bindings.get("*", ())
                if not origins and not stars:
                    continue
                next_trace = {**seen, (module, name): len(suffix)}
                pending.extend((_symbol_with_suffix(origin, suffix), next_trace) for origin in origins)
                pending.extend((_symbol_with_suffix(origin, [name, *suffix]), next_trace) for origin in stars)

    def _unit_escaped_classes(
        self,
        unit: SourceUnit,
        namespaces: Mapping[str, frozenset[SymbolRef]],
        *,
        already_escaped: AbstractSet[SymbolRef] = frozenset(),
    ) -> frozenset[SymbolRef]:
        if unit.tree is None:
            return frozenset()
        escaped = set(already_escaped)
        imports = self._runtime_origins[unit.module] if unit.module is not None else _runtime_import_origins(unit)
        roots = self._unit_value_roots(unit, imports, namespaces, already_escaped=escaped)
        if roots == frozenset():
            return frozenset(escaped)
        for use in _runtime_class_value_uses(
            unit.tree,
            roots=roots,
            opaque_type_providers=self._runtime_type_providers_opaque,
            type_providers=self._type_providers.get(unit.tree),
        ):
            targets = self._owned_value_targets(
                _possible_class_symbols(unit, use.reference, imports), namespaces, already_escaped=escaped
            )
            if not targets or use.type_or_constructor:
                continue
            for symbol in targets:
                if symbol in self._classes:
                    escaped.add(symbol)
                if use.namespace_value:
                    escaped.update(namespaces.get(_qualified_symbol(symbol), ()))
        return frozenset(escaped)

    @cached_property
    def _runtime_type_providers_opaque(self) -> bool:
        namespaces = self._runtime_type_provider_namespaces
        if self._value_origins_incomplete:
            return True
        for unit in self._units.values():
            if unit.tree is None:
                continue
            roots = self._unit_type_provider_roots(unit, namespaces)
            if self._value_origins_incomplete:
                return True
            if not roots:
                continue
            facts = _type_provider_facts(unit.tree, known_roots=roots)
            self._type_providers[unit.tree] = facts
            if facts.opaque:
                return True
        return False

    def _unit_type_provider_roots(self, unit: SourceUnit, namespaces: frozenset[str]) -> frozenset[str]:
        imports = self._runtime_origins[unit.module] if unit.module is not None else _runtime_import_origins(unit)
        return frozenset(
            name
            for name, targets in imports.items()
            for origin in targets
            for canonical in self._canonical_value_symbols(origin)
            if _type_provider_origin(canonical) or _qualified_symbol(canonical) in namespaces
        )

    @cached_property
    def _runtime_type_provider_namespaces(self) -> frozenset[str]:
        reverse: dict[str, set[str]] = {}
        providers = set(_TYPE_PROVIDER_NAMESPACES)
        for module, bindings in self._runtime_origins.items():
            prefixes = _module_prefixes(module)
            for targets in bindings.values():
                for origin in targets:
                    for canonical in self._canonical_value_symbols(origin):
                        qualified = _qualified_symbol(canonical)
                        reverse.setdefault(qualified, set()).update(prefixes)
                        if _type_provider_origin(canonical):
                            providers.add(qualified)
        return _reachable_namespaces(providers, reverse)

    @cached_property
    def _local_value_roots(self) -> Mapping[str, frozenset[str]]:
        roots: dict[str, set[str]] = {}
        for symbol in self._classes:
            roots.setdefault(symbol.module, set()).add(symbol.name.split(".", 1)[0])
        for namespace, targets in self._runtime_namespaces.items():
            if targets:
                parent, _, name = namespace.rpartition(".")
                roots.setdefault(parent, set()).add(name)
        return MappingProxyType({module: frozenset(names) for module, names in roots.items()})

    def _unit_value_roots(
        self,
        unit: SourceUnit,
        imports: Mapping[str, frozenset[SymbolRef]],
        namespaces: Mapping[str, frozenset[SymbolRef]],
        *,
        already_escaped: AbstractSet[SymbolRef],
    ) -> frozenset[str] | None:
        if unit.module is None or "*" in imports or self._value_origins_incomplete:
            return None
        roots = set(self._local_value_roots.get(unit.module, ()))
        roots.update(
            name
            for name, origins in imports.items()
            if self._owned_value_targets(iter(origins), namespaces, already_escaped=already_escaped)
        )
        return None if self._value_origins_incomplete else frozenset(roots)

    def _owned_value_targets(
        self,
        symbols: Iterator[SymbolRef],
        namespaces: Mapping[str, frozenset[SymbolRef]],
        *,
        already_escaped: AbstractSet[SymbolRef] = frozenset(),
    ) -> tuple[SymbolRef, ...]:
        return tuple(
            target
            for symbol in symbols
            for target in self._canonical_value_symbols(symbol)
            if (target in self._classes and target not in already_escaped)
            or not namespaces.get(_qualified_symbol(target), frozenset()).issubset(already_escaped)
        )

    def constructor_consumers(self, unit: SourceUnit, name: str) -> frozenset[tuple[Path, str]]:
        if unit.module is None:
            return frozenset()
        target = SymbolRef(unit.module, name)
        consumers: set[tuple[Path, str]] = set()
        for candidate in self._units.values():
            if candidate.tree is None:
                continue
            consumers.update(_unit_constructor_consumers(candidate, candidate.tree, target))
        return frozenset(consumers)

    def constructor_operations(self, unit: SourceUnit, name: str) -> frozenset[tuple[Path, str]]:
        if unit.module is None:
            return frozenset()
        return self._constructor_operations.get(SymbolRef(unit.module, name), frozenset())

    @cached_property
    def _constructor_operations(self) -> Mapping[SymbolRef, frozenset[tuple[Path, str]]]:
        module_counts: dict[str, int] = {}
        for unit in self._units.values():
            if unit.module is not None:
                module_counts[unit.module] = module_counts.get(unit.module, 0) + 1
        owned_modules = frozenset(module for module, count in module_counts.items() if count == 1)
        operations: dict[SymbolRef, set[tuple[Path, str]]] = {}
        for unit in self._units.values():
            if unit.tree is None or unit.module not in owned_modules or is_generated(unit.path, unit.source):
                continue
            for symbol, operation in _unit_constructor_operations(unit, unit.tree, owned_modules):
                if symbol.module in owned_modules and symbol in self._classes:
                    operations.setdefault(symbol, set()).add((unit.path, operation))
        return MappingProxyType({symbol: frozenset(calls) for symbol, calls in operations.items()})

    def direct_subclasses(self, unit: SourceUnit, name: str) -> frozenset[tuple[Path, str]]:
        if unit.module is None:
            return frozenset()
        target = SymbolRef(unit.module, name)
        return frozenset(
            (candidate.path, node.name)
            for candidate in self._units.values()
            if candidate.tree is not None
            for node in candidate.tree.body
            if isinstance(node, ast.ClassDef)
            and any(_direct_base_symbol(candidate, base) == target for base in node.bases)
        )

    def typed_class_consumers(self, unit: SourceUnit, name: str) -> frozenset[tuple[Path, str]]:
        if unit.module is None:
            return frozenset()
        target = SymbolRef(unit.module, name)
        return frozenset(
            (candidate.path, owner.name)
            for candidate in self._units.values()
            if candidate.tree is not None
            for owner in candidate.tree.body
            if isinstance(owner, ast.ClassDef) and _class_has_typed_dependency(candidate, owner, target)
        )

    def test_mock_specs(self, unit: SourceUnit, name: str) -> frozenset[Path]:
        if unit.module is None:
            return frozenset()
        target = SymbolRef(unit.module, name)
        return frozenset(
            candidate.path
            for candidate in self._units.values()
            if candidate.tree is not None
            and any(
                _is_mock_spec_for(candidate, call, target)
                for call in walk_ast(candidate.tree)
                if isinstance(call, ast.Call)
            )
        )

    def class_inherits_from(self, unit: SourceUnit, name: str, qualified_bases: frozenset[str]) -> bool:
        if unit.module is None:
            return False
        pending = [SymbolRef(unit.module, name)]
        seen: set[SymbolRef] = set()
        while pending:
            symbol = pending.pop()
            if symbol in seen:
                continue
            seen.add(symbol)
            summary = self._classes.get(symbol)
            if summary is None:
                continue
            for base in summary.bases:
                if f"{base.module}.{base.name}" in qualified_bases:
                    return True
                pending.append(base)
        return False


def _class_namespaces(classes: Mapping[SymbolRef, ClassSummary]) -> dict[str, frozenset[SymbolRef]]:
    namespaces: dict[str, set[SymbolRef]] = {}
    for symbol in classes:
        parts = symbol.module.split(".")
        for size in range(1, len(parts) + 1):
            namespaces.setdefault(".".join(parts[:size]), set()).add(symbol)
    return {name: frozenset(symbols) for name, symbols in namespaces.items()}


def _module_prefixes(module: str) -> tuple[str, ...]:
    parts = module.split(".")
    return tuple(".".join(parts[:size]) for size in range(1, len(parts) + 1))


def _symbol_with_suffix(symbol: SymbolRef, suffix: Sequence[str]) -> SymbolRef:
    parts = [*_qualified_symbol(symbol).split("."), *suffix]
    return SymbolRef(".".join(parts[:-1]), parts[-1])


def _link_namespace_value(
    module: str,
    target: SymbolRef,
    classes: Mapping[SymbolRef, ClassSummary],
    values: dict[str, set[SymbolRef]],
    links: dict[str, set[str]],
) -> None:
    qualified = _qualified_symbol(target)
    for prefix in _module_prefixes(module):
        if target in classes:
            values[prefix].add(target)
        if qualified in values:
            links.setdefault(prefix, set()).add(qualified)


def _namespace_closure(
    values: dict[str, set[SymbolRef]], links: Mapping[str, set[str]]
) -> Mapping[str, frozenset[SymbolRef]]:
    changed = True
    while changed:
        changed = False
        for namespace, targets in links.items():
            before = len(values[namespace])
            for target in targets:
                values[namespace].update(values[target])
            changed = changed or len(values[namespace]) != before
    return MappingProxyType({name: frozenset(targets) for name, targets in values.items()})


def _runtime_import_origins(
    unit: SourceUnit, *, node_index: NodeIndex | None = None
) -> dict[str, frozenset[SymbolRef]]:
    origins: dict[str, set[SymbolRef]] = {name: {symbol} for name, symbol in unit.imports.items()}
    if unit.tree is not None:
        package = (unit.module or "") if unit.path.name == "__init__.py" else (unit.module or "").rpartition(".")[0]
        statements = (
            nodes(unit.tree, ast.Import, ast.ImportFrom, index=node_index)
            if node_index is not None
            else _runtime_import_statements(unit.tree)
        )
        for node in statements:
            for name, symbol in _statement_import_origins(node, package).items():
                origins.setdefault(name, set()).add(symbol)
    return {name: frozenset(symbols) for name, symbols in origins.items()}


def _runtime_import_statements(tree: ast.Module) -> Iterator[ast.Import | ast.ImportFrom]:
    queue: list[ast.AST] = [tree]
    offset = 0
    while offset < len(queue):
        current = queue[offset]
        offset += 1
        if isinstance(current, ast.Import | ast.ImportFrom):
            yield current
        queue.extend(
            child for child in children(current) if isinstance(child, ast.stmt | ast.ExceptHandler | ast.match_case)
        )


def _statement_import_origins(node: ast.Import | ast.ImportFrom, package: str) -> dict[str, SymbolRef]:
    imported: dict[str, SymbolRef] = {}
    _record_import(node, package, imported)
    if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
        target = _relative_module(package, node.level, node.module)
        if target is not None:
            imported["*"] = SymbolRef(target, "")
    return imported


def _possible_class_symbols(
    unit: SourceUnit, reference: ast.Name | ast.Attribute, imports: Mapping[str, frozenset[SymbolRef]]
) -> Iterator[SymbolRef]:
    resolved = ProjectIndexSet.resolve(unit, reference)
    if resolved is not None:
        yield resolved
    attributes: list[str] = []
    root: ast.expr = reference
    while isinstance(root, ast.Attribute):
        attributes.append(root.attr)
        root = root.value
    if not isinstance(root, ast.Name):
        return
    for origin in imports.get(root.id, ()):
        if not attributes:
            yield origin
            continue
        parts = [origin.module, *([origin.name] if origin.name else []), *reversed(attributes)]
        yield SymbolRef(".".join(parts[:-1]), parts[-1])


def _qualified_symbol(symbol: SymbolRef) -> str:
    if not symbol.module:
        return symbol.name
    return f"{symbol.module}.{symbol.name}" if symbol.name else symbol.module


def _runtime_class_value_uses(
    tree: ast.Module,
    *,
    roots: frozenset[str] | None = None,
    opaque_type_providers: bool = False,
    type_providers: _TypeProviderFacts | None = None,
) -> Iterator[_ClassValueUse]:
    queue: deque[tuple[ast.AST, ast.AST | None, bool]] = deque([(tree, None, False)])
    while queue:
        current, parent, in_type = queue.popleft()
        if in_type and isinstance(current, ast.Subscript):
            if type_providers is None and not opaque_type_providers:
                type_providers = _type_provider_facts(tree)
            in_type = (
                not opaque_type_providers
                and type_providers is not None
                and not type_providers.opaque
                and _proven_type_provider(current.value, type_providers.imports)
            )
        if (
            isinstance(current, _CLASS_VALUE_NODES)
            and isinstance(current.ctx, ast.Load)
            and _reference_has_root(current, roots)
        ):
            yield _ClassValueUse(
                current,
                in_type or (isinstance(parent, ast.Call) and parent.func is current),
                not (isinstance(parent, ast.Attribute) and parent.value is current),
            )
        changes_type_context = isinstance(current, _TYPE_CONTEXT_PARENTS)
        queue.extend(
            (
                child,
                current,
                _child_type_context(parent=current, child=child, inherited=in_type)
                if changes_type_context
                else in_type,
            )
            for child in children(current)
        )


def _reachable_namespaces(providers: set[str], reverse: Mapping[str, set[str]]) -> frozenset[str]:
    queue = deque(providers)
    while queue:
        current = queue.popleft()
        for namespace in reverse.get(current, ()):
            if namespace not in providers:
                providers.add(namespace)
                queue.append(namespace)
    return frozenset(providers)


def _type_provider_facts(tree: ast.Module, *, known_roots: frozenset[str] = frozenset()) -> _TypeProviderFacts:
    imports = ImportIndex.from_tree(tree)
    opaque = any(
        isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
        for statement in _runtime_import_statements(tree)
    )
    return _TypeProviderFacts(imports, opaque or _type_provider_imports_escape(tree, imports, known_roots=known_roots))


def _type_provider_imports_escape(
    tree: ast.Module, imports: ImportIndex, *, known_roots: frozenset[str] = frozenset()
) -> bool:
    roots = _type_provider_roots(tree, imports) | known_roots
    if not roots:
        return False
    queue: deque[tuple[ast.AST, ast.AST | None]] = deque([(tree, None)])
    while queue:
        current, parent = queue.popleft()
        if (
            isinstance(current, _CLASS_VALUE_NODES)
            and _reference_has_root(current, roots)
            and (not isinstance(current.ctx, ast.Load) or not _safe_type_provider_reference(current, parent, imports))
        ):
            return True
        queue.extend((child, current) for child in children(current))
    return False


def _type_provider_roots(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    roots = {
        name
        for name, binding in imports.bindings.items()
        if binding.module in _TYPE_PROVIDER_NAMESPACES
        and (binding.symbol is None or binding.symbol in _GENERIC_TYPE_PROVIDERS | _BUILTIN_TYPE_PROVIDERS)
    }
    roots.update(
        name
        for statement in _runtime_import_statements(tree)
        for name, symbol in _statement_import_origins(statement, "").items()
        if _type_provider_origin(symbol)
    )
    return frozenset(roots)


def _type_provider_origin(symbol: SymbolRef) -> bool:
    return symbol.module in _TYPE_PROVIDER_NAMESPACES and (
        not symbol.name or symbol.name in _GENERIC_TYPE_PROVIDERS | _BUILTIN_TYPE_PROVIDERS
    )


def _safe_type_provider_reference(reference: ast.expr, parent: ast.AST | None, imports: ImportIndex) -> bool:
    if isinstance(reference, ast.Attribute) and reference.attr.startswith("__"):
        return False
    if imports.resolved_symbol(reference, sources=_GENERIC_TYPE_SOURCES) == "TYPE_CHECKING":
        return True
    match parent:
        case ast.Attribute(value=value) | ast.Subscript(value=value):
            return value is reference
        case ast.Call(func=function):
            return function is reference and (
                _proven_type_provider(reference, imports)
                or imports.resolved_symbol(reference, sources=_GENERIC_TYPE_SOURCES) in _TYPE_HELPER_CALLS
                or imports.resolved_symbol(reference, sources=frozenset({"builtins"})) in _BUILTIN_TYPE_PROVIDERS
            )
        case ast.ClassDef(bases=bases):
            return reference in bases
        case (
            ast.arg(annotation=annotation)
            | ast.AnnAssign(annotation=annotation)
            | ast.FunctionDef(returns=annotation)
            | ast.AsyncFunctionDef(returns=annotation)
        ):
            return annotation is reference
        case _:
            return False


def _proven_type_provider(provider: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(provider, ast.Name) and provider.id in _BUILTIN_TYPE_PROVIDERS:
        return imports.builtin_is_unshadowed(provider.id)
    return imports.resolved_symbol(provider, sources=_GENERIC_TYPE_SOURCES) in _GENERIC_TYPE_PROVIDERS


def _reference_has_root(reference: ast.Name | ast.Attribute, roots: frozenset[str] | None) -> bool:
    if roots is None:
        return True
    current: ast.expr = reference
    while isinstance(current, ast.Attribute):
        current = current.value
    return isinstance(current, ast.Name) and current.id in roots


def _child_type_context(*, parent: ast.AST, child: ast.AST, inherited: bool) -> bool:
    match parent:
        case ast.FunctionDef(returns=annotation) | ast.AsyncFunctionDef(returns=annotation):
            return annotation is child
        case ast.ClassDef(bases=bases):
            return child in bases
        case ast.Module() | ast.Lambda() | ast.Call():
            return False
        case ast.arg(annotation=annotation) | ast.AnnAssign(annotation=annotation):
            return inherited or annotation is child
        case _:
            return inherited


def _units(sources: Mapping[Path, str], roots: Sequence[Path] = ()) -> dict[Path, SourceUnit]:
    parsed: dict[Path, tuple[str | None, str, ast.Module | None]] = {}
    for path, source in sources.items():
        if not _is_index_candidate(symbol_prefilter_source(source)):
            continue
        tree: ast.Module | None = None
        with suppress(SyntaxError):
            tree = ast.parse(source, filename=str(path))
        parsed[path] = (_module_name(path, roots), source, tree)
    return {
        path: SourceUnit(
            path=path,
            module=module,
            source=source,
            tree=tree,
            imports=MappingProxyType(_imports(module, tree, is_package=path.name == "__init__.py")),
        )
        for path, (module, source, tree) in parsed.items()
    }


def _is_index_candidate(source: str) -> bool:
    return (
        "import" in source
        or "NewType" in source
        or "class" in source
        or "spec" in source
        or ("match" in source and "str" in source)
    )


def _module_name(path: Path, roots: Sequence[Path]) -> str | None:
    resolved = path.resolve()
    root = next((candidate for candidate in roots if resolved == candidate or candidate in resolved.parents), None)
    if root is not None:
        try:
            project_module = _project_module_name(resolved, root)
            if project_module is not None:
                return project_module
            package_dir = _outer_package_directory(resolved, root)
        except OSError:
            return None
        if package_dir is not None:
            relative = resolved.relative_to(package_dir)
            suffix = relative.parts[:-1] if relative.name == "__init__.py" else (*relative.parts[:-1], relative.stem)
            return ".".join((package_dir.name, *suffix))
    return _package_module_name(path)


def _project_module_name(resolved: Path, root: Path) -> str | None:
    # PEP 420 namespace directories do not have __init__.py. The closest
    # Python project boundary preserves their complete importable path.
    project = next(
        (ancestor for ancestor in resolved.parents if (ancestor / "pyproject.toml").is_file()),
        None,
    )
    if project is None or not (project == root or root in project.parents):
        return None
    relative = resolved.relative_to(project)
    parts = relative.parts[1:] if relative.parts[0] == "src" else relative.parts
    if not parts:
        return None
    suffix = parts[:-1] if parts[-1] == "__init__.py" else (*parts[:-1], Path(parts[-1]).stem)
    return ".".join(suffix) or None


def _package_module_name(path: Path) -> str | None:
    parts: list[str] = []
    parent = path.absolute().parent
    try:
        while parent != parent.parent and (parent / "__init__.py").is_file():
            parts.append(parent.name)
            parent = parent.parent
    except OSError:
        return None
    if not parts:
        if path.is_absolute():
            return None
        relative = [part for part in path.parts if part not in {".", ".."}]
        if not relative:
            return None
        if path.name == "__init__.py":
            return ".".join(relative[:-1]) or None
        return ".".join([*relative[:-1], path.stem])
    parts.reverse()
    if path.name != "__init__.py":
        parts.append(path.stem)
    return ".".join(parts)


def _project_roots(paths: Sequence[Path], *, facts: FirstPartyFacts | None = None) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    for path in paths:
        try:
            root = project_root(path.resolve(), facts=facts)
        except OSError:
            continue
        if root is not None:
            candidates.add(root)
    roots: list[Path] = []
    for candidate in sorted(candidates):
        if any(candidate == root or root in candidate.parents for root in roots):
            continue
        roots.append(candidate)
        if len(roots) >= _MAX_ROOTS:
            break
    return tuple(roots)


def _imports(module: str | None, tree: ast.Module | None, *, is_package: bool) -> dict[str, SymbolRef]:
    if module is None or tree is None:
        return {}
    result: dict[str, SymbolRef] = {}
    package = module if is_package else module.rpartition(".")[0]
    for node in _module_import_statements(tree):
        _record_import(node, package, result)
    return result


def _module_import_statements(tree: ast.Module) -> tuple[ast.stmt, ...]:
    statements: list[ast.stmt] = list(tree.body)
    for statement in tree.body:
        if not isinstance(statement, ast.If) or not _is_type_checking_guard(statement.test):
            continue
        statements.extend(child for child in statement.body if isinstance(child, (ast.Import, ast.ImportFrom)))
    return tuple(statements)


def _is_type_checking_guard(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"typing", "typing_extensions"}
        and node.attr == "TYPE_CHECKING"
    )


def _tail(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _resolve(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
    if unit.module is None:
        return None
    if isinstance(expression, ast.Name):
        return unit.imports.get(expression.id) or SymbolRef(unit.module, expression.id)
    if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
        root = unit.imports.get(expression.value.id)
        if root is not None and not root.name:
            return SymbolRef(root.module, expression.attr)
    return None


def _direct_base_symbol(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
    resolved = _resolve(unit, expression)
    if resolved is not None or not isinstance(expression, ast.Name) or unit.tree is None:
        return resolved
    # Test support modules need not be packages. Absolute imports still prove
    # the base identity even when the file itself has no importable module name.
    for statement in _module_import_statements(unit.tree):
        if not isinstance(statement, ast.ImportFrom) or statement.level or statement.module is None:
            continue
        for alias in statement.names:
            if (alias.asname or alias.name) == expression.id:
                return SymbolRef(statement.module, alias.name)
    return None


def _collect_unit_symbols(
    units: Mapping[Path, SourceUnit], classes: dict[SymbolRef, ClassSummary], nominals: dict[str, set[SymbolRef]]
) -> None:
    for unit in units.values():
        if unit.module is None or unit.tree is None:
            continue
        for statement in unit.tree.body:
            if isinstance(statement, ast.ClassDef):
                symbol = SymbolRef(unit.module, statement.name)
                classes[symbol] = _class_summary(unit, statement, symbol)
            nominal = _new_type(statement, unit.module)
            if nominal is not None:
                nominals.setdefault(_field_key(nominal.name), set()).add(nominal)


def _field_key(type_name: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", type_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _new_type(statement: ast.stmt, module: str) -> SymbolRef | None:
    target: ast.Name | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        target, value = statement.target, statement.value
    if (
        target is None
        or not isinstance(value, ast.Call)
        or _tail(value.func) != "NewType"
        or len(value.args) < _NEW_TYPE_MIN_ARGS
    ):
        return None
    declared = value.args[0]
    carrier = value.args[1]
    if not (
        isinstance(declared, ast.Constant) and declared.value == target.id and _tail(carrier) in {"UUID", "int", "str"}
    ):
        return None
    return SymbolRef(module, target.id)


def _class_summary(unit: SourceUnit, statement: ast.ClassDef, symbol: SymbolRef) -> ClassSummary:
    fields = {
        item.target.id: item.annotation
        for item in statement.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    }
    return ClassSummary(
        symbol=symbol,
        fields=MappingProxyType(fields),
        bases=tuple(
            resolved
            for base in statement.bases
            if (resolved := _resolve(unit, base.value if isinstance(base, ast.Subscript) else base)) is not None
        ),
        is_enum=any(_tail(base) in {"Enum", "IntEnum", "StrEnum"} for base in statement.bases),
    )


def _load_root_sources(root: Path, sources: dict[Path, str]) -> None:
    count = 0
    source_chars = 0
    for path in _python_files(root):
        if count >= _MAX_FILES_PER_ROOT or source_chars >= _MAX_SOURCE_CHARS_PER_ROOT:
            break
        try:
            if path.resolve() in sources:
                count += 1
                continue
        except OSError:
            continue
        loaded_source = _read_bounded_source(root, path)
        if loaded_source is None:
            continue
        if source_chars + len(loaded_source.source) > _MAX_SOURCE_CHARS_PER_ROOT:
            break
        sources.setdefault(loaded_source.path, loaded_source.source)
        source_chars += len(loaded_source.source)
        count += 1


def _read_bounded_source(root: Path, path: Path) -> LoadedSource | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        return LoadedSource(resolved, read_python_source(resolved))
    except OSError, ValueError, SyntaxError:
        return None


def _python_files(root: Path) -> Iterator[Path]:
    for scanned, (directory, dir_names, file_names) in enumerate(os.walk(root), start=1):
        if scanned > _MAX_DIRS_PER_ROOT:
            return
        parent = Path(directory)
        dir_names[:] = [
            name
            for name in sorted(dir_names)
            if not name.startswith(".") and name not in _SKIP_DIRS and not (parent / name / ".git").exists()
        ]
        for name in sorted(file_names):
            if name.endswith(".py"):
                yield parent / name


def _unit_constructor_consumers(
    candidate: SourceUnit, tree: ast.Module, target: SymbolRef
) -> Iterator[tuple[Path, str]]:
    for owner in tree.body:
        if not isinstance(owner, ast.ClassDef):
            continue
        initializer = next(
            (
                statement
                for statement in owner.body
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == "__init__"
            ),
            None,
        )
        if initializer is None:
            continue
        parameters = (*initializer.args.posonlyargs, *initializer.args.args, *initializer.args.kwonlyargs)
        if any(
            _annotation_contains_symbol(candidate, parameter.annotation, target)
            for parameter in parameters
            if parameter.arg != "self"
        ):
            yield (candidate.path, owner.name)


def _unit_constructor_operations(
    unit: SourceUnit, tree: ast.Module, owned_modules: frozenset[str]
) -> Iterator[tuple[SymbolRef, str]]:
    if any(
        isinstance(item, ast.ImportFrom) and any(alias.name == "*" for alias in item.names) for item in walk_ast(tree)
    ):
        return
    rebound = _module_constructor_rebindings(tree)
    for owner in tree.body:
        self_symbol = SymbolRef(unit.module or "", owner.name) if isinstance(owner, ast.ClassDef) else None
        for method in _direct_functions(owner):
            for symbol, operation in _function_constructor_operations(unit, method, rebound, owned_modules):
                if symbol != self_symbol:
                    yield symbol, operation


def _module_constructor_rebindings(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    declarations: dict[str, int] = {}
    for statement in tree.body:
        for name in _module_constructor_declarations(statement):
            declarations[name] = declarations.get(name, 0) + 1
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(statement.name)
        elif not isinstance(statement, ast.ClassDef | ast.Import | ast.ImportFrom):
            names.update(_bound_constructor_names(statement))
    names.update(name for name, count in declarations.items() if count > 1)
    return frozenset(names)


def _module_constructor_declarations(statement: ast.stmt) -> frozenset[str]:
    if isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return frozenset({statement.name})
    return _bound_constructor_names(statement)


def _direct_functions(owner: ast.stmt) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    if isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        return (owner,)
    if isinstance(owner, ast.ClassDef):
        return tuple(item for item in owner.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef))
    return ()


def _function_constructor_operations(
    unit: SourceUnit,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    rebound: frozenset[str],
    owned_modules: frozenset[str],
) -> Iterator[tuple[SymbolRef, str]]:
    shadowed = _bound_constructor_names(method) | rebound
    for statement in method.body:
        if isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign | ast.Return):
            operation = _direct_constructor_operation(unit, statement.value, shadowed, owned_modules)
            if operation is not None:
                yield operation
        if isinstance(
            statement,
            ast.Return
            | ast.Raise
            | ast.If
            | ast.For
            | ast.AsyncFor
            | ast.While
            | ast.Try
            | ast.TryStar
            | ast.With
            | ast.AsyncWith
            | ast.Match,
        ):
            break


def _direct_constructor_operation(
    unit: SourceUnit, value: ast.expr | None, shadowed: frozenset[str], owned_modules: frozenset[str]
) -> tuple[SymbolRef, str] | None:
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
        return None
    if not isinstance(value.func.value, ast.Call):
        return None
    constructor = value.func.value.func
    root = constructor
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in shadowed:
        return None
    symbol = _owned_constructor_symbol(unit, constructor, owned_modules)
    return (symbol, value.func.attr) if symbol is not None else None


def _owned_constructor_symbol(
    unit: SourceUnit, expression: ast.expr, owned_modules: frozenset[str]
) -> SymbolRef | None:
    if isinstance(expression, ast.Name):
        return _resolve(unit, expression)
    parts: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or not parts:
        return None
    imported = unit.imports.get(current.id)
    if imported is None or imported.name:
        return None
    ordered = list(reversed(parts))
    module = ".".join((imported.module, *ordered[:-1]))
    if len(ordered) > 1 and not _explicit_constructor_module(unit, module):
        return None
    return SymbolRef(module, ordered[-1]) if module in owned_modules else None


def _explicit_constructor_module(unit: SourceUnit, module: str) -> bool:
    if unit.tree is None:
        return False
    return any(
        alias.name == module and alias.asname is None
        for statement in _module_import_statements(unit.tree)
        if isinstance(statement, ast.Import)
        for alias in statement.names
    )


def _bound_constructor_names(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for item in walk_ast(node):
        match item:
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.arg(arg=name)
                | ast.ClassDef(name=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
            ):
                names.add(name)
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name.split(".", 1)[0] for alias in aliases)
            case ast.Attribute(ctx=(ast.Store() | ast.Del())):
                root = item.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    names.add(root.id)
            case _:
                pass
    return frozenset(names)


def _class_has_typed_dependency(unit: SourceUnit, owner: ast.ClassDef, target: SymbolRef) -> bool:
    for statement in owner.body:
        if isinstance(statement, ast.AnnAssign) and _annotation_contains_symbol(unit, statement.annotation, target):
            return True
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parameters = (*statement.args.posonlyargs, *statement.args.args, *statement.args.kwonlyargs)
        if any(
            parameter.arg not in {"self", "cls"} and _annotation_contains_symbol(unit, parameter.annotation, target)
            for parameter in parameters
        ):
            return True
    return False


def _is_mock_spec_for(unit: SourceUnit, call: ast.Call, target: SymbolRef) -> bool:
    mock_name = _mock_function_name(unit, call.func)
    if mock_name is None:
        return False
    return any(
        keyword.arg in {"spec", "spec_set"} and _direct_base_symbol(unit, keyword.value) == target
        for keyword in call.keywords
    ) or (mock_name == "create_autospec" and bool(call.args) and _direct_base_symbol(unit, call.args[0]) == target)


def _mock_function_name(unit: SourceUnit, function: ast.expr) -> str | None:
    if isinstance(function, ast.Name):
        return _imported_mock_name(unit, function.id)
    if not isinstance(function, ast.Attribute) or not isinstance(function.value, ast.Name):
        return None
    return _module_mock_name(unit, function.value.id, function.attr)


def _imported_mock_name(unit: SourceUnit, name: str) -> str | None:
    imported = _direct_import_symbol(unit, name)
    if imported is None or imported.module != "unittest.mock":
        return None
    return imported.name if imported.name in {"Mock", "MagicMock", "AsyncMock", "create_autospec"} else None


def _module_mock_name(unit: SourceUnit, module_name: str, method_name: str) -> str | None:
    imported = _direct_import_symbol(unit, module_name)
    if imported not in {SymbolRef("unittest", "mock"), SymbolRef("unittest.mock", "")}:
        return None
    return method_name if method_name in {"Mock", "MagicMock", "AsyncMock", "create_autospec"} else None


def _direct_import_symbol(unit: SourceUnit, name: str) -> SymbolRef | None:
    imported = unit.imports.get(name)
    if imported is not None or unit.tree is None:
        return imported
    for statement in _module_import_statements(unit.tree):
        if (matched := _absolute_import_symbol(statement, name)) is not None:
            return matched
    return None


def _absolute_import_symbol(statement: ast.stmt, name: str) -> SymbolRef | None:
    if isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module is not None:
        for alias in statement.names:
            if (alias.asname or alias.name) == name:
                return SymbolRef(statement.module, alias.name)
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            if (alias.asname or alias.name.partition(".")[0]) == name:
                return SymbolRef(alias.name if alias.asname else alias.name.partition(".")[0], "")
    return None


def _annotation_contains_symbol(unit: SourceUnit, annotation: ast.expr | None, target: SymbolRef) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        with suppress(SyntaxError):
            annotation = ast.parse(annotation.value, mode="eval").body
    return any(
        _resolve(unit, candidate) == target
        for candidate in walk_ast(annotation)
        if isinstance(candidate, (ast.Name, ast.Attribute))
    )


def _record_import(node: ast.stmt, package: str, result: dict[str, SymbolRef]) -> None:
    if isinstance(node, ast.ImportFrom) and not any(alias.name == "*" for alias in node.names):
        target = _relative_module(package, node.level, node.module)
        if target is None:
            return
        for alias in node.names:
            result[alias.asname or alias.name] = SymbolRef(target, alias.name)
    elif isinstance(node, ast.Import):
        for alias in node.names:
            local_name = alias.asname or alias.name.partition(".")[0]
            module = alias.name if alias.asname else local_name
            result[local_name] = SymbolRef(module, "")


def _relative_module(package: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module
    parts = package.split(".") if package else []
    if level > len(parts) + 1:
        return None
    base = parts[: len(parts) - level + 1]
    if module:
        base.extend(module.split("."))
    return ".".join(base) if base else None


def _outer_package_directory(resolved: Path, root: Path) -> Path | None:
    package_dir: Path | None = None
    for ancestor in resolved.parents:
        if ancestor == root:
            break
        if (ancestor / "__init__.py").is_file():
            package_dir = ancestor
    return package_dir
