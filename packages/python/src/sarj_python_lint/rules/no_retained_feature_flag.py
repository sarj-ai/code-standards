from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, final, override

from sarj_python_lint.feature_flag_options import MANIFEST_NAME
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.feature_flag_options import FeatureFlagOptions


type _Definition = ast.FunctionDef | ast.AsyncFunctionDef
type _Function = _Definition | ast.Lambda
type _Store = ast.Assign | ast.AnnAssign | ast.AugAssign

_MEMOIZERS: Final = frozenset(
    {
        "aiocache.cached",
        "async_lru.alru_cache",
        "cachetools.cached",
        "cachetools.cachedmethod",
        "cachetools.func.lru_cache",
        "cachetools.func.ttl_cache",
        "functools.cache",
        "functools.cached_property",
        "functools.lru_cache",
    }
)
_MANIFEST: Final = (
    "[python.no-retained-feature-flag]\n"
    'modules = ["app.flags"]\n'
    'snapshot_types = ["FlagSnapshot"]\n'
    'resolver_functions = ["pinned_flags"]\n'
    'resolver_methods = ["evaluate"]\n'
    'selector_methods = ["for_"]\n'
    'startup_functions = ["create_app"]\n'
    'unit_of_work_types = ["RequestFlags"]\n'
)
_IMPORTS: Final = "from app.flags import NEW_CHECKOUT, FlagSnapshot, Switch, pinned_flags\n"


class _Kind(StrEnum):
    SNAPSHOT = "snapshot"
    DERIVED = "derived"


class _Retention(StrEnum):
    IMPORT_TIME = "import-time"
    STARTUP = "startup"
    MEMOISED = "memoised"
    GLOBAL = "global"
    CLASS_STATE = "class-state"
    INSTANCE_STATE = "instance-state"
    PROCESS_STATE = "process-state"
    MODULE_OBJECT = "module-object"


_MESSAGES: Final[Mapping[_Retention, str]] = MappingProxyType(
    {
        _Retention.IMPORT_TIME: "Feature flags are resolved while the module is imported, so the value is fixed "
        "for the life of the process",
        _Retention.STARTUP: "Feature flags are resolved in a function that runs once at process start, so a later "
        "change is never seen",
        _Retention.MEMOISED: "A memoised function resolves feature flags, so its first answer is reused after the "
        "flag changes",
        _Retention.GLOBAL: "A flag value is kept in a module global, which outlives the unit of work",
        _Retention.CLASS_STATE: "A flag value is kept in a class attribute, which outlives the unit of work",
        _Retention.INSTANCE_STATE: "A flag value is kept on `self`, which may outlive the unit of work",
        _Retention.PROCESS_STATE: "A flag value is kept in process-lifetime application state",
        _Retention.MODULE_OBJECT: "A flag value is kept on a module-level object, which outlives the unit of work",
    }
)
_ADVICE: Final = "; resolve one snapshot per unit of work and pass it, or what it selects, as an argument."


def _example(*, example_id: str, title: str, body: str, matches: bool, public: bool = True) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(
            ExampleFile(path=PurePosixPath(MANIFEST_NAME), source=_MANIFEST),
            ExampleFile.python("app/checkout.py", _IMPORTS + body),
        ),
        focus_path=PurePosixPath("app/checkout.py"),
        expected_count=1 if matches else 0,
        public=public,
    )


@final
class NoRetainedFeatureFlag(Rule):
    id = "no-retained-feature-flag"
    code = "SARJ594"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Resolve feature flags once per unit of work instead of retaining them in process-lifetime state",
        rationale=(
            "A flag provider refreshes its definitions while the process runs, so a changed flag is expected to "
            "reach the next request, call or job. A value read at import or process start, memoised, or copied to "
            "a module global, class attribute, long-lived instance or application state is frozen until the next "
            "deploy: the rollout or kill switch appears to work in the provider and does nothing in production."
        ),
        remediation=(
            "Resolve one snapshot where the unit of work starts (request, call, job) and pass the snapshot, or the "
            "behaviour it selects, down as an argument. Keep only the flag source and the unresolved selector in "
            "long-lived objects. A deliberate one-time read keeps `# sarj-noqa: SARJ594 -- <reason>`."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "The rule is inactive until the repository manifest has `[python.no-retained-feature-flag]` with "
                "`modules` and `snapshot_types`; `resolver_functions`, `resolver_methods`, `selector_methods`, "
                "`startup_functions`, `unit_of_work_types`, `memoizers` and `process_state` are optional."
            ),
            (
                "Only files that name a configured module are checked. Snapshots are recognised from configured "
                "resolver calls, same-file functions annotated to return a snapshot type, and parameters or locals "
                "annotated with one. Resolver methods match by name because the receiver type is not inferred."
            ),
            (
                "Stores are assignments to a `global` name, `self`/`cls` or class attributes, module-level objects "
                "and configured application state. Mutating calls such as `append` or `setattr`, values wrapped in "
                "another object, tuple unpacking, relative imports and imports inside functions are not modeled."
            ),
            "Instances of `unit_of_work_types` may hold a snapshot. Tests and generated code are excluded.",
        ),
        examples=(
            _example(
                example_id="resolved-at-import",
                title="A module constant fixes the flag when the process starts",
                body="CHECKOUT = Switch(NEW_CHECKOUT, on=new, off=old).for_(pinned_flags())\n",
                matches=True,
            ),
            _example(
                example_id="kept-on-a-service",
                title="A long-lived service copies the flag value in its constructor",
                body=(
                    "class CheckoutService:\n"
                    "    def __init__(self, flags: FlagSnapshot) -> None:\n"
                    "        self.use_new = flags.get(NEW_CHECKOUT)\n"
                ),
                matches=True,
                public=False,
            ),
            _example(
                example_id="memoised-read",
                title="A memoised function reuses its first answer",
                body=(
                    "from functools import cache\n"
                    "@cache\n"
                    "def new_checkout() -> bool:\n"
                    "    return pinned_flags().get(NEW_CHECKOUT)\n"
                ),
                matches=True,
                public=False,
            ),
            _example(
                example_id="resolved-per-request",
                title="The handler resolves a snapshot and the service receives what it selects",
                body=(
                    "CHECKOUT = Switch(NEW_CHECKOUT, on=new, off=old)\n"
                    "class CheckoutService:\n"
                    "    def __init__(self, source: FlagSource) -> None:\n"
                    "        self.source = source\n"
                    "    async def pay(self, order: Order) -> Receipt:\n"
                    "        flags = await self.source.evaluate(order.subject)\n"
                    "        return await charge(order, CHECKOUT.for_(flags))\n"
                ),
                matches=False,
            ),
            _example(
                example_id="unit-of-work-holder",
                title="A configured unit-of-work type may hold the snapshot",
                body=(
                    "class RequestFlags:\n"
                    "    def __init__(self, flags: FlagSnapshot) -> None:\n"
                    "        self.snapshot = flags\n"
                ),
                matches=False,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated or context.tree is None:
            return []
        options = context.session.feature_flags.options(context.path)
        if options is None or not any(module in context.source for module in options.modules):
            return []
        found: dict[int, Diagnostic] = {}
        for finding in _Analysis(context, context.tree, options).findings():
            found.setdefault(
                finding.node.lineno,
                Diagnostic(
                    path=context.path,
                    line=finding.node.lineno,
                    col=finding.node.col_offset + 1,
                    code=self.code,
                    message=_MESSAGES[finding.retention] + _ADVICE,
                    severity=Severity.WARNING,
                ),
            )
        return [found[line] for line in sorted(found)]


@dataclass(frozen=True, slots=True)
class _Finding:
    node: ast.expr
    retention: _Retention


@final
class _Analysis:
    def __init__(self, context: PythonFileContext, tree: ast.Module, options: FeatureFlagOptions) -> None:
        self._context = context
        self._options = options
        self._imports = context.module_imports
        self._module_names = self._imports.shadowed_names | frozenset(self._imports.bindings)
        self._classes = frozenset(node.name for node in tree.body if isinstance(node, ast.ClassDef))
        self._owners: dict[ast.AST, _Function | None] = {}
        self._environments: dict[_Function, dict[str, _Kind]] = {}
        self._definitions = context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
        self._resolvers = frozenset(
            definition.name for definition in self._definitions if self._is_snapshot_type(definition.returns)
        )
        self._stores = self._by_owner(context.nodes(ast.Assign, ast.AnnAssign, ast.AugAssign))
        self._walruses = self._by_owner(context.nodes(ast.NamedExpr))
        stored = self._by_owner([name for name in context.nodes(ast.Name) if isinstance(name.ctx, ast.Store)])
        self._bound = {owner: {name.id for name in names} for owner, names in stored.items()}
        declared = self._by_owner(context.nodes(ast.Global))
        self._globals = {
            owner: {name for declaration in declarations for name in declaration.names}
            for owner, declarations in declared.items()
        }
        self._memoised = frozenset({*self._decorated_memoised(), *self._wrapped_memoised()})

    def findings(self) -> list[_Finding]:
        return [*self._resolutions(), *self._kept_values()]

    def _resolutions(self) -> Iterator[_Finding]:
        for call in self._context.nodes(ast.Call):
            if self._is_resolver(call) and (retention := self._resolution_retention(call)) is not None:
                yield _Finding(call, retention)

    def _resolution_retention(self, call: ast.Call) -> _Retention | None:
        if (function := self._owner(call)) is None:
            return _Retention.IMPORT_TIME
        if any(enclosing in self._memoised for enclosing in self._enclosing(function)):
            return _Retention.MEMOISED
        names = self._qualified_names(function)
        return None if names.isdisjoint(self._options.startup_functions) else _Retention.STARTUP

    def _qualified_names(self, function: _Function) -> frozenset[str]:
        match function, self._context.parents.get(function):
            case ((ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name)), ast.ClassDef(name=owner)):
                return frozenset({name, f"{owner}.{name}"})
            case ((ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name)), _):
                return frozenset({name})
            case _:
                return frozenset()

    def _kept_values(self) -> Iterator[_Finding]:
        for function, stores in self._stores.items():
            if function is None:
                continue
            environment = self._environment(function)
            for store in stores:
                if store.value is not None and self._kind(store.value, environment) is not None:
                    yield from self._kept_targets(store, function)

    def _kept_targets(self, store: _Store, function: _Function) -> Iterator[_Finding]:
        match store:
            case ast.Assign(targets=targets):
                pass
            case ast.AnnAssign(target=target) | ast.AugAssign(target=target):
                targets = [target]
        for target in targets:
            if (retention := self._target_retention(target, function)) is not None:
                yield _Finding(target, retention)

    def _target_retention(self, target: ast.expr, function: _Function) -> _Retention | None:
        match target:
            case ast.Name(id=name):
                return _Retention.GLOBAL if name in self._globals.get(function, ()) else None
            case ast.Attribute(value=container) | ast.Subscript(value=container):
                return self._container_retention(_without_subscripts(container), function)
            case _:
                return None

    def _container_retention(self, container: ast.expr, function: _Function) -> _Retention | None:
        path = _attribute_path(container)
        if any(path == state or path.endswith(f".{state}") for state in self._options.process_state):
            return _Retention.PROCESS_STATE
        if (root := _root(container)) is None:
            return None
        if (method := self._method_binding(root, function)) is not None:
            return self._receiver_retention(method)
        if root in self._classes:
            return _Retention.CLASS_STATE
        return _Retention.MODULE_OBJECT if root in self._module_names and not self._is_local(root, function) else None

    def _method_binding(self, root: str, function: _Function) -> _Definition | None:
        for enclosing in self._enclosing(function):
            match enclosing, self._context.parents.get(enclosing):
                case ((ast.FunctionDef() | ast.AsyncFunctionDef() as method), ast.ClassDef()):
                    receiver = next(iter([*method.args.posonlyargs, *method.args.args]), None)
                    return method if receiver is not None and receiver.arg == root else None
                case _:
                    continue
        return None

    def _receiver_retention(self, method: _Definition) -> _Retention | None:
        if any(_is_name(decorator, "classmethod") for decorator in method.decorator_list):
            return _Retention.CLASS_STATE
        match self._context.parents.get(method):
            case ast.ClassDef(name=name) if name in self._options.unit_of_work_types:
                return None
            case _:
                return _Retention.INSTANCE_STATE

    def _is_local(self, name: str, function: _Function) -> bool:
        return name not in self._globals.get(function, ()) and any(
            name in self._bound.get(enclosing, ()) or name in _parameters(enclosing)
            for enclosing in self._enclosing(function)
        )

    def _environment(self, function: _Function) -> dict[str, _Kind]:
        if (known := self._environments.get(function)) is not None:
            return known
        outer = self._owner(function)
        environment = {} if outer is None else dict(self._environment(outer))
        for parameter in _arguments(function):
            environment.pop(parameter.arg, None)
            if self._is_snapshot_type(parameter.annotation):
                environment[parameter.arg] = _Kind.SNAPSHOT
        self._environments[function] = environment
        bindings = [*self._stores.get(function, ()), *self._walruses.get(function, ())]
        changed = True
        while changed:
            changed = self._bind(bindings, environment)
        return environment

    def _bind(self, bindings: list[_Store | ast.NamedExpr], environment: dict[str, _Kind]) -> bool:
        changed = False
        for binding in bindings:
            match binding:
                case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation) if self._is_snapshot_type(
                    annotation
                ):
                    kind = _Kind.SNAPSHOT
                case (
                    ast.Assign(targets=[ast.Name(id=name), *_], value=value)
                    | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
                    | ast.NamedExpr(target=ast.Name(id=name), value=value)
                ):
                    kind = self._kind(value, environment)
                case _:
                    continue
            if kind is not None and name not in environment:
                environment[name] = kind
                changed = True
        return changed

    def _kind(self, node: ast.expr, environment: Mapping[str, _Kind]) -> _Kind | None:
        match node:
            case ast.Await(value=value) | ast.NamedExpr(value=value):
                return self._kind(value, environment)
            case ast.Name(id=name):
                return environment.get(name)
            case ast.IfExp(body=body, orelse=orelse):
                return self._kind(body, environment) or self._kind(orelse, environment)
            case ast.BoolOp(values=values):
                return next((kind for value in values if (kind := self._kind(value, environment)) is not None), None)
            case ast.Call():
                return self._call_kind(node, environment)
            case ast.Attribute(value=value) | ast.Subscript(value=value) | ast.UnaryOp(operand=value):
                return None if self._kind(value, environment) is None else _Kind.DERIVED
            case ast.Compare(left=left, comparators=comparators):
                return self._any_derived([left, *comparators], environment)
            case ast.BinOp(left=left, right=right):
                return self._any_derived([left, right], environment)
            case ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements):
                return self._any_derived(elements, environment)
            case ast.Dict(values=values):
                return self._any_derived(values, environment)
            case _:
                return None

    def _any_derived(self, nodes: list[ast.expr], environment: Mapping[str, _Kind]) -> _Kind | None:
        return _Kind.DERIVED if any(self._kind(node, environment) is not None for node in nodes) else None

    def _call_kind(self, call: ast.Call, environment: Mapping[str, _Kind]) -> _Kind | None:
        if self._is_resolver(call):
            return _Kind.SNAPSHOT
        match call.func:
            case ast.Attribute(value=receiver) if self._kind(receiver, environment) is not None:
                return _Kind.DERIVED
            case ast.Attribute(attr=method) if method in self._options.selector_methods:
                arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
                selects = any(self._kind(argument, environment) is _Kind.SNAPSHOT for argument in arguments)
                return _Kind.DERIVED if selects else None
            case _:
                return None

    def _is_resolver(self, call: ast.Call) -> bool:
        match call.func:
            case ast.Name(id=name) if name in self._resolvers:
                return True
            case ast.Attribute(attr=method) if method in self._options.resolver_methods:
                return True
            case function:
                return self._owned_symbol(function) in self._options.resolver_functions

    def _is_snapshot_type(self, annotation: ast.expr | None) -> bool:
        match annotation:
            case None:
                return False
            case ast.Constant(value=str() as text):
                try:
                    parsed = ast.parse(text, mode="eval").body
                except SyntaxError:
                    return False
                return self._is_snapshot_type(parsed)
            case _:
                types = self._options.snapshot_types
                return any(self._owned_symbol(node) in types for node in ast.walk(annotation))

    def _owned_symbol(self, node: ast.AST) -> str | None:
        match node:
            case ast.Name(id=name) if name in self._classes:
                return name
            case ast.Name() | ast.Attribute():
                qualified = self._imports.resolved_qualified_name(node)
            case _:
                return None
        if qualified is None:
            return None
        module, _, symbol = qualified.rpartition(".")
        return symbol if self._options.owns_module(module) else None

    def _decorated_memoised(self) -> Iterator[_Function]:
        for definition in self._definitions:
            match self._context.parents.get(definition):
                case ast.ClassDef(name=name) if name in self._options.unit_of_work_types:
                    continue
                case _:
                    pass
            if any(self._is_memoizer(decorator) for decorator in definition.decorator_list):
                yield definition

    def _wrapped_memoised(self) -> Iterator[_Function]:
        for call in self._context.nodes(ast.Call):
            if not self._is_memoizer(call.func):
                continue
            match call.args:
                case [ast.Lambda() as wrapped, *_]:
                    yield wrapped
                case [ast.Name(id=name), *_]:
                    yield from (definition for definition in self._definitions if definition.name == name)
                case _:
                    pass

    def _is_memoizer(self, node: ast.expr) -> bool:
        match node:
            case ast.Call(func=target) | target:
                qualified = self._imports.resolved_qualified_name(target)
        return qualified is not None and (qualified in _MEMOIZERS or qualified in self._options.memoizers)

    def _by_owner[NodeT: ast.AST](self, nodes: list[NodeT]) -> dict[_Function | None, list[NodeT]]:
        grouped: dict[_Function | None, list[NodeT]] = {}
        for node in nodes:
            grouped.setdefault(self._owner(node), []).append(node)
        return grouped

    def _enclosing(self, function: _Function | None) -> Iterator[_Function]:
        while function is not None:
            yield function
            function = self._owner(function)

    def _owner(self, node: ast.AST) -> _Function | None:
        if node not in self._owners:
            self._owners[node] = self._find_owner(node)
        return self._owners[node]

    def _find_owner(self, node: ast.AST) -> _Function | None:
        child = node
        while (parent := self._context.parents.get(child)) is not None:
            match parent:
                case ast.Lambda(body=body) if child is body:
                    return parent
                case ast.FunctionDef(body=statements) | ast.AsyncFunctionDef(body=statements) if any(
                    child is statement for statement in statements
                ):
                    return parent
                case _:
                    child = parent
        return None


def _arguments(function: _Function) -> list[ast.arg]:
    arguments = function.args
    variadic = [argument for argument in (arguments.vararg, arguments.kwarg) if argument is not None]
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *variadic]


def _parameters(function: _Function) -> frozenset[str]:
    return frozenset(argument.arg for argument in _arguments(function))


def _without_subscripts(node: ast.expr) -> ast.expr:
    while isinstance(node, ast.Subscript):
        node = node.value
    return node


def _attribute_path(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    match node:
        case ast.Name(id=name):
            parts.append(name)
        case _:
            pass
    return ".".join(reversed(parts))


def _root(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    match node:
        case ast.Name(id=name):
            return name
        case _:
            return None


def _is_name(node: ast.expr, name: str) -> bool:
    match node:
        case ast.Name(id=found):
            return found == name
        case _:
            return False
