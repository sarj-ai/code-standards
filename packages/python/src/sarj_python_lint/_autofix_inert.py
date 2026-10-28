from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Final

    from sarj_python_lint._file_context import PythonFileContext


class _Kind(StrEnum):
    UNKNOWN = "unknown"
    UNBOUND = "unbound-local"
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    COMPLEX = "complex"
    STR = "str"
    BYTES = "bytes"
    LIST = "list"
    TUPLE = "tuple"
    SET = "set"
    DICT = "dict"
    FUNCTION = "function"
    TYPE = "builtin-type"
    BYTES_TYPE = "builtin-bytes"
    LEN = "builtin-len"
    DICT_TYPE = "builtin-dict"
    STR_TYPE = "builtin-str"
    ISINSTANCE = "builtin-isinstance"


_PRIMITIVES = frozenset({_Kind.NONE, _Kind.BOOL, _Kind.INT, _Kind.FLOAT, _Kind.COMPLEX, _Kind.STR, _Kind.BYTES})
_CONTAINERS = frozenset({_Kind.LIST, _Kind.TUPLE, _Kind.SET, _Kind.DICT})
_STRING_METHODS: Final[Mapping[str, Callable[[str], str]]] = {
    "strip": str.strip,
    "lower": str.lower,
    "upper": str.upper,
    "lstrip": str.lstrip,
    "rstrip": str.rstrip,
    "casefold": str.casefold,
    "capitalize": str.capitalize,
    "title": str.title,
    "swapcase": str.swapcase,
    "expandtabs": str.expandtabs,
}
_BUILTINS: Final[dict[str, _Kind]] = {
    "type": _Kind.TYPE,
    "bytes": _Kind.BYTES_TYPE,
    "len": _Kind.LEN,
    "dict": _Kind.DICT_TYPE,
    "str": _Kind.STR_TYPE,
    "isinstance": _Kind.ISINSTANCE,
}
_PAIR_SIZE = 2
_PRIMITIVE_CLASSES: Final[dict[str, type[object]]] = {
    "bool": bool,
    "int": int,
    "float": float,
    "complex": complex,
    "str": str,
    "bytes": bytes,
}


@dataclass(slots=True)
class _Value:
    kind: _Kind
    literal: bool | int | float | complex | str | bytes | None = None
    known: bool = False
    items: list[_Value] = field(default_factory=list)
    function: _Function | None = None


@dataclass(slots=True)
class _Function:
    node: ast.FunctionDef
    closure: dict[str, _Value]
    defaults: dict[str, _Value]


@dataclass(frozen=True, slots=True)
class _Result:
    returned: bool
    value: _Value


class _UnsafeError(Exception):
    pass


def _constant(value: object) -> _Value:
    kinds: Mapping[type[object], _Kind] = {
        type(None): _Kind.NONE,
        bool: _Kind.BOOL,
        int: _Kind.INT,
        float: _Kind.FLOAT,
        complex: _Kind.COMPLEX,
        str: _Kind.STR,
        bytes: _Kind.BYTES,
    }
    kind = kinds.get(type(value))
    if kind is None or not isinstance(value, bool | int | float | complex | str | bytes | None):
        raise _UnsafeError
    return _Value(kind, value, known=True)


def inert_private_scope(owner: ast.FunctionDef, context: PythonFileContext) -> bool:
    containing = [owner]
    parent = context.parents.get(owner)
    while parent is not None:
        if isinstance(parent, (ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return False
        if isinstance(parent, ast.FunctionDef):
            containing.append(parent)
        parent = context.parents.get(parent)
    analyzer = _Analysis(context, containing[-1])
    try:
        analyzer.check()
    except _UnsafeError:
        return False
    return True


@final
class _Analysis:
    def __init__(self, context: PythonFileContext, outer: ast.FunctionDef) -> None:
        self.context = context
        self.outer = outer
        self.provenance = ResourceProvenance(context)
        self.active: set[ast.FunctionDef] = set()
        self.iterating: set[int] = set()

    def check(self) -> None:
        if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(self.outer)):
            raise _UnsafeError
        defaults = self._defaults(self.outer, {})
        function = _Function(self.outer, {}, defaults)
        arguments = self.outer.args
        names = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        values = {argument.arg: _Value(_Kind.UNKNOWN) for argument in names}
        if arguments.vararg is not None:
            values[arguments.vararg.arg] = _Value(_Kind.UNKNOWN)
        if arguments.kwarg is not None:
            values[arguments.kwarg.arg] = _Value(_Kind.UNKNOWN)
        self._execute(function, values)

    def _defaults(self, function: ast.FunctionDef, environment: dict[str, _Value]) -> dict[str, _Value]:
        if function.decorator_list or function.type_params:
            raise _UnsafeError
        positional = [*function.args.posonlyargs, *function.args.args]
        defaults = {
            argument.arg: self._expression(value, environment)
            for argument, value in zip(positional[-len(function.args.defaults) :], function.args.defaults, strict=False)
        }
        for argument, value in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True):
            if value is not None:
                defaults[argument.arg] = self._expression(value, environment)
        return defaults

    def _execute(self, function: _Function, supplied: dict[str, _Value]) -> _Value:
        if function.node in self.active:
            raise _UnsafeError
        self.active.add(function.node)
        local_names = self.provenance.bindings.get(function.node, {})
        environment = {name: value for name, value in function.closure.items() if name not in local_names}
        environment.update(function.defaults)
        environment.update(supplied)
        try:
            if self._bytes_comparison(
                function.node, environment, frozenset(function.defaults.keys() - supplied.keys())
            ):
                return _Value(_Kind.BOOL)
            return self._body(function.node.body, environment).value
        finally:
            self.active.remove(function.node)

    def _body(self, statements: list[ast.stmt], environment: dict[str, _Value]) -> _Result:
        for statement in statements:
            result = self._statement(statement, environment)
            if result.returned:
                return result
        return _Result(returned=False, value=_constant(None))

    def _statement(self, statement: ast.stmt, environment: dict[str, _Value]) -> _Result:
        match statement:
            case ast.FunctionDef():
                defaults = self._defaults(statement, environment)
                self._store(
                    statement.name,
                    _Value(_Kind.FUNCTION, function=_Function(statement, environment, defaults)),
                    environment,
                )
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                self._store(name, self._expression(value, environment), environment)
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                if value is not None:
                    self._store(name, self._expression(value, environment), environment)
            case ast.AugAssign(target=ast.Name(id=name), op=ast.Add(), value=value):
                self._store(
                    name,
                    self._addition(
                        self._name(name, statement.target, environment), self._expression(value, environment)
                    ),
                    environment,
                )
            case ast.Delete(targets=[ast.Name(id=name)]):
                previous = environment.get(name)
                if previous is None or previous.kind is not _Kind.NONE:
                    raise _UnsafeError
                environment[name] = _Value(_Kind.UNBOUND)
            case ast.Expr(value=value):
                self._expression(value, environment)
            case ast.Return(value=value):
                return _Result(
                    returned=True, value=_constant(None) if value is None else self._expression(value, environment)
                )
            case ast.Pass():
                pass
            case ast.For(target=ast.Name(id=name), iter=iterable, body=body, orelse=[]):
                return self._loop(name, iterable, body, environment)
            case ast.If(test=test, body=body, orelse=otherwise):
                selected = body if self._truth(self._expression(test, environment)) else otherwise
                return self._body(selected, environment)
            case ast.Match():
                return self._match(statement, environment)
            case _:
                raise _UnsafeError
        return _Result(returned=False, value=_constant(None))

    def _store(self, name: str, value: _Value, environment: dict[str, _Value]) -> None:
        previous = environment.get(name)
        if previous is not None and self._retains_unknown(previous, set()):
            raise _UnsafeError
        environment[name] = value

    def _retains_unknown(self, value: _Value, seen: set[int]) -> bool:
        if id(value) in seen:
            return False
        seen.add(id(value))
        if value.kind is _Kind.UNKNOWN:
            return True
        children = list(value.items)
        if value.function is not None:
            children.extend(value.function.defaults.values())
            children.extend(value.function.closure.values())
        return any(self._retains_unknown(child, seen) for child in children)

    def _loop(self, name: str, iterable: ast.expr, body: list[ast.stmt], environment: dict[str, _Value]) -> _Result:
        value = self._expression(iterable, environment)
        if id(value) in self.iterating:
            raise _UnsafeError
        self.iterating.add(id(value))
        try:
            for item in self._iteration(value):
                self._store(name, item, environment)
                result = self._body(body, environment)
                if result.returned:
                    return result
            return _Result(returned=False, value=_constant(None))
        finally:
            self.iterating.remove(id(value))

    def _expression(self, node: ast.expr, environment: dict[str, _Value]) -> _Value:
        match node:
            case ast.Constant(value=value):
                return _constant(value)
            case ast.Name(id=name):
                return self._name(name, node, environment)
            case ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements):
                return self._sequence(node, elements, environment)
            case ast.Dict(keys=keys, values=values):
                return self._mapping(keys, values, environment)
            case ast.Call():
                return self._call(node, environment)
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                return self._addition(self._expression(left, environment), self._expression(right, environment))
            case ast.ListComp():
                return self._comprehension(node, environment)
            case ast.Compare():
                return self._comparison(node, environment)
            case ast.UnaryOp(op=ast.Not(), operand=value):
                return _constant(not self._truth(self._expression(value, environment)))
            case _:
                raise _UnsafeError

    def _sequence(
        self, node: ast.Tuple | ast.List | ast.Set, elements: list[ast.expr], environment: dict[str, _Value]
    ) -> _Value:
        values = [self._expression(element, environment) for element in elements]
        kinds = {ast.Tuple: _Kind.TUPLE, ast.List: _Kind.LIST, ast.Set: _Kind.SET}
        kind = kinds[type(node)]
        if kind is _Kind.SET:
            if any(value.kind not in _PRIMITIVES or not value.known for value in values):
                raise _UnsafeError
            values = [_constant(value) for value in {item.literal for item in values}]
        return _Value(kind, items=values)

    def _mapping(self, keys: list[ast.expr | None], values: list[ast.expr], environment: dict[str, _Value]) -> _Value:
        items: dict[object, _Value] = {}
        for key, expression in zip(keys, values, strict=True):
            if key is None:
                raise _UnsafeError
            value = self._expression(key, environment)
            if value.kind not in _PRIMITIVES or not value.known:
                raise _UnsafeError
            items[value.literal] = self._expression(expression, environment)
        return _Value(_Kind.DICT, items=list(items.values()))

    def _comparison(self, node: ast.Compare, environment: dict[str, _Value]) -> _Value:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise _UnsafeError
        first = self._expression(node.left, environment)
        second = self._expression(node.comparators[0], environment)
        operator = node.ops[0]
        if isinstance(operator, ast.Is | ast.IsNot):
            if first.kind not in {_Kind.NONE, _Kind.BOOL} or second.kind not in {_Kind.NONE, _Kind.BOOL}:
                raise _UnsafeError
            if not first.known or not second.known:
                raise _UnsafeError
            equal = first.literal is second.literal
            return _constant(not equal if isinstance(operator, ast.IsNot) else equal)
        if not isinstance(operator, ast.Eq | ast.NotEq):
            raise _UnsafeError
        if first.kind not in _PRIMITIVES or second.kind not in _PRIMITIVES:
            raise _UnsafeError
        if first.known and second.known:
            equal = first.literal == second.literal
            return _constant(not equal if isinstance(operator, ast.NotEq) else equal)
        return _Value(_Kind.BOOL)

    def _name(self, name: str, node: ast.AST, environment: dict[str, _Value]) -> _Value:
        if name in environment:
            value = environment[name]
            if value.kind is _Kind.UNBOUND:
                raise _UnsafeError
            return value
        if (
            name in _BUILTINS
            and self.context.imports.builtin_is_unshadowed(name)
            and self.provenance.builtin_namespace_untouched
        ):
            return _Value(_BUILTINS[name])
        binding = self.provenance.runtime_binding(name, node)
        statement = self.context.parents.get(binding) if binding is not None else None
        if isinstance(binding, ast.FunctionDef) and self.context.parents.get(binding) is self.context.tree:
            statement = binding
        if isinstance(statement, ast.AnnAssign) and statement.value is None:
            raise _UnsafeError
        if (
            isinstance(statement, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef))
            and statement.lineno < self.outer.lineno
            and self.context.parents.get(statement) is self.context.tree
        ):
            return _Value(_Kind.UNKNOWN)
        raise _UnsafeError

    def _call(self, call: ast.Call, environment: dict[str, _Value]) -> _Value:
        if any(isinstance(value, ast.Starred) for value in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            raise _UnsafeError
        if isinstance(call.func, ast.Attribute):
            return self._method(call, call.func, environment)
        callee = self._expression(call.func, environment)
        if callee.kind is _Kind.ISINSTANCE:
            return self._isinstance(call, environment)
        values = [self._expression(value, environment) for value in call.args]
        keywords = {
            keyword.arg: self._expression(keyword.value, environment)
            for keyword in call.keywords
            if keyword.arg is not None
        }
        if len(keywords) != len(call.keywords):
            raise _UnsafeError
        if callee.kind is _Kind.FUNCTION and callee.function is not None:
            return self._invoke(callee.function, values, keywords)
        if callee.kind is _Kind.DICT_TYPE and not values:
            return _Value(_Kind.DICT, items=list(keywords.values()))
        if callee.kind is _Kind.LEN and len(values) == 1 and not keywords:
            return self._length(values[0])
        raise _UnsafeError

    def _isinstance(self, call: ast.Call, environment: dict[str, _Value]) -> _Value:
        if len(call.args) != _PAIR_SIZE or call.keywords:
            raise _UnsafeError
        value = self._expression(call.args[0], environment)
        class_name = call.args[1]
        if not isinstance(class_name, ast.Name) or class_name.id in environment:
            raise _UnsafeError
        if (
            class_name.id not in _PRIMITIVE_CLASSES
            or not self.context.imports.builtin_is_unshadowed(class_name.id)
            or not self.provenance.builtin_namespace_untouched
        ):
            raise _UnsafeError
        if value.kind not in _PRIMITIVES or not value.known:
            raise _UnsafeError
        return _constant(isinstance(value.literal, _PRIMITIVE_CLASSES[class_name.id]))

    def _length(self, value: _Value) -> _Value:
        if value.kind in _CONTAINERS:
            return _constant(len(value.items))
        if value.kind in {_Kind.STR, _Kind.BYTES} and value.known and isinstance(value.literal, str | bytes):
            return _constant(len(value.literal))
        raise _UnsafeError

    def _invoke(self, function: _Function, values: list[_Value], keywords: dict[str, _Value]) -> _Value:
        arguments = function.node.args
        positional = [*arguments.posonlyargs, *arguments.args]
        supplied = {argument.arg: value for argument, value in zip(positional, values, strict=False)}
        if len(values) > len(positional):
            raise _UnsafeError
        allowed = {argument.arg for argument in (*arguments.args, *arguments.kwonlyargs)}
        if any(name not in allowed or name in supplied for name in keywords):
            raise _UnsafeError
        supplied.update(keywords)
        required = {argument.arg for argument in positional[: len(positional) - len(arguments.defaults)]}
        required.update(
            argument.arg
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
            if default is None
        )
        if not required <= supplied.keys() or arguments.vararg is not None:
            raise _UnsafeError
        if arguments.kwarg is not None:
            supplied[arguments.kwarg.arg] = _Value(_Kind.DICT)
        return self._execute(function, supplied)

    def _method(self, call: ast.Call, method: ast.Attribute, environment: dict[str, _Value]) -> _Value:
        receiver = self._expression(method.value, environment)
        if receiver.kind is _Kind.STR and receiver.known and isinstance(receiver.literal, str):
            return self._string_method(call, method.attr, receiver.literal)
        if receiver.kind is _Kind.LIST and method.attr == "append" and len(call.args) == 1 and not call.keywords:
            if id(receiver) in self.iterating:
                raise _UnsafeError
            receiver.items.append(self._expression(call.args[0], environment))
            return _constant(None)
        raise _UnsafeError

    def _string_method(self, call: ast.Call, name: str, value: str) -> _Value:
        if name not in _STRING_METHODS or call.args or call.keywords:
            raise _UnsafeError
        return _constant(_STRING_METHODS[name](value))

    def _addition(self, first: _Value, second: _Value) -> _Value:
        if first.kind is not second.kind or first.kind not in {_Kind.STR, _Kind.BYTES, _Kind.INT}:
            raise _UnsafeError
        if first.known and second.known:
            if isinstance(first.literal, str) and isinstance(second.literal, str):
                return _constant(first.literal + second.literal)
            if isinstance(first.literal, bytes) and isinstance(second.literal, bytes):
                return _constant(first.literal + second.literal)
            if isinstance(first.literal, int) and isinstance(second.literal, int):
                return _constant(first.literal + second.literal)
        return _Value(first.kind)

    def _iteration(self, value: _Value) -> list[_Value]:
        if value.kind in {_Kind.TUPLE, _Kind.LIST}:
            return value.items
        if value.kind is _Kind.STR and value.known and isinstance(value.literal, str):
            return [_constant(character) for character in value.literal]
        raise _UnsafeError

    def _truth(self, value: _Value) -> bool:
        if value.kind in _CONTAINERS:
            return bool(value.items)
        if value.kind in _PRIMITIVES and value.known:
            return bool(value.literal)
        raise _UnsafeError

    def _comprehension(self, node: ast.ListComp, environment: dict[str, _Value]) -> _Value:
        if len(node.generators) != 1:
            raise _UnsafeError
        generator = node.generators[0]
        if generator.is_async or not isinstance(generator.target, ast.Name):
            raise _UnsafeError
        result: list[_Value] = []
        iterable = self._expression(generator.iter, environment)
        if id(iterable) in self.iterating:
            raise _UnsafeError
        self.iterating.add(id(iterable))
        scope = {name: value for name, value in environment.items() if name != generator.target.id}
        try:
            for value in self._iteration(iterable):
                self._store(generator.target.id, value, scope)
                if all(self._truth(self._expression(test, scope)) for test in generator.ifs):
                    result.append(self._expression(node.elt, scope))
        finally:
            self.iterating.remove(id(iterable))
        return _Value(_Kind.LIST, items=result)

    def _match(self, statement: ast.Match, environment: dict[str, _Value]) -> _Result:
        subject = self._expression(statement.subject, environment)
        if subject.kind not in _PRIMITIVES or not subject.known:
            raise _UnsafeError
        for case in statement.cases:
            if case.guard is not None:
                raise _UnsafeError
            pattern = case.pattern
            if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Constant):
                selected = subject.literal == pattern.value.value
            elif isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None:
                selected = True
            else:
                raise _UnsafeError
            if selected:
                return self._body(case.body, environment)
        return _Result(returned=False, value=_constant(None))

    def _bytes_comparison(
        self, function: ast.FunctionDef, environment: dict[str, _Value], omitted: frozenset[str]
    ) -> bool:
        if len(function.body) != _PAIR_SIZE:
            return False
        guard, fallback = function.body
        if not isinstance(guard, ast.If) or guard.orelse or len(guard.body) != 1:
            return False
        if (
            not isinstance(fallback, ast.Return)
            or not isinstance(fallback.value, ast.Constant)
            or fallback.value.value is not False
        ):
            return False
        test = guard.test
        if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.And) or len(test.values) != _PAIR_SIZE:
            return False
        names = {self._bytes_type_test(condition, environment, omitted) for condition in test.values}
        return None not in names and self._guarded_equality(guard.body[0], names)

    def _bytes_type_test(
        self, condition: ast.expr, environment: dict[str, _Value], omitted: frozenset[str]
    ) -> str | None:
        match condition:
            case ast.Compare(
                left=ast.Call(func=ast.Name(id=callee), args=[ast.Name(id=value)], keywords=[]),
                ops=[ast.Is()],
                comparators=[ast.Name(id=kind)],
            ):
                if callee not in omitted or kind not in omitted or value not in environment:
                    return None
                if environment.get(callee, _Value(_Kind.UNKNOWN)).kind is not _Kind.TYPE:
                    return None
                if environment.get(kind, _Value(_Kind.UNKNOWN)).kind is not _Kind.BYTES_TYPE:
                    return None
                return value
            case _:
                return None

    def _guarded_equality(self, returned: ast.stmt, names: set[str | None]) -> bool:
        if not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Compare):
            return False
        comparison = returned.value
        if (
            len(names) != _PAIR_SIZE
            or len(comparison.ops) != 1
            or not isinstance(comparison.ops[0], (ast.Eq, ast.NotEq))
            or len(comparison.comparators) != 1
        ):
            return False
        operands = (comparison.left, comparison.comparators[0])
        if not isinstance(operands[0], ast.Name) or not isinstance(operands[1], ast.Name):
            return False
        return {operands[0].id, operands[1].id} == names
