from __future__ import annotations

import ast
from dataclasses import dataclass, field
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef

_MOCK_FACTORIES = frozenset({"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"})
_MOCK_CONTROLS = frozenset({"spec", "spec_set", "wraps", "name", "unsafe", "return_value", "side_effect"})
_METHOD_DECORATORS = frozenset({"abc.abstractmethod", "typing.override", "typing_extensions.override"})
_CLASS_DECORATORS = frozenset({"typing.final", "typing_extensions.final"})
_TERMINAL_BASES = frozenset({"builtins.object", "abc.ABC", "pydantic.BaseModel", "pydantic.main.BaseModel"})
_SETATTR_ARITY = 3


@dataclass(frozen=True, slots=True)
class _ForwardedOriginal:
    variable: str
    reference: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Binding:
    contract: SymbolRef | None = None
    mock: ast.Call | None = None
    callable: bool = False
    original: tuple[str, ...] | None = None
    forwarded: frozenset[_ForwardedOriginal] = frozenset()


@dataclass(slots=True)
class _ModelMock:
    contract: SymbolRef
    fields: set[str] = field(default_factory=set)
    behavioral: bool = False


@dataclass(frozen=True, slots=True)
class _Analysis:
    grafts: list[tuple[ast.AST, str]]
    model_mocks: list[tuple[ast.Call, str]]


@final
class TestProvenance:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.indexes = context.session.project or ProjectIndexSet.single(context.path, context.source)
        tree = context.tree
        indexed_unit = (
            self.indexes.unit_or_source(context.path, context.source, tree)
            if tree is not None
            else self.indexes.unit(context.path)
        )
        self.unit = (
            indexed_unit
            if indexed_unit is not None and indexed_unit.module is not None
            else SourceUnit(
                path=context.path,
                module="__test_source__",
                source=context.source,
                tree=context.tree,
                imports={
                    name: SymbolRef(target.module, target.symbol or "")
                    for name, target in context.module_imports.bindings.items()
                },
            )
        )
        self._classes: dict[SymbolRef, tuple[SourceUnit, ast.ClassDef]] = {}
        self._members: dict[tuple[SymbolRef, str], str | None] = {}
        self._scope_imports: dict[_Function, ImportIndex] = {}
        self._module_writes: dict[str | None, frozenset[str]] = {}
        self._module_indexes: dict[str | None, ImportIndex] = {}
        self._fixtures: dict[str, _Binding | None] = {}
        self._models: dict[ast.Call, _ModelMock] = {}
        self._grafts: list[tuple[ast.AST, str]] = []
        self._restoring: dict[tuple[str, ...], str] = {}

    def method_grafts(self) -> list[tuple[ast.AST, str]]:
        return self._analyzed.grafts

    def model_data_mocks(self) -> list[tuple[ast.Call, str]]:
        return self._analyzed.model_mocks

    @cached_property
    def _functions(self) -> tuple[_Function, ...]:
        tree = self.context.tree
        if tree is None:
            return ()
        return tuple(
            function
            for statement in tree.body
            for function in (
                (statement,)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                else tuple(statement.body)
                if isinstance(statement, ast.ClassDef)
                else ()
            )
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

    @cached_property
    def _analyzed(self) -> _Analysis:
        for function in self._functions:
            if not _inside_constructor(function):
                self._scan(function, self._parameters(function))
        models = [
            (call, model.contract.name) for call, model in self._models.items() if model.fields and not model.behavioral
        ]
        return _Analysis(grafts=self._grafts, model_mocks=models)

    def _class(self, symbol: SymbolRef) -> tuple[SourceUnit, ast.ClassDef] | None:
        if symbol in self._classes:
            return self._classes[symbol]
        unit = self.unit if symbol.module == self.unit.module else self.indexes.source_unit(symbol.module)
        if unit is None or unit.tree is None:
            return None
        candidates = [node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == symbol.name]
        if len(candidates) != 1 or symbol.name in self._writes(unit) or candidates[0].keywords:
            return None
        imports = self._module_imports(unit)
        if any(
            imports.resolved_qualified_name(decorator) not in _CLASS_DECORATORS
            for decorator in candidates[0].decorator_list
        ) or any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"__new__", "__getattribute__", "__getattr__"}
            for node in candidates[0].body
        ):
            return None
        result = unit, candidates[0]
        self._classes[symbol] = result
        return result

    def _symbol(self, expression: ast.expr, unit: SourceUnit | None = None) -> SymbolRef | None:
        owner = unit or self.unit
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            try:
                return self._symbol(ast.parse(expression.value, mode="eval").body, owner)
            except SyntaxError:
                return None
        if isinstance(expression, ast.Subscript):
            return self._symbol(expression.value, owner)
        if isinstance(expression, ast.Name) and expression.id in self._writes(owner):
            return None
        return self.indexes.resolve(owner, expression)

    def _writes(self, unit: SourceUnit) -> frozenset[str]:
        if unit.module not in self._module_writes:
            self._module_writes[unit.module] = _scope_writes(unit.tree.body) if unit.tree is not None else frozenset()
        return self._module_writes[unit.module]

    def _bases(self, unit: SourceUnit, node: ast.ClassDef) -> tuple[SymbolRef, ...] | None:
        bases: list[SymbolRef] = []
        for expression in node.bases:
            if isinstance(expression, ast.Name) and expression.id == "object":
                symbol = SymbolRef("builtins", "object")
            else:
                symbol = self._symbol(expression, unit)
            if symbol is None:
                return None
            bases.append(symbol)
        return tuple(bases)

    def _member(self, symbol: SymbolRef, name: str, seen: frozenset[SymbolRef] = frozenset()) -> str | None:
        key = symbol, name
        if key in self._members:
            return self._members[key]
        if symbol in seen or (resolved := self._class(symbol)) is None:
            return None
        unit, node = resolved
        if unit.tree is None:
            return None
        direct = _declared_member(node, name, self._module_imports(unit))
        if direct is not None:
            self._members[key] = direct
            return direct
        bases = self._bases(unit, node)
        if bases is None:
            return None
        inherited: list[str] = []
        for base in bases:
            if f"{base.module}.{base.name}" in _TERMINAL_BASES:
                continue
            if self._class(base) is None:
                return None
            member = self._member(base, name, seen | {symbol})
            if member is not None:
                inherited.append(member)
        result = inherited[0] if len(inherited) == 1 else None
        self._members[key] = result
        return result

    def _expression(
        self, expression: ast.expr, bindings: Mapping[str, _Binding], imports: ImportIndex, *, factories: bool = True
    ) -> _Binding | None:
        match expression:
            case ast.Name(id=name):
                return bindings.get(name)
            case ast.Lambda():
                return _Binding(callable=True)
            case ast.Attribute(value=receiver, attr=name):
                parent = self._expression(receiver, bindings, imports)
                if (
                    parent is not None
                    and parent.contract is not None
                    and self._member(parent.contract, name) == "method"
                ):
                    return _Binding(callable=True, original=_reference(expression))
                return None
            case ast.Call():
                return self._call_expression(expression, bindings, imports, factories=factories)
            case _:
                return None

    def _call_expression(
        self, expression: ast.Call, bindings: Mapping[str, _Binding], imports: ImportIndex, *, factories: bool
    ) -> _Binding | None:
        factory = _mock_factory(expression.func, imports)
        if factory in _MOCK_FACTORIES or factory == "create_autospec":
            return self._mock_expression(expression, bindings, factory=factory)
        if isinstance(expression.func, ast.Name) and expression.func.id in bindings:
            return None
        contract = self._symbol(expression.func)
        if contract is not None and self._class(contract) is not None:
            return _Binding(contract=contract)
        if factories and isinstance(expression.func, ast.Name) and not expression.args and not expression.keywords:
            candidates = [function for function in self._functions if function.name == expression.func.id]
            if len(candidates) == 1:
                return self._returned_binding(candidates[0])
        return None

    def _mock_expression(
        self, expression: ast.Call, bindings: Mapping[str, _Binding], *, factory: str
    ) -> _Binding | None:
        if not _instance_mock(expression, factory=factory):
            return None
        spec = _mock_spec(expression, factory=factory)
        if spec is None:
            return None
        contract = (
            bindings[spec.id].contract if isinstance(spec, ast.Name) and spec.id in bindings else self._symbol(spec)
        )
        if contract is None or self._class(contract) is None:
            return None
        if self._pydantic(contract):
            self._track_model_constructor(expression, contract)
        return _Binding(contract=contract, mock=expression)

    def _track_model_constructor(self, expression: ast.Call, contract: SymbolRef) -> None:
        model = self._models.setdefault(expression, _ModelMock(contract))
        model.fields.update(
            keyword.arg
            for keyword in expression.keywords
            if keyword.arg is not None
            and keyword.arg not in _MOCK_CONTROLS
            and self._member(contract, keyword.arg) == "field"
        )
        if any(
            keyword.arg is None or keyword.arg in {"side_effect", "return_value"} for keyword in expression.keywords
        ):
            model.behavioral = True

    def _pydantic(self, symbol: SymbolRef, seen: frozenset[SymbolRef] = frozenset()) -> bool:
        if symbol in seen or (resolved := self._class(symbol)) is None:
            return False
        unit, node = resolved
        bases = self._bases(unit, node)
        return bases is not None and any(
            f"{base.module}.{base.name}" in {"pydantic.BaseModel", "pydantic.main.BaseModel"}
            or self._pydantic(base, seen | {symbol})
            for base in bases
        )

    def _module_imports(self, unit: SourceUnit) -> ImportIndex:
        if unit.module not in self._module_indexes:
            tree = unit.tree or ast.Module(body=[], type_ignores=[])
            self._module_indexes[unit.module] = ImportIndex.from_tree(tree, module_scope_only=True)
        return self._module_indexes[unit.module]

    def _imports(self, function: _Function) -> ImportIndex:
        if function in self._scope_imports:
            return self._scope_imports[function]
        local = ImportIndex.from_tree(ast.Module(body=[function, *function.body], type_ignores=[]))
        module = self._lexical_imports
        bindings = {
            name: target
            for name, target in module.bindings.items()
            if name not in local.shadowed_names and (name not in local.bindings or local.bindings[name] == target)
        }
        result = ImportIndex(MappingProxyType(bindings), module.shadowed_names | local.shadowed_names)
        self._scope_imports[function] = result
        return result

    @cached_property
    def _lexical_imports(self) -> ImportIndex:
        tree = self.context.tree
        if tree is None:
            return ImportIndex.from_tree(ast.Module(body=[], type_ignores=[]))
        module = ast.Module(
            body=[
                *(
                    statement
                    for statement in tree.body
                    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ),
            ],
            type_ignores=[],
        )
        return ImportIndex.from_tree(module)

    def _parameters(self, function: _Function, *, fixtures: bool = True) -> dict[str, _Binding]:
        result: dict[str, _Binding] = {}
        for parameter in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
            annotation = parameter.annotation
            symbol = self._symbol(annotation) if annotation is not None else None
            if symbol is not None and self._class(symbol) is not None:
                result[parameter.arg] = _Binding(contract=symbol)
            elif fixtures and function.name.startswith("test_"):
                binding = self._fixture(parameter.arg)
                result[parameter.arg] = binding or _Binding()
            else:
                result[parameter.arg] = _Binding()
        return result

    def _fixture(self, name: str) -> _Binding | None:
        if name in self._fixtures:
            return self._fixtures[name]
        self._fixtures[name] = None
        candidates = self._fixture_functions.get(name, [])
        if len(candidates) != 1:
            return None
        result = self._returned_binding(candidates[0])
        self._fixtures[name] = result
        return result

    @cached_property
    def _fixture_functions(self) -> dict[str, list[_Function]]:
        candidates: dict[str, list[_Function]] = {}
        for function in self._functions:
            name = self._fixture_name(function)
            if name is not None:
                candidates.setdefault(name, []).append(function)
        return candidates

    def _returned_binding(self, function: _Function) -> _Binding | None:
        bindings = self._parameters(function, fixtures=False)
        imports = self._imports(function)
        returns: list[_Binding | None] = []
        for statement in function.body:
            if isinstance(statement, ast.Return) and statement.value is not None:
                returns.append(self._expression(statement.value, bindings, imports, factories=False))
            elif (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Yield)
                and statement.value.value is not None
            ):
                returns.append(self._expression(statement.value.value, bindings, imports, factories=False))
            else:
                self._bind(statement, bindings, imports)
        return returns[0] if len(returns) == 1 else None

    def _fixture_name(self, function: _Function) -> str | None:
        if not function.decorator_list:
            return None
        imports = self._imports(function)
        for decorator in function.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if not imports.resolves(target, sources=frozenset({"pytest", "pytest_asyncio"}), symbol="fixture"):
                continue
            return _fixture_public_name(function, decorator)
        return None

    def _scan(self, function: _Function, bindings: dict[str, _Binding]) -> None:
        imports = self._imports(function)
        if not function.name.startswith("test_") and self._fixture_name(function) is None and _has_graft(function):
            bindings.update(self._helper_parameters(function))
        self._restoring = _restored_methods(function)
        for statement in function.body:
            self._observe(statement, bindings, imports)
            self._bind(statement, bindings, imports)

    def _helper_parameters(self, function: _Function) -> dict[str, _Binding]:
        calls: list[dict[str, _Binding]] = []
        for caller in self._helper_callers.get(function.name, []):
            bindings = self._parameters(caller)
            imports = self._imports(caller)
            for statement in caller.body:
                calls.extend(
                    self._call_bindings(function, call, bindings, imports)
                    for call in _scope_nodes(statement)
                    if isinstance(call, ast.Call) and _helper_call(call.func, function.name)
                )
                self._bind(statement, bindings, imports)
        if not calls:
            return {}
        return {name: value for name, value in calls[0].items() if all(mapping.get(name) == value for mapping in calls)}

    @cached_property
    def _helper_callers(self) -> dict[str, list[_Function]]:
        callers: dict[str, list[_Function]] = {}
        for function in self._functions:
            if not function.name.startswith("test_"):
                continue
            names = {
                name
                for statement in function.body
                for node in _scope_nodes(statement)
                if isinstance(node, ast.Call) and (name := _helper_call_name(node.func)) is not None
            }
            for name in names:
                callers.setdefault(name, []).append(function)
        return callers

    def _call_bindings(
        self, function: _Function, call: ast.Call, bindings: Mapping[str, _Binding], imports: ImportIndex
    ) -> dict[str, _Binding]:
        if any(isinstance(arg, ast.Starred) for arg in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            return {}
        parameters = [*function.args.posonlyargs, *function.args.args]
        if isinstance(call.func, ast.Attribute) and parameters and parameters[0].arg == "self":
            parameters = parameters[1:]
        supplied = dict(zip((arg.arg for arg in parameters), call.args, strict=False))
        supplied.update({keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None})
        return {
            name: value
            for name, expression in supplied.items()
            if (value := self._expression(expression, bindings, imports)) is not None
        }

    def _observe(self, statement: ast.stmt, bindings: Mapping[str, _Binding], imports: ImportIndex) -> None:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return, ast.Raise, ast.Assert)):
            self._exclude_ambiguous_models(statement, bindings)
            return
        self._observe_grafts(statement, bindings, imports)
        for node in _scope_nodes(statement):
            if isinstance(node, ast.Attribute):
                self._observe_model_attribute(node, bindings)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                model = self._model_receiver(node.func, bindings)
                if model is not None:
                    model.behavioral = True

    def _observe_grafts(self, statement: ast.stmt, bindings: Mapping[str, _Binding], imports: ImportIndex) -> None:
        match statement:
            case ast.Assign(targets=targets, value=value):
                self._observe_assignment_grafts(targets, value, bindings, imports)
            case ast.AnnAssign(target=target, value=value) if value is not None:
                self._observe_assignment_grafts([target], value, bindings, imports)
            case ast.Expr(value=ast.Call() as call):
                self._observe_setattr(call, bindings, imports)
            case _:
                pass

    def _observe_assignment_grafts(
        self, targets: list[ast.expr], value: ast.expr, bindings: Mapping[str, _Binding], imports: ImportIndex
    ) -> None:
        replacement = self._expression(value, bindings, imports)
        for target in targets:
            if isinstance(target, ast.Attribute):
                self._graft(target, target.value, target.attr, replacement, bindings=bindings, imports=imports)

    def _observe_setattr(self, call: ast.Call, bindings: Mapping[str, _Binding], imports: ImportIndex) -> None:
        if not (
            isinstance(call.func, ast.Name)
            and call.func.id == "setattr"
            and imports.builtin_is_unshadowed("setattr")
            and len(call.args) == _SETATTR_ARITY
        ):
            return
        name = call.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            self._graft(
                call,
                call.args[0],
                name.value,
                self._expression(call.args[2], bindings, imports),
                bindings=bindings,
                imports=imports,
            )

    def _model_receiver(self, node: ast.Attribute, bindings: Mapping[str, _Binding]) -> _ModelMock | None:
        reference = _root_attribute(node)
        if reference is None:
            return None
        binding = bindings.get(reference[0])
        return self._models.get(binding.mock) if binding is not None and binding.mock is not None else None

    def _observe_model_attribute(self, node: ast.Attribute, bindings: Mapping[str, _Binding]) -> None:
        model = self._model_receiver(node, bindings)
        reference = _root_attribute(node)
        if model is None or reference is None:
            return
        member = self._member(model.contract, reference[1])
        if member == "field" and isinstance(node.ctx, ast.Store):
            model.fields.add(reference[1])
        if member == "method" or node.attr in {"configure_mock", "attach_mock", "mock_add_spec", "reset_mock"}:
            model.behavioral = True
        if node.attr in {"side_effect", "return_value"} and isinstance(node.value, ast.Attribute):
            model.behavioral = True

    def _exclude_ambiguous_models(self, statement: ast.stmt, bindings: Mapping[str, _Binding]) -> None:
        for node in walk(statement):
            if (
                isinstance(node, ast.Name)
                and (binding := bindings.get(node.id)) is not None
                and binding.mock is not None
            ):
                model = self._models.get(binding.mock)
                if model is not None:
                    model.behavioral = True

    def _graft(
        self,
        location: ast.AST,
        receiver: ast.expr,
        name: str,
        replacement: _Binding | None,
        *,
        bindings: Mapping[str, _Binding],
        imports: ImportIndex,
    ) -> None:
        binding = self._expression(receiver, bindings, imports)
        if (
            binding is not None
            and binding.contract is not None
            and replacement is not None
            and replacement.callable
            and self._member(binding.contract, name) == "method"
        ):
            destination = _reference(receiver)
            reference = (*destination, name) if destination is not None else None
            if reference is not None and self._preserves_original(reference, replacement, bindings):
                return
            self._grafts.append((location, name))

    def _preserves_original(
        self, reference: tuple[str, ...], replacement: _Binding, bindings: Mapping[str, _Binding]
    ) -> bool:
        if replacement.original == reference or any(
            forwarded.reference == reference
            and (current := bindings.get(forwarded.variable)) is not None
            and current.original == reference
            for forwarded in replacement.forwarded
        ):
            return True
        saved_name = self._restoring.get(reference)
        saved = bindings.get(saved_name) if saved_name is not None else None
        return saved is not None and saved.original == reference

    def _bind(self, statement: ast.stmt, bindings: dict[str, _Binding], imports: ImportIndex) -> None:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                bindings[statement.name] = _Binding(
                    callable=not statement.decorator_list, forwarded=_forwarded_originals(statement, bindings)
                )
            case ast.ClassDef(name=name):
                bindings[name] = _Binding()
            case ast.Assign(targets=targets, value=value):
                self._bind_assignment(targets, value, bindings, imports)
            case ast.AnnAssign(target=target, value=value):
                self._bind_assignment([target], value, bindings, imports)
            case _:
                for name in _scope_writes([statement]):
                    bindings[name] = _Binding()

    def _bind_assignment(
        self, targets: list[ast.expr], expression: ast.expr | None, bindings: dict[str, _Binding], imports: ImportIndex
    ) -> None:
        value = self._expression(expression, bindings, imports) if expression is not None else None
        for target in targets:
            for name in _target_names(target):
                bindings[name] = value if isinstance(target, ast.Name) and value is not None else _Binding()


def _declared_member(node: ast.ClassDef, name: str, imports: ImportIndex) -> str | None:
    member: str | None = None
    for statement in node.body:
        field_kind = _declared_field(statement, name, imports)
        if field_kind is not None:
            return field_kind
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == name:
            member = (
                "method"
                if all(_transparent_method_decorator(item, imports) for item in statement.decorator_list)
                else "descriptor"
            )
    return member


def _declared_field(statement: ast.stmt, name: str, imports: ImportIndex) -> str | None:
    match statement:
        case ast.AnnAssign(target=ast.Name(id=target), annotation=annotation) if target == name:
            head = annotation.value if isinstance(annotation, ast.Subscript) else annotation
            return (
                "descriptor"
                if imports.resolved_qualified_name(head) in {"typing.ClassVar", "typing_extensions.ClassVar"}
                else "field"
            )
        case ast.Assign(targets=targets) if any(name in _target_names(target) for target in targets):
            return "field"
        case ast.FunctionDef(name="__init__") | ast.AsyncFunctionDef(name="__init__"):
            if _constructor_field(statement, name):
                return "field"
        case _:
            pass
    return None


def _constructor_field(function: _Function, name: str) -> bool:
    return any(
        isinstance(child, ast.Attribute)
        and isinstance(child.ctx, ast.Store)
        and isinstance(child.value, ast.Name)
        and child.value.id == "self"
        and child.attr == name
        for child in _scope_nodes(function, include_root=True)
    )


def _transparent_method_decorator(decorator: ast.expr, imports: ImportIndex) -> bool:
    return (
        isinstance(decorator, ast.Name)
        and decorator.id in {"staticmethod", "classmethod"}
        and imports.builtin_is_unshadowed(decorator.id)
    ) or imports.resolved_qualified_name(decorator) in _METHOD_DECORATORS


def _instance_mock(expression: ast.Call, *, factory: str) -> bool:
    if any(keyword.arg == "wraps" for keyword in expression.keywords):
        return False
    return factory != "create_autospec" or any(
        keyword.arg == "instance" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in expression.keywords
    )


def _mock_factory(expression: ast.expr, imports: ImportIndex) -> str | None:
    factory = imports.resolved_symbol(expression, sources=frozenset({"unittest.mock"}))
    if factory is not None:
        return factory
    if isinstance(expression, ast.Attribute) and imports.resolved_qualified_name(expression.value) == "unittest.mock":
        return expression.attr
    return None


def _mock_spec(expression: ast.Call, *, factory: str) -> ast.expr | None:
    spec = next((keyword.value for keyword in expression.keywords if keyword.arg == "spec"), None)
    if spec is None and expression.args:
        spec = expression.args[0]
    if factory != "create_autospec":
        strict_spec = next((keyword.value for keyword in expression.keywords if keyword.arg == "spec_set"), None)
        if strict_spec is not None and not (isinstance(strict_spec, ast.Constant) and strict_spec.value is None):
            spec = strict_spec
    return spec.func if isinstance(spec, ast.Call) else spec


def _fixture_public_name(function: _Function, decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Call):
        named = next((keyword.value for keyword in decorator.keywords if keyword.arg == "name"), None)
        if named is not None:
            return named.value if isinstance(named, ast.Constant) and isinstance(named.value, str) else None
    return function.name


def _scope_writes(statements: list[ast.stmt]) -> frozenset[str]:
    return frozenset(
        name
        for statement in statements
        for node in _scope_nodes(statement)
        if (name := _captured_name(node)) is not None
    )


def _captured_name(node: ast.AST) -> str | None:
    match node:
        case (
            ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
            | ast.ExceptHandler(name=str(name))
            | ast.MatchAs(name=str(name))
            | ast.MatchStar(name=str(name))
            | ast.MatchMapping(rest=str(name))
        ):
            return name
        case _:
            return None


def _forwarded_originals(function: _Function, bindings: Mapping[str, _Binding]) -> frozenset[_ForwardedOriginal]:
    originals: set[_ForwardedOriginal] = set()
    local_imports = ImportIndex.from_tree(ast.Module(body=[function], type_ignores=[]))
    for statement in function.body:
        for node in _scope_nodes(statement):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and local_imports.builtin_is_unshadowed(node.func.id)
            ):
                binding = bindings.get(node.func.id)
                if binding is not None and binding.original is not None:
                    originals.add(_ForwardedOriginal(variable=node.func.id, reference=binding.original))
    return frozenset(originals)


def _restored_methods(function: _Function) -> dict[tuple[str, ...], str]:
    restored: dict[tuple[str, ...], str] = {}
    for statement in function.body:
        if not isinstance(statement, (ast.Try, ast.TryStar)):
            continue
        written = _scope_writes([statement])
        for restoration in statement.finalbody:
            if not isinstance(restoration, ast.Assign) or not isinstance(restoration.value, ast.Name):
                continue
            if restoration.value.id in written:
                continue
            for target in restoration.targets:
                reference = _reference(target)
                if reference is not None and reference[0] not in written:
                    restored[reference] = restoration.value.id
    return restored


def _reference(expression: ast.expr) -> tuple[str, ...] | None:
    match expression:
        case ast.Name(id=name):
            return (name,)
        case ast.Attribute(value=receiver, attr=name):
            parent = _reference(receiver)
            return (*parent, name) if parent is not None else None
        case _:
            return None


def _has_graft(function: _Function) -> bool:
    return any(
        (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and isinstance(statement.value, (ast.Name, ast.Attribute, ast.Lambda))
            and any(
                isinstance(target, ast.Attribute)
                for target in (statement.targets if isinstance(statement, ast.Assign) else [statement.target])
            )
        )
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "setattr"
        )
        for statement in function.body
    )


def _target_names(target: ast.expr) -> set[str]:
    return {
        node.id for node in walk(target) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    }


def _scope_nodes(node: ast.AST, *, include_root: bool = False) -> Iterator[ast.AST]:
    if not include_root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _scope_nodes(child)


def _root_attribute(node: ast.Attribute) -> tuple[str, str] | None:
    first = node
    while isinstance(first.value, ast.Attribute):
        first = first.value
    return (first.value.id, first.attr) if isinstance(first.value, ast.Name) else None


def _helper_call(expression: ast.expr, name: str) -> bool:
    return _helper_call_name(expression) == name


def _helper_call_name(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name) | ast.Attribute(value=ast.Name(id="self"), attr=name):
            return name
        case _:
            return None


def _inside_constructor(function: _Function) -> bool:
    return function.name in {"__init__", "__new__"}
