from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from operator import or_ as _operator_union  # pyright: ignore[reportUnknownVariableType] -- typeshed leaves arbitrary reflected operator dispatch untyped; preserve Python's real union dispatch.
import sys
from types import (
    BuiltinFunctionType,
    CodeType,
    FunctionType,
    MappingProxyType,
    MethodDescriptorType,
    MethodType,
    MethodWrapperType,
    WrapperDescriptorType,
)
from typing import TYPE_CHECKING, NamedTuple, TypeIs, final

from sarj_python_lint.rule_base import Rule, RuleDocumentation
from sarj_python_lint.rule_metadata import RuleDescriptor, is_alias_tuple, load_descriptors


if TYPE_CHECKING:
    from collections.abc import Callable, ItemsView, Iterator, KeysView, ValuesView


_union: Callable[[object, object], object] = _operator_union  # pyright: ignore[reportUnknownVariableType] -- operator.or_ accepts arbitrary operands and returns the reflected operation's arbitrary result.
type _ConstructorHook = (
    FunctionType | BuiltinFunctionType | MethodDescriptorType | MethodType | MethodWrapperType | WrapperDescriptorType
)


class _ConstructorHooks(NamedTuple):
    initializer: _ConstructorHook
    code: CodeType | None
    allocator: _ConstructorHook
    metaclass_call: _ConstructorHook


class _Observation(NamedTuple):
    code: str
    description: str
    documentation: RuleDocumentation
    aliases: tuple[str, ...]
    constructor_hooks: _ConstructorHooks


def _observe(rule: type[Rule]) -> _Observation | None:
    documentation = rule.documentation
    if not isinstance(documentation, RuleDocumentation) or not is_alias_tuple(documentation.aliases):
        return None
    code = rule.code
    description = rule.description
    if not _is_text(code) or not _is_text(description):
        return None
    hooks = _constructor_hooks(rule)
    if hooks is None:
        return None
    return _Observation(
        code,
        description,
        documentation,
        tuple(documentation.aliases),
        hooks,
    )


def _constructor_hooks(rule: type[Rule]) -> _ConstructorHooks | None:
    initializer = rule.__init__
    allocator = rule.__new__
    metaclass_call = type(rule).__call__
    if (
        not _is_constructor_hook(initializer)
        or not _is_constructor_hook(allocator)
        or not _is_constructor_hook(metaclass_call)
    ):
        return None
    code: object = getattr(initializer, "__code__", None)
    if code is not None and not isinstance(code, CodeType):
        return None
    return _ConstructorHooks(initializer, code, allocator, metaclass_call)


def _is_constructor_hook(value: object) -> TypeIs[_ConstructorHook]:
    return isinstance(
        value,
        FunctionType
        | BuiltinFunctionType
        | MethodDescriptorType
        | MethodType
        | MethodWrapperType
        | WrapperDescriptorType,
    )


def _is_text(value: object) -> TypeIs[str]:
    return isinstance(value, str)


@final
@dataclass(frozen=True, slots=True)
class _Catalog:
    descriptors: tuple[RuleDescriptor, ...]
    by_id: MappingProxyType[str, RuleDescriptor]
    default_ids: MappingProxyType[str, None]


@final
class _RegistryState:
    def __init__(self) -> None:
        self.catalog: _Catalog | None = None
        self.classes: dict[str, type[Rule]] = {}
        self.observations: dict[str, _Observation | None] = {}
        self.complete: dict[bool, dict[str, type[Rule]]] = {}
        self.external_modules: set[str] = set()
        self.bootstrap = False

    def entries(self) -> _Catalog:
        catalog = self.catalog
        if catalog is None:
            descriptors = load_descriptors()
            by_id: dict[str, RuleDescriptor] = {entry.rule_id: entry for entry in descriptors}
            default_ids: dict[str, None] = {entry.rule_id: None for entry in descriptors if entry.enabled_by_default}
            catalog = _Catalog(
                descriptors,
                MappingProxyType(by_id),
                MappingProxyType(default_ids),
            )
            self.catalog = catalog
        return catalog

    def keys(self, *, defaults: bool) -> tuple[str, ...]:
        if self.bootstrap:
            return tuple(self.complete[defaults])
        catalog = self.entries()
        return tuple(entry.rule_id for entry in catalog.descriptors if not defaults or entry.enabled_by_default)

    def resolve(self, entry: RuleDescriptor) -> type[Rule]:
        cached = self.classes.get(entry.rule_id)
        if cached is not None:
            return cached
        if entry.module in sys.modules:
            self.external_modules.add(entry.module)
        module = import_module(entry.module)
        value: object = getattr(module, entry.class_name, None)
        if not isinstance(value, type) or not issubclass(value, Rule):
            msg = f"{entry.rule_id}: descriptor does not resolve to a Rule class"
            raise TypeError(msg)
        self.classes[entry.rule_id] = value
        self.observations[entry.rule_id] = _observe(value)
        return value

    def item(self, key: str, *, defaults: bool) -> type[Rule]:
        if defaults in self.complete:
            return self.complete[defaults][key]
        catalog = self.entries()
        entry = catalog.by_id[key]
        if defaults and not entry.enabled_by_default:
            raise KeyError(key)
        return self.resolve(entry)

    def materialize(self, *, defaults: bool) -> dict[str, type[Rule]]:
        cached = self.complete.get(defaults)
        if cached is not None:
            return cached
        from sarj_python_lint.rules._registry import (  # ruff: ignore[import-outside-top-level] -- explicit full operations use the independent eager class owner.
            _AUTHORING_DEFAULT_REGISTRY,  # pyright: ignore[reportPrivateUsage] -- full operations deliberately load the private eager source owner.
            _AUTHORING_REGISTRY,  # pyright: ignore[reportPrivateUsage] -- bootstrap must remain independent of missing generated descriptors.
        )

        try:
            catalog = self.entries()
        except ModuleNotFoundError as exc:
            if exc.name != "sarj_python_lint._rule_descriptors":
                raise
            # Source maintenance can bootstrap the writer before the generated file exists.
            self.complete[False] = dict(_AUTHORING_REGISTRY)
            self.complete[True] = dict(_AUTHORING_DEFAULT_REGISTRY)
            self.bootstrap = True
            return self.complete[defaults]
        complete: dict[str, type[Rule]] = {
            entry.rule_id: self.resolve(entry)
            for entry in catalog.descriptors
            if not defaults or entry.enabled_by_default
        }
        self.complete[defaults] = complete
        return complete

    def aliases(self) -> dict[str, str] | None:
        if self.bootstrap or self.external_modules:
            return None
        entries = self.entries().descriptors
        for entry in entries:
            module = sys.modules.get(entry.module)
            rule = self.classes.get(entry.rule_id)
            if module is None and rule is None:
                continue
            observed = self.observations.get(entry.rule_id)
            if (
                module is None
                or rule is None
                or observed is None
                or getattr(module, entry.class_name, None) is not rule
            ):
                return None
            if (
                observed.code != entry.code
                or observed.description != entry.description
                or observed.aliases != entry.aliases
            ):
                return None
            current = _observe(rule)
            if current is None or current.documentation is not observed.documentation or current != observed:
                return None
        return {alias: entry.rule_id for entry in entries for alias in entry.aliases}


@final
class _RuleMapping(Mapping[str, type[Rule]]):
    __hash__ = None

    def __init__(self, state: _RegistryState, *, defaults: bool) -> None:
        self.state = state
        self.defaults = defaults

    def __getitem__(self, key: str) -> type[Rule]:
        return self.state.item(key, defaults=self.defaults)

    def __iter__(self) -> Iterator[str]:
        return iter(self.state.keys(defaults=self.defaults))

    def __len__(self) -> int:
        return len(self.state.keys(defaults=self.defaults))

    def __contains__(
        self,
        key: object,  # sarj-noqa: SARJ528 -- Mapping membership accepts arbitrary keys, including unhashable keys whose native TypeError must be preserved.
    ) -> bool:
        if self.state.bootstrap:
            return key in self.state.complete[self.defaults]
        catalog = self.state.entries()
        return key in (catalog.default_ids if self.defaults else catalog.by_id)

    def __reversed__(self) -> Iterator[str]:
        return reversed(self.state.keys(defaults=self.defaults))

    def copy(self) -> dict[str, type[Rule]]:
        return self.state.materialize(defaults=self.defaults).copy()

    def keys(self) -> KeysView[str]:
        return self.state.materialize(defaults=self.defaults).keys()

    def values(self) -> ValuesView[type[Rule]]:
        return self.state.materialize(defaults=self.defaults).values()

    def items(self) -> ItemsView[str, type[Rule]]:
        return self.state.materialize(defaults=self.defaults).items()

    def __repr__(self) -> str:
        return repr(self.state.materialize(defaults=self.defaults))

    def __eq__(self, other: object) -> bool:
        return self.state.materialize(defaults=self.defaults) == other

    def __ne__(self, other: object) -> bool:
        return self.state.materialize(defaults=self.defaults) != other

    def __or__(
        self,
        other: object,  # sarj-noqa: SARJ528 -- Python union dispatch accepts arbitrary operands so their real reflected operator remains available.
    ) -> object:  # sarj-noqa: SARJ528 -- Python union dispatch permits arbitrary reflected operands and results; native errors and reflected return values are part of proxy compatibility.
        return _union(self.state.materialize(defaults=self.defaults), other)

    def __ror__(
        self,
        other: object,  # sarj-noqa: SARJ528 -- Reflected union accepts arbitrary operands and preserves Python's native dispatch and errors.
    ) -> object:  # sarj-noqa: SARJ528 -- reflected union must retain Python's arbitrary operand/result protocol rather than narrow it to mappings.
        return _union(other, self.state.materialize(defaults=self.defaults))


_STATE = _RegistryState()
REGISTRY: MappingProxyType[str, type[Rule]] = MappingProxyType(_RuleMapping(_STATE, defaults=False))
DEFAULT_REGISTRY: MappingProxyType[str, type[Rule]] = MappingProxyType(_RuleMapping(_STATE, defaults=True))


def canonical_aliases(registry: Mapping[str, type[Rule]]) -> dict[str, str] | None:
    return _STATE.aliases() if registry is REGISTRY else None
