from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, scope_bound_names
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MODEL_BASES = frozenset({"pydantic.BaseModel", "pydantic.main.BaseModel"})
_PYDANTIC = frozenset({"pydantic", "pydantic.functional_validators"})
_TYPING = frozenset({"typing", "typing_extensions"})
_COLLECTIONS = frozenset({"collections.abc", "typing", "typing_extensions"})
_TWO_ARGUMENTS = 2
_ANNOTATION_DEPTH_LIMIT = 24
_LIST_MUTATORS = frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"})
_DICT_MUTATORS = frozenset({"clear", "pop", "popitem", "setdefault", "update"})
_SET_MUTATORS = frozenset(
    {
        "add",
        "clear",
        "difference_update",
        "discard",
        "intersection_update",
        "pop",
        "remove",
        "symmetric_difference_update",
        "update",
    }
)


@dataclass(frozen=True, slots=True)
class _Shape:
    kind: str = "unknown"
    model: SymbolRef | None = None
    element: _Shape | None = None


@dataclass(frozen=True, slots=True)
class _Value:
    shape: _Shape
    borrowed: bool = False
    shared_children: bool = False
    fields: tuple[tuple[str, _Value], ...] = ()
    element: _Value | None = None


@dataclass(frozen=True, slots=True)
class Mutation:
    node: ast.expr
    before_validator: bool


@final
class _Models:
    def __init__(self, context: PythonFileContext) -> None:
        self.indexes = context.session.project or ProjectIndexSet.single(context.path, context.source)
        unit = self.indexes.unit(context.path)
        self.unit = (
            unit
            if unit is not None and unit.module is not None
            else SourceUnit(
                context.path,
                "__copy_source__",
                context.source,
                context.tree,
                {
                    name: SymbolRef(target.module, target.symbol or "")
                    for name, target in context.module_imports.bindings.items()
                },
            )
        )
        self._classes: dict[SymbolRef, tuple[SourceUnit, ast.ClassDef] | None] = {}
        self._ancestry: dict[SymbolRef, bool] = {}
        self._fields: dict[tuple[SymbolRef, str], _Shape | None] = {}
        self._annotations: dict[str | None, AnnotationSemantics] = {}

    def annotations(self, unit: SourceUnit) -> AnnotationSemantics:
        if unit.module not in self._annotations:
            tree = unit.tree if unit.tree is not None else ast.Module(body=[], type_ignores=[])
            self._annotations[unit.module] = AnnotationSemantics.from_tree(tree)
        return self._annotations[unit.module]

    def symbol(self, expression: ast.expr, unit: SourceUnit | None = None) -> SymbolRef | None:
        owner = unit or self.unit
        if owner.tree is None:
            return None
        imports = self.annotations(owner).imports
        qualified = imports.resolved_qualified_name(expression)
        if qualified is not None:
            module, _, name = qualified.rpartition(".")
            return SymbolRef(module, name)
        if isinstance(expression, ast.Name) and expression.id in imports.shadowed_names:
            return SymbolRef(owner.module or "__copy_source__", expression.id)
        if isinstance(expression, ast.Attribute) and any(
            isinstance(node, ast.Name) and node.id in imports.shadowed_names for node in ast.walk(expression)
        ):
            return None
        return self.indexes.resolve(owner, expression)

    def class_node(self, symbol: SymbolRef) -> tuple[SourceUnit, ast.ClassDef] | None:
        if symbol in self._classes:
            return self._classes[symbol]
        unit = self.unit if symbol.module == self.unit.module else self.indexes.source_unit(symbol.module)
        result = self._plain_class(unit, symbol.name) if unit is not None else None
        self._classes[symbol] = result
        return result

    def _plain_class(self, unit: SourceUnit, name: str) -> tuple[SourceUnit, ast.ClassDef] | None:
        if unit.tree is None:
            return None
        candidates = [node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == name]
        if len(candidates) != 1:
            return None
        node = candidates[0]
        if name in scope_bound_names([statement for statement in unit.tree.body if statement is not node]):
            return None
        if any(keyword.arg == "metaclass" for keyword in node.keywords):
            return None
        imports = self.annotations(unit).imports
        if any(
            imports.resolved_qualified_name(decorator) not in {"typing.final", "typing_extensions.final"}
            for decorator in node.decorator_list
        ):
            return None
        if self._dynamic_class(node):
            return None
        return unit, node

    @staticmethod
    def _dynamic_class(node: ast.ClassDef) -> bool:
        methods = (member for member in node.body if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)))
        return any(member.name in {"__getattr__", "__getattribute__", "__new__"} for member in methods)

    def pydantic(self, symbol: SymbolRef, seen: frozenset[SymbolRef] = frozenset()) -> bool:
        if symbol in self._ancestry:
            return self._ancestry[symbol]
        if symbol in seen or (resolved := self.class_node(symbol)) is None:
            return False
        unit, node = resolved
        result = any(
            base is not None and (f"{base.module}.{base.name}" in _MODEL_BASES or self.pydantic(base, seen | {symbol}))
            for expression in node.bases
            if (base := self.symbol(expression, unit)) is not None
        )
        self._ancestry[symbol] = result
        return result

    def standard_copy(self, symbol: SymbolRef, seen: frozenset[SymbolRef] = frozenset()) -> bool:
        if symbol in seen or (resolved := self.class_node(symbol)) is None:
            return False
        unit, node = resolved
        if any(
            (
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name in {"model_copy", "__copy__", "__deepcopy__"}
            )
            or (
                isinstance(member, (ast.Assign, ast.AnnAssign))
                and any(name in {"model_copy", "__copy__", "__deepcopy__"} for name in scope_bound_names([member]))
            )
            for member in node.body
        ):
            return False
        bases = [self.symbol(base, unit) for base in node.bases]
        return bool(bases) and all(
            base is not None
            and (f"{base.module}.{base.name}" in _MODEL_BASES or self.standard_copy(base, seen | {symbol}))
            for base in bases
        )

    def shape(
        self,
        annotation: ast.expr | None,
        *,
        unit: SourceUnit | None = None,
        blocked: frozenset[str] = frozenset(),
        depth: int = 0,
    ) -> _Shape:
        owner = unit or self.unit
        if owner.tree is None or depth >= _ANNOTATION_DEPTH_LIMIT:
            return _Shape()
        semantics = self.annotations(owner)
        members = [
            member
            for member in semantics.transparent_members(annotation)
            if not (isinstance(member, ast.Constant) and member.value is None)
        ]
        if len(members) != 1:
            return _Shape()
        member = members[0]
        if any(isinstance(node, ast.Name) and node.id in blocked for node in ast.walk(member)):
            return _Shape()
        if isinstance(member, ast.Subscript):
            return self._container_shape(member, owner, blocked, depth)
        symbol = self.symbol(member, owner)
        if symbol is not None and self.pydantic(symbol):
            return _Shape("model", symbol)
        return _Shape(_container_kind(member, semantics.imports) or "unknown")

    def _container_shape(self, member: ast.Subscript, owner: SourceUnit, blocked: frozenset[str], depth: int) -> _Shape:
        kind = _container_kind(member.value, self.annotations(owner).imports)
        if kind is None:
            return _Shape()
        parts = member.slice.elts if isinstance(member.slice, ast.Tuple) else [member.slice]
        if kind == "tuple" and not self._homogeneous_tuple(parts):
            return _Shape()
        element = parts[-1] if kind in {"dict", "mapping"} else parts[0]
        return _Shape(kind, element=self.shape(element, unit=owner, blocked=blocked, depth=depth + 1))

    @staticmethod
    def _homogeneous_tuple(parts: list[ast.expr]) -> bool:
        if len(parts) == 1:
            return True
        return len(parts) == _TWO_ARGUMENTS and isinstance(parts[1], ast.Constant) and parts[1].value is Ellipsis

    def field(self, symbol: SymbolRef, name: str, seen: frozenset[SymbolRef] = frozenset()) -> _Shape | None:
        key = symbol, name
        if key in self._fields:
            return self._fields[key]
        if name.startswith("_") or name == "model_config" or symbol in seen:
            return None
        resolved = self.class_node(symbol)
        if resolved is None:
            return None
        unit, node = resolved
        result = self._declared_field(unit, node, name)
        if result is None and name not in scope_bound_names(node.body):
            result = self._inherited_field(unit, node, name, seen | {symbol})
        self._fields[key] = result
        return result

    def _declared_field(self, unit: SourceUnit, node: ast.ClassDef, name: str) -> _Shape | None:
        annotations = (
            member for member in node.body if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name)
        )
        direct = [member for member in annotations if isinstance(member.target, ast.Name) and member.target.id == name]
        if len(direct) != 1:
            return None
        semantics = self.annotations(unit)
        annotation = semantics.parse(direct[0].annotation)
        if isinstance(annotation, ast.Subscript) and semantics.imports.resolves(
            annotation.value, sources=_TYPING, symbol="ClassVar"
        ):
            return None
        return self.shape(annotation, unit=unit)

    def _inherited_field(
        self, unit: SourceUnit, node: ast.ClassDef, name: str, seen: frozenset[SymbolRef]
    ) -> _Shape | None:
        known: list[_Shape] = []
        for expression in node.bases:
            base = self.symbol(expression, unit)
            field = self.field(base, name, seen) if base is not None else None
            if field is not None:
                known.append(field)
        return known[0] if len(known) == 1 else None


def _container_kind(node: ast.expr, imports: ImportIndex) -> str | None:
    if (
        isinstance(node, ast.Name)
        and node.id in {"list", "dict", "set", "tuple"}
        and imports.builtin_is_unshadowed(node.id)
    ):
        return node.id
    name = imports.resolved_symbol(node, sources=_COLLECTIONS | frozenset({"builtins"}))
    return {
        "List": "list",
        "Sequence": "sequence",
        "MutableSequence": "sequence",
        "list": "list",
        "Dict": "dict",
        "Mapping": "mapping",
        "MutableMapping": "mapping",
        "dict": "dict",
        "Set": "set-interface",
        "MutableSet": "set-interface",
        "set": "set",
        "Tuple": "tuple",
        "tuple": "tuple",
    }.get(name or "")


def _contains_model(shape: _Shape) -> bool:
    return shape.model is not None or (shape.element is not None and _contains_model(shape.element))


@final
class CopyOnWriteAnalysis:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.models = _Models(context)
        self.mutations: list[Mutation] = []
        self.discarded: list[ast.Call] = []
        self._imports = context.module_imports
        self._blocked = frozenset[str]()
        self._before = False
        tree = context.tree
        if tree is None or context.generated:
            return
        self._scan(tree.body, {})
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            self._function(function)

    def _function(self, function: _Function) -> None:
        parameters = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        names = {parameter.arg for parameter in parameters}
        names.update(
            parameter.arg for parameter in (function.args.vararg, function.args.kwarg) if parameter is not None
        )
        self._imports = self._function_imports(function, names)
        self._blocked = frozenset(names | scope_bound_names(function.body))
        before_input = self._validator_input(function)
        self._before = before_input is not None
        bindings = self._parameter_bindings(function, parameters, before_input)
        self._scan(function.body, bindings)

    def _function_imports(self, function: _Function, names: set[str]) -> ImportIndex:
        local = ImportIndex.from_tree(ast.Module(body=function.body, type_ignores=[]))
        by_name = {**self.context.module_imports.bindings, **local.bindings}
        shadows = local.shadowed_names | names
        return ImportIndex(
            MappingProxyType({name: target for name, target in by_name.items() if name not in shadows}),
            self.context.module_imports.shadowed_names | shadows,
        )

    def _parameter_bindings(
        self, function: _Function, parameters: list[ast.arg], before_input: str | None
    ) -> dict[str, _Value]:
        bindings: dict[str, _Value] = {}
        receiver = self._receiver(function, parameters)
        for parameter in parameters:
            shape = self.models.shape(parameter.annotation, blocked=self._blocked)
            if receiver is not None and parameter is parameters[0]:
                bindings[parameter.arg] = receiver
            elif _contains_model(shape) or parameter.arg == before_input:
                bindings[parameter.arg] = _Value(shape, borrowed=True, shared_children=True)
        return bindings

    def _receiver(self, function: _Function, parameters: list[ast.arg]) -> _Value | None:
        parent = self.context.parents.get(function)
        if not parameters or not isinstance(parent, ast.ClassDef):
            return None
        if any(
            isinstance(decorator, ast.Name) and decorator.id == "staticmethod" for decorator in function.decorator_list
        ):
            return None
        symbol = self.models.symbol(ast.Name(id=parent.name))
        return _Value(_Shape("model", symbol)) if symbol is not None and self.models.pydantic(symbol) else None

    def _validator_input(self, function: _Function) -> str | None:
        parent = self.context.parents.get(function)
        class_bindings: set[str] = scope_bound_names(parent.body) if isinstance(parent, ast.ClassDef) else set()
        if not any(
            isinstance(decorator, ast.Call)
            and not any(isinstance(node, ast.Name) and node.id in class_bindings for node in ast.walk(decorator.func))
            and self.context.module_imports.resolved_symbol(decorator.func, sources=_PYDANTIC)
            in {"model_validator", "field_validator"}
            and any(
                keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "before"
                for keyword in decorator.keywords
            )
            for decorator in function.decorator_list
        ):
            return None
        parameters = [*function.args.posonlyargs, *function.args.args]
        is_classmethod = any(
            isinstance(decorator, ast.Name) and decorator.id == "classmethod" for decorator in function.decorator_list
        )
        offset = int(is_classmethod or bool(parameters and parameters[0].arg == "cls"))
        return parameters[offset].arg if len(parameters) > offset else None

    def _value(self, node: ast.expr, bindings: Mapping[str, _Value]) -> _Value | None:
        match node:
            case ast.Name(id=name):
                return bindings.get(name)
            case ast.Attribute():
                return self._member_value(node, bindings)
            case ast.Subscript():
                return self._item_value(node, bindings)
            case ast.Call():
                return self._call_value(node, bindings)
            case ast.Dict():
                return self._dict_value(node, bindings)
            case ast.List() | ast.Set() | ast.Tuple():
                return self._collection_value(node, bindings)
            case _:
                return None

    def _member_value(self, node: ast.Attribute, bindings: Mapping[str, _Value]) -> _Value | None:
        owner = self._value(node.value, bindings)
        if owner is None or owner.shape.model is None:
            return None
        field = self.models.field(owner.shape.model, node.attr)
        if field is None:
            return None
        return dict(owner.fields).get(
            node.attr, _Value(field, owner.borrowed or owner.shared_children, owner.borrowed or owner.shared_children)
        )

    def _item_value(self, node: ast.Subscript, bindings: Mapping[str, _Value]) -> _Value | None:
        owner = self._value(node.value, bindings)
        if owner is None:
            return None
        if isinstance(node.slice, ast.Slice):
            return self._shallow(owner) if owner.shape.kind in {"list", "tuple", "sequence"} else None
        if owner.shape.kind not in {"list", "sequence", "dict", "mapping", "tuple", "unknown"}:
            return None
        if owner.element is not None:
            return owner.element
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            field = dict(owner.fields).get(node.slice.value)
            if field is not None:
                return field
        return _Value(
            owner.shape.element or _Shape(),
            owner.borrowed or owner.shared_children,
            owner.borrowed or owner.shared_children,
        )

    def _collection_value(self, node: ast.List | ast.Set | ast.Tuple, bindings: Mapping[str, _Value]) -> _Value:
        values = [self._value(item, bindings) for item in node.elts]
        elements = [value.shape for value in values if value is not None]
        shape = _Shape()
        if elements and len(elements) == len(values) and all(item == elements[0] for item in elements):
            shape = elements[0]
        kind = "list" if isinstance(node, ast.List) else "set" if isinstance(node, ast.Set) else "tuple"
        element = values[0] if values and all(value == values[0] for value in values) else None
        return _Value(_Shape(kind, element=shape), element=element or _Value(_Shape()))

    @staticmethod
    def _shallow(value: _Value) -> _Value:
        return replace(value, borrowed=False, shared_children=value.borrowed or value.shared_children)

    def _call_value(self, node: ast.Call, bindings: Mapping[str, _Value]) -> _Value | None:
        if self._imports.resolves(node.func, sources=_TYPING, symbol="cast") and len(node.args) == _TWO_ARGUMENTS:
            value = self._value(node.args[1], bindings)
            return (
                replace(value, shape=self.models.shape(node.args[0], blocked=self._blocked))
                if value is not None
                else None
            )
        kind = _container_kind(node.func, self._imports)
        if kind in {"list", "dict", "set", "tuple"}:
            if node.keywords:
                return None
            value = self._value(node.args[0], bindings) if len(node.args) == 1 else None
            return (
                replace(self._shallow(value), shape=_Shape(kind, element=value.shape.element))
                if value is not None
                else _Value(_Shape(kind))
            )
        constructor = self._model_constructor(node)
        if constructor is not None:
            return constructor
        if not isinstance(node.func, ast.Attribute):
            return None
        owner = self._value(node.func.value, bindings)
        if owner is None:
            return None
        if (
            node.func.attr == "copy"
            and owner.shape.kind in {"list", "dict", "set"}
            and not node.args
            and not node.keywords
        ):
            return self._shallow(owner)
        return self._model_copy(node, owner, bindings)

    def _model_constructor(self, node: ast.Call) -> _Value | None:
        symbol = self.models.symbol(node.func)
        if symbol is None or not self.models.pydantic(symbol):
            return None
        if any(isinstance(name, ast.Name) and name.id in self._blocked for name in ast.walk(node.func)):
            return None
        return _Value(_Shape("model", symbol))

    def _model_copy(self, node: ast.Call, owner: _Value, bindings: Mapping[str, _Value]) -> _Value | None:
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "model_copy":
            return None
        if owner.shape.model is None or not self.models.standard_copy(owner.shape.model):
            return None
        if node.args or any(keyword.arg not in {"update", "deep"} for keyword in node.keywords):
            return None
        result = self._shallow(owner)
        for keyword in node.keywords:
            if keyword.arg == "deep":
                if not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False):
                    return None
            elif not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None):
                result = self._copy_updates(keyword.value, result, bindings)
                if result is None:
                    return None
        return result

    def _copy_updates(self, update: ast.expr, result: _Value, bindings: Mapping[str, _Value]) -> _Value | None:
        if not isinstance(update, ast.Dict):
            return None
        fields = dict(result.fields)
        for key, expression in zip(update.keys, update.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return None
            fields[key.value] = self._value(expression, bindings) or _Value(_Shape())
        return replace(result, fields=tuple(fields.items()))

    def _dict_value(self, node: ast.Dict, bindings: Mapping[str, _Value]) -> _Value:
        fields: dict[str, _Value] = {}
        shared = False
        element = None
        for key, expression in zip(node.keys, node.values, strict=True):
            value = self._value(expression, bindings)
            if key is None:
                fields.clear()
                if value is not None:
                    shared |= value.borrowed or value.shared_children
                    element = value.shape.element
                    fields.update(value.fields)
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                fields[key.value] = value or _Value(_Shape())
        return _Value(_Shape("dict", element=element), shared_children=shared, fields=tuple(fields.items()))

    def _write(self, target: ast.expr, bindings: Mapping[str, _Value]) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._write(item, bindings)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            owner = self._value(target.value, bindings)
            if (
                owner is not None
                and owner.borrowed
                and (
                    isinstance(target, ast.Subscript)
                    or (owner.shape.model is not None and self.models.field(owner.shape.model, target.attr) is not None)
                )
            ):
                self.mutations.append(Mutation(target, self._before))

    def _expression(self, node: ast.AST, bindings: dict[str, _Value]) -> None:
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.NamedExpr):
            self._expression(node.value, bindings)
            self._bind(node.target, self._value(node.value, bindings), bindings)
            return
        if isinstance(node, ast.Call) and self._mutator_call(node, bindings):
            self.mutations.append(Mutation(node, self._before))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self._comprehension(node, bindings)
            return
        for child in ast.iter_child_nodes(node):
            self._expression(child, bindings)

    def _mutator_call(self, node: ast.Call, bindings: Mapping[str, _Value]) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        owner = self._value(node.func.value, bindings)
        methods = {"list": _LIST_MUTATORS, "dict": _DICT_MUTATORS, "set": _SET_MUTATORS}
        return owner is not None and owner.borrowed and node.func.attr in methods.get(owner.shape.kind, frozenset())

    def _comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp, bindings: Mapping[str, _Value]
    ) -> None:
        local = dict(bindings)
        for generator in node.generators:
            self._expression(generator.iter, local)
            self._bind(generator.target, self._iter_element(generator.iter, local), local)
            for condition in generator.ifs:
                self._expression(condition, local)
        if isinstance(node, ast.DictComp):
            self._expression(node.key, local)
            self._expression(node.value, local)
        else:
            self._expression(node.elt, local)

    def _iter_element(self, expression: ast.expr, bindings: Mapping[str, _Value]) -> _Value | None:
        owner = self._value(expression, bindings)
        if owner is None or owner.shape.element is None or owner.shape.kind in {"dict", "mapping"}:
            return None
        if owner.element is not None:
            return owner.element
        return _Value(
            owner.shape.element, owner.borrowed or owner.shared_children, owner.borrowed or owner.shared_children
        )

    def _bind(self, target: ast.expr, value: _Value | None, bindings: dict[str, _Value]) -> None:
        match target:
            case ast.Name(id=name):
                if value is None:
                    bindings.pop(name, None)
                else:
                    bindings[name] = value
            case ast.Tuple(elts=items) | ast.List(elts=items):
                for item in items:
                    self._bind(item, None, bindings)
            case ast.Attribute() | ast.Subscript():
                self._bind_owned_field(target, value, bindings)
            case _:
                pass

    def _bind_owned_field(
        self, target: ast.Attribute | ast.Subscript, value: _Value | None, bindings: dict[str, _Value]
    ) -> None:
        if not isinstance(target.value, ast.Name):
            return
        owner = bindings.get(target.value.id)
        if owner is None or owner.borrowed:
            return
        match target:
            case ast.Attribute(attr=key):
                pass
            case ast.Subscript(slice=ast.Constant(value=str() as key)):
                pass
            case _:
                return
        fields = dict(owner.fields)
        fields[key] = value or _Value(_Shape())
        updated = replace(owner, fields=tuple(fields.items()))
        for name, binding in tuple(bindings.items()):
            if binding is owner:
                bindings[name] = updated

    @staticmethod
    def _join(branches: list[dict[str, _Value]], bindings: dict[str, _Value]) -> None:
        bindings.clear()
        if branches:
            bindings.update(
                {
                    name: value
                    for name, value in branches[0].items()
                    if all(branch.get(name) == value for branch in branches[1:])
                }
            )

    def _scan(self, statements: list[ast.stmt], bindings: dict[str, _Value]) -> None:
        for statement in statements:
            if self._statement(statement, bindings):
                return

    def _statement(self, statement: ast.stmt, bindings: dict[str, _Value]) -> bool:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                bindings.pop(statement.name, None)
            case ast.Assign() | ast.AnnAssign():
                self._assignment(statement, bindings)
            case ast.AugAssign():
                self._augmented(statement, bindings)
            case ast.Delete(targets=targets):
                for target in targets:
                    self._write(target, bindings)
                    self._bind(target, None, bindings)
            case ast.If():
                self._branches(statement, bindings)
            case ast.For() | ast.AsyncFor():
                self._for(statement, bindings)
            case ast.Expr(value=ast.Call() as call):
                if self._discarded_copy(call, bindings):
                    self.discarded.append(call)
                self._expression(call, bindings)
            case ast.With() | ast.AsyncWith():
                self._with(statement, bindings)
            case ast.Try() | ast.TryStar():
                self._try(statement, bindings)
            case ast.While():
                self._while(statement, bindings)
            case ast.Import() | ast.ImportFrom():
                for name in scope_bound_names([statement]):
                    bindings.pop(name, None)
            case ast.Return() | ast.Raise():
                self._expression(statement, bindings)
                return True
            case _:
                for name in scope_bound_names([statement]):
                    bindings.pop(name, None)
                self._expression(statement, bindings)
        return False

    def _assignment(self, statement: ast.Assign | ast.AnnAssign, bindings: dict[str, _Value]) -> None:
        if statement.value is None:
            return
        self._expression(statement.value, bindings)
        value = self._value(statement.value, bindings)
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            self._write(target, bindings)
            self._bind(target, value, bindings)

    def _branches(self, statement: ast.If, bindings: dict[str, _Value]) -> None:
        self._expression(statement.test, bindings)
        branches: list[dict[str, _Value]] = []
        for positive, block in ((True, statement.body), (False, statement.orelse)):
            branch = dict(bindings)
            self._refine(statement.test, branch, positive=positive)
            self._scan(block, branch)
            if not block or not isinstance(block[-1], (ast.Return, ast.Raise)):
                branches.append(branch)
        self._join(branches, bindings)

    def _for(self, statement: ast.For | ast.AsyncFor, bindings: dict[str, _Value]) -> None:
        self._expression(statement.iter, bindings)
        branch = dict(bindings)
        self._bind(statement.target, self._iter_element(statement.iter, bindings), branch)
        self._scan(statement.body, branch)
        self._join([dict(bindings), branch], bindings)
        self._scan(statement.orelse, bindings)

    def _with(self, statement: ast.With | ast.AsyncWith, bindings: dict[str, _Value]) -> None:
        for item in statement.items:
            self._expression(item.context_expr, bindings)
            if item.optional_vars is not None:
                self._bind(item.optional_vars, None, bindings)
        self._scan(statement.body, bindings)

    def _try(self, statement: ast.Try | ast.TryStar, bindings: dict[str, _Value]) -> None:
        branch = dict(bindings)
        self._scan(statement.body, branch)
        self._scan(statement.orelse, branch)
        branches = [branch]
        uncertain = scope_bound_names(statement.body)
        for handler in statement.handlers:
            branch = {name: value for name, value in bindings.items() if name not in uncertain}
            if handler.name is not None:
                branch.pop(handler.name, None)
            self._scan(handler.body, branch)
            branches.append(branch)
        self._join(branches, bindings)
        self._scan(statement.finalbody, bindings)

    def _while(self, statement: ast.While, bindings: dict[str, _Value]) -> None:
        self._expression(statement.test, bindings)
        branch = dict(bindings)
        self._scan(statement.body, branch)
        self._join([dict(bindings), branch], bindings)
        self._scan(statement.orelse, bindings)

    def _discarded_copy(self, node: ast.Call, bindings: Mapping[str, _Value]) -> bool:
        if self._expected_exception(node):
            return False
        if self._imports.resolves(node.func, sources=frozenset({"copy", "dataclasses"}), symbol="replace"):
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "model_copy":
            owner = self._value(node.func.value, bindings)
            return owner is not None and owner.shape.model is not None and self.models.standard_copy(owner.shape.model)
        return False

    def _expected_exception(self, node: ast.Call) -> bool:
        parent = self.context.parents.get(node)
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(parent, ast.With) and any(
                isinstance(item.context_expr, ast.Call)
                and self._imports.resolves(item.context_expr.func, sources=frozenset({"pytest"}), symbol="raises")
                for item in parent.items
            ):
                return True
            parent = self.context.parents.get(parent)
        return False

    def _augmented(self, statement: ast.AugAssign, bindings: dict[str, _Value]) -> None:
        target = statement.target
        self._write(target, bindings)
        self._expression(statement.value, bindings)
        child = self._value(target, bindings)
        parent = self._value(target.value, bindings) if isinstance(target, (ast.Attribute, ast.Subscript)) else None
        if (
            child is not None
            and child.borrowed
            and child.shape.kind in {"list", "dict", "set"}
            and (parent is None or not parent.borrowed)
        ):
            self.mutations.append(Mutation(target, self._before))
        self._bind(target, None, bindings)

    def _refine(self, test: ast.expr, bindings: dict[str, _Value], *, positive: bool) -> None:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            self._refine(test.operand, bindings, positive=not positive)
            return
        if not positive or not isinstance(test, ast.Call) or len(test.args) != _TWO_ARGUMENTS:
            return
        if not (
            isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"
            and self._imports.builtin_is_unshadowed("isinstance")
        ):
            return
        if isinstance(test.args[0], ast.Name):
            name = test.args[0].id
            kind = _container_kind(test.args[1], self._imports)
            if kind is not None and name in bindings:
                bindings[name] = replace(bindings[name], shape=_Shape(kind, element=bindings[name].shape.element))
