from __future__ import annotations

import ast
from collections import defaultdict
from typing import TYPE_CHECKING, NamedTuple, final

from sarj_python_lint.rules._test_composition import call_arguments, direct_nodes


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules.require_pydantic_for_mapping_shape import MappingShapeFacts


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MAX_DEPTH = 12
_MAX_ESCAPE_NODES = 128
_PAIR_ARITY = 2
_REFLECTION_INPUTS = frozenset({"sys.getrefcount"})
_FUNCTION_TYPES = frozenset({"types.FunctionType", "types.LambdaType"})
_PROTOCOLS = frozenset({"typing.Protocol", "typing_extensions.Protocol"})
_RUNTIME_PROTOCOLS = frozenset({"typing.runtime_checkable", "typing_extensions.runtime_checkable"})


class SourcePosition(NamedTuple):
    line: int
    column: int


@final
class NativeObjectContracts:
    def __init__(self, context: PythonFileContext, facts: MappingShapeFacts) -> None:
        self.context = context
        self.facts = facts
        self.namespaces: dict[_Function, _NamespaceFlow] = {}
        self.namespace_possible = "exec" in context.symbol_source or "eval" in context.symbol_source
        self.namespace_rebindings: dict[str, bool] = {}

    def namespace(self, function: _Function) -> _NamespaceFlow:
        if function not in self.namespaces:
            self.namespaces[function] = _NamespaceFlow(self, function)
        return self.namespaces[function]

    def property_result(self, function: _Function, annotation: ast.expr) -> bool:
        owner = self.context.parents.get(function)
        if not isinstance(owner, ast.ClassDef) or annotation is not function.returns:
            return False
        return (
            self._getter(function)
            and self._runtime_protocol(owner)
            and all(_stub(statement) for statement in function.body)
        )

    def _getter(self, function: _Function) -> bool:
        if not isinstance(function, ast.FunctionDef):
            return False
        positional = (*function.args.posonlyargs, *function.args.args)
        if len(positional) != 1 or function.args.kwonlyargs or function.args.vararg or function.args.kwarg:
            return False
        return len(function.decorator_list) == 1 and self.builtin(function.decorator_list[0], "property", function)

    def _runtime_protocol(self, owner: ast.ClassDef) -> bool:
        return any(self.qualified(base, owner) in _PROTOCOLS for base in owner.bases) and any(
            self.qualified(decorator, owner) in _RUNTIME_PROTOCOLS for decorator in owner.decorator_list
        )

    def arguments(self, call: ast.Call) -> tuple[ast.expr, ...]:
        if self._function_value(call.func):
            if any(isinstance(value, ast.Starred) for value in call.args) or any(
                keyword.arg is None for keyword in call.keywords
            ):
                return ()
            return (*call.args, *(keyword.value for keyword in call.keywords))
        if (
            self.qualified(call.func, call) in _REFLECTION_INPUTS
            and len(call.args) == 1
            and not call.keywords
            and not isinstance(call.args[0], ast.Starred)
        ):
            return (call.args[0],)
        return ()

    def output(self, value: ast.expr, function: _Function) -> bool:
        if isinstance(value, ast.Call) and self._function_value(value.func):
            return True
        if isinstance(value, ast.Call) and self.namespace(function).evaluates(value):
            return True
        if isinstance(value, ast.Attribute) and value.attr == "value" and self._constant(value.value):
            return True
        if isinstance(value, ast.Name) and self._constant_capture(value):
            return True
        return self.namespace(function).unknown_read(value)

    def _function_value(self, value: ast.expr) -> bool:
        if isinstance(value, ast.Call):
            return self.qualified(value.func, value) in _FUNCTION_TYPES
        if not isinstance(value, ast.Name) or value.id in self.facts.provenance.mutated:
            return False
        binding = self.facts.provenance.runtime_binding(value.id, value)
        if isinstance(binding, ast.arg) and binding.annotation is not None:
            annotation = self.context.annotation_semantics.parse(binding.annotation)
            return (
                annotation is not None
                and self.qualified(annotation, binding.annotation) in _FUNCTION_TYPES
                and not self.namespace_rebound(value.id)
            )
        if isinstance(binding, ast.Name):
            assigned = self.facts.provenance.assignment_value(binding, value)
            return (
                isinstance(assigned, ast.Call)
                and self.qualified(assigned.func, assigned) in _FUNCTION_TYPES
                and not self.namespace_rebound(value.id)
            )
        return False

    def _constant(self, value: ast.expr) -> bool:
        if isinstance(value, ast.Name):
            binding = self.facts.provenance.runtime_binding(value.id, value)
            if isinstance(binding, ast.arg) and binding.annotation is not None:
                annotation = self.context.annotation_semantics.parse(binding.annotation)
                if annotation is not None and self.qualified(annotation, binding.annotation) == "ast.Constant":
                    return True
        current: ast.AST = value
        while (parent := self.context.parents.get(current)) is not None:
            if (
                _accepted_branch(current, parent)
                and isinstance(parent, ast.If | ast.IfExp)
                and self._constant_test(parent.test, value)
            ):
                return True
            if isinstance(parent, ast.match_case) and self._constant_case(parent, value):
                return True
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
                break
            current = parent
        return False

    def _constant_test(self, test: ast.expr, value: ast.expr) -> bool:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return any(self._constant_test(member, value) for member in test.values)
        return (
            isinstance(test, ast.Call)
            and len(test.args) == _PAIR_ARITY
            and not test.keywords
            and self.facts.builtin(test.func, "isinstance", test)
            and self.qualified(test.args[1], test) == "ast.Constant"
            and self._same_value(test.args[0], value)
        )

    def _constant_case(self, case: ast.match_case, value: ast.expr) -> bool:
        owner = self.context.parents.get(case)
        return (
            isinstance(owner, ast.Match)
            and self._same_value(owner.subject, value)
            and isinstance(case.pattern, ast.MatchClass)
            and self.qualified(case.pattern.cls, case.pattern) == "ast.Constant"
        )

    def _constant_capture(self, value: ast.Name) -> bool:
        binding = self.facts.provenance.runtime_binding(value.id, value)
        if not isinstance(binding, ast.MatchAs) or binding.pattern is not None:
            return False
        parent = self.context.parents.get(binding)
        if not isinstance(parent, ast.MatchClass) or self.qualified(parent.cls, parent) != "ast.Constant":
            return False
        return any(
            attribute == "value" and pattern is binding
            for attribute, pattern in zip(parent.kwd_attrs, parent.kwd_patterns, strict=True)
        )

    def _same_value(self, left: ast.expr, right: ast.expr) -> bool:
        if isinstance(left, ast.Name) and isinstance(right, ast.Name):
            binding = self.facts.provenance.runtime_binding(left.id, left)
            return binding is not None and binding is self.facts.provenance.runtime_binding(right.id, right)
        return (
            isinstance(left, ast.Attribute)
            and isinstance(right, ast.Attribute)
            and left.attr == right.attr
            and self._same_value(left.value, right.value)
        )

    def builtin(self, node: ast.expr, name: str, at: ast.AST) -> bool:
        return not self.namespace_rebound(name) and (
            self.facts.builtin(node, name, at) or self.qualified(node, at) == f"builtins.{name}"
        )

    def qualified(self, node: ast.expr, at: ast.AST) -> str | None:
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and self.namespace_rebound(root.id):
            return None
        return self.facts.qualified(node, at)

    def namespace_rebound(self, name: str) -> bool:
        if name not in self.namespace_rebindings:
            self.namespace_rebindings[name] = any(
                isinstance(node.ctx, ast.Store | ast.Del)
                and self._native_namespace(node.value)
                and (not isinstance(node.slice, ast.Constant) or node.slice.value == name)
                for node in self.context.nodes(ast.Subscript)
            ) or any(self._namespace_method_rebinds(call, name) for call in self.context.nodes(ast.Call))
        return self.namespace_rebindings[name]

    def _namespace_method_rebinds(self, call: ast.Call, name: str) -> bool:
        if not isinstance(call.func, ast.Attribute) or not self._native_namespace(call.func.value):
            return False
        if call.func.attr in {"get", "keys", "values", "items", "copy", "__getitem__"}:
            return False
        if call.func.attr == "update":
            return any(keyword.arg is None or keyword.arg == name for keyword in call.keywords) or any(
                not isinstance(value, ast.Dict)
                or any(not isinstance(key, ast.Constant) or key.value == name for key in value.keys)
                for value in call.args
            )
        if call.func.attr in {"setdefault", "pop", "__setitem__", "__delitem__"} and call.args:
            key = call.args[0]
            return not isinstance(key, ast.Constant) or key.value == name
        return True

    def namespace_replaced(self, name: str) -> bool:
        replaced = any(
            isinstance(node.ctx, ast.Store)
            and self._native_namespace(node.value)
            and (not isinstance(node.slice, ast.Constant) or node.slice.value == name)
            for node in self.context.nodes(ast.Subscript)
        )
        return replaced or any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr not in {"clear", "pop", "popitem", "__delitem__"}
            and self._namespace_method_rebinds(call, name)
            for call in self.context.nodes(ast.Call)
        )

    def _native_namespace(self, node: ast.expr, *, depth: int = 0) -> bool:
        if depth >= _MAX_DEPTH:
            return False
        if isinstance(node, ast.Name):
            binding = self.facts.provenance.runtime_binding(node.id, node)
            value = self.facts.provenance.assignment_value(binding, node) if isinstance(binding, ast.Name) else None
            return value is not None and self._native_namespace(value, depth=depth + 1)
        if not isinstance(node, ast.Call):
            return False
        if self.facts.qualified(node.func, node) in {"builtins.globals", "builtins.locals", "builtins.vars"}:
            return True
        return (
            isinstance(node.func, ast.Name)
            and node.func.id in {"globals", "locals", "vars"}
            and self.facts.provenance.binding(node.func.id, node) is None
            and not self.facts.shadowed(node.func.id, node)
        )

    def dict_call(self, call: ast.Call) -> bool:
        return (
            len(call.args) <= 1
            and not any(isinstance(value, ast.Starred) for value in call.args)
            and self.builtin(call.func, "dict", call)
        )


@final
class _NamespaceFlow:
    def __init__(self, native: NativeObjectContracts, function: _Function) -> None:
        self.native = native
        self.function = function
        self.bindings: set[ast.AST] = set()
        self.executions: dict[ast.AST, list[ast.Call]] = defaultdict(list)
        self.reads: dict[ast.arg, set[ast.Name]] = defaultdict(set)
        self.nodes = tuple(direct_nodes(function)) if native.namespace_possible else ()
        for node in self.nodes:
            if isinstance(node, ast.Call):
                for namespace in self.arguments(node):
                    if self.plain_dict(namespace):
                        self._collect(namespace, execution=node)
        self._writes()

    def parameters(self) -> frozenset[ast.arg]:
        if not self.reads or self._unsafe_inputs():
            return frozenset()
        return frozenset(
            parameter
            for parameter, allowed in self.reads.items()
            if all(read in allowed or _identity_read(read, self.native.context) for read in self._reads(parameter))
        )

    def _unsafe_inputs(self) -> bool:
        return any(
            self.known(read) and self._before_execution(read, read) and not self._namespace_input_read(read)
            for reads in self.native.facts.provenance.reads.values()
            for read in reads
        )

    def _namespace_input_read(self, read: ast.Name) -> bool:
        parent = self.native.context.parents.get(read)
        if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is read:
            return True
        if isinstance(parent, ast.Subscript) and parent.value is read:
            return isinstance(parent.ctx, ast.Store)
        if isinstance(parent, ast.Call):
            return self.native.dict_call(parent) or any(namespace is read for namespace in self.arguments(parent))
        return False

    def evaluates(self, call: ast.Call) -> bool:
        return self.native.builtin(call.func, "eval", call) and any(
            self.binding(namespace) in self.bindings for namespace in self.arguments(call)
        )

    def known(self, value: ast.expr) -> bool:
        return bool(self.related(value) & self.bindings)

    def container(self, value: ast.expr) -> bool:
        return self._execution(value, value) is not None

    def unknown_read(self, node: ast.expr) -> bool:
        receiver = self._receiver(node)
        if receiver is None or (execution := self._execution(receiver, node)) is None:
            return False
        escapes = _NamespaceEscapes(self, receiver)
        return not any(
            source_position(execution) < source_position(statement) <= source_position(node)
            and (self._mutates(statement, receiver) or (isinstance(statement, ast.Call) and escapes.call(statement)))
            for statement in self.nodes
        )

    def _receiver(self, node: ast.expr) -> ast.expr | None:
        if isinstance(node, ast.Subscript):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            return node.func.value
        return None

    def _execution(self, receiver: ast.expr, at: ast.expr) -> ast.Call | None:
        calls = [call for binding in self.related(receiver) for call in self.executions.get(binding, ())]
        return next((call for call in reversed(calls) if self._dominates(call, at)), None)

    def _dominates(self, call: ast.Call, at: ast.AST) -> bool:
        statement = self.native.context.parents.get(call)
        return (
            isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign)
            and self.native.context.parents.get(statement) is self.function
            and (statement.end_lineno or statement.lineno) < source_position(at)[0]
        )

    def related(self, value: ast.expr, *, depth: int = 0) -> set[ast.AST]:
        if depth >= _MAX_DEPTH:
            return set()
        binding = self.binding(value)
        found: set[ast.AST] = {binding} if binding is not None else set()
        if isinstance(value, ast.Name) and (assigned := self.assigned(value)) is not None:
            found.update(self.related(assigned, depth=depth + 1))
        return found

    def _mutates(self, node: ast.AST, receiver: ast.expr) -> bool:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Delete):
            targets = node.targets if isinstance(node, ast.Assign | ast.Delete) else [node.target]
            return any(
                isinstance(target, ast.Subscript) and bool(self.related(target.value) & self.related(receiver))
                for target in targets
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return node.func.attr not in {"get", "keys", "values", "items", "copy"} and bool(
                self.related(node.func.value) & self.related(receiver)
            )
        return False

    def _reads(self, parameter: ast.arg) -> tuple[ast.Name, ...]:
        provenance = self.native.facts.provenance
        return tuple(
            read for reads in provenance.reads.values() for read in reads if self._root_parameter(read) is parameter
        )

    def _root_parameter(self, read: ast.Name, *, depth: int = 0) -> ast.arg | None:
        if depth >= _MAX_DEPTH:
            return None
        binding = self.native.facts.provenance.runtime_binding(read.id, read)
        if isinstance(binding, ast.arg):
            return binding
        assigned = self.assigned(read)
        return self._root_parameter(assigned, depth=depth + 1) if isinstance(assigned, ast.Name) else None

    def arguments(self, call: ast.Call) -> tuple[ast.expr, ...]:
        name = next((name for name in ("exec", "eval") if self.native.builtin(call.func, name, call)), None)
        if name is None or not call.args:
            return ()
        allowed = {"globals", "locals", "closure"} if name == "exec" else {"globals", "locals"}
        if any(keyword.arg not in allowed for keyword in call.keywords):
            return ()
        arguments = call_arguments(call, ("source", "globals", "locals"))
        if arguments is None or "source" not in arguments:
            return ()
        return tuple(arguments[name] for name in ("globals", "locals") if name in arguments)

    def binding(self, value: ast.expr) -> ast.AST | None:
        if isinstance(value, ast.Name):
            return self.native.facts.provenance.runtime_binding(value.id, value)
        return value if isinstance(value, ast.Dict | ast.Call | ast.IfExp) else None

    def assigned(self, node: ast.Name) -> ast.expr | None:
        binding = self.binding(node)
        if not isinstance(binding, ast.Name) or node.id in self.native.facts.provenance.mutated:
            return None
        return self.native.facts.provenance.assignment_value(binding, node)

    def plain_dict(self, value: ast.expr, *, depth: int = 0) -> bool:
        if depth >= _MAX_DEPTH:
            return False
        match value:
            case ast.Name():
                assigned = self.assigned(value)
                return assigned is not None and self.plain_dict(assigned, depth=depth + 1)
            case ast.IfExp():
                return self.plain_dict(value.body, depth=depth + 1) and self.plain_dict(value.orelse, depth=depth + 1)
            case _:
                pass
        return isinstance(value, ast.Dict) or (isinstance(value, ast.Call) and self.native.dict_call(value))

    def _collect(self, value: ast.expr, *, execution: ast.Call, depth: int = 0) -> None:
        if depth >= _MAX_DEPTH:
            return
        binding = self.binding(value)
        if binding is not None:
            self.bindings.add(binding)
            self.executions[binding].append(execution)
        match value:
            case ast.Name():
                assigned = self.assigned(value)
                if assigned is not None:
                    self._collect(assigned, execution=execution, depth=depth + 1)
            case ast.Dict() | ast.Call():
                self._input(value, depth=depth + 1)
            case ast.IfExp():
                self._collect(value.body, execution=execution, depth=depth + 1)
                self._collect(value.orelse, execution=execution, depth=depth + 1)
            case _:
                pass

    def _input(self, value: ast.expr, *, depth: int = 0) -> set[ast.arg]:
        if depth >= _MAX_DEPTH:
            return set()
        match value:
            case ast.Name():
                return self._name_input(value, depth)
            case ast.Dict():
                return self._dictionary_inputs(value, depth)
            case _:
                pass
        if isinstance(value, ast.Call) and self.native.dict_call(value):
            return self._constructor_inputs(value, depth)
        found: set[ast.arg] = set()
        if isinstance(value, ast.List | ast.Tuple | ast.Set):
            for member in value.elts:
                found.update(self._input(member, depth=depth + 1))
        return found

    def _name_input(self, value: ast.Name, depth: int) -> set[ast.arg]:
        binding = self.native.facts.provenance.runtime_binding(value.id, value)
        if isinstance(binding, ast.arg):
            self.reads[binding].add(value)
            return {binding}
        assigned = self.assigned(value)
        found: set[ast.arg] = self._input(assigned, depth=depth + 1) if assigned is not None else set()
        for parameter in found:
            self.reads[parameter].add(value)
        return found

    def _dictionary_inputs(self, value: ast.Dict, depth: int) -> set[ast.arg]:
        found: set[ast.arg] = set()
        for key, member in zip(value.keys, value.values, strict=True):
            if key is None:
                found.update(self._mapping_input(member, depth=depth + 1))
            else:
                found.update(self._input(member, depth=depth + 1))
        return found

    def _constructor_inputs(self, value: ast.Call, depth: int) -> set[ast.arg]:
        found: set[ast.arg] = set()
        for member in value.args:
            found.update(self._mapping_input(member, depth=depth + 1))
        for keyword in value.keywords:
            if keyword.arg is None:
                found.update(self._mapping_input(keyword.value, depth=depth + 1))
            else:
                found.update(self._input(keyword.value, depth=depth + 1))
        return found

    def _mapping_input(self, value: ast.expr, *, depth: int) -> set[ast.arg]:
        if depth >= _MAX_DEPTH or not isinstance(value, ast.Name):
            return set()
        parameter = self._root_parameter(value)
        if (
            parameter is not None
            and parameter.annotation is not None
            and self.native.facts.annotation(parameter.annotation, parameter.annotation, mapping=True)
        ):
            return self._input(value, depth=depth + 1)
        return set()

    def _writes(self) -> None:
        for node in self.nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if (
                    isinstance(target, ast.Subscript)
                    and self.known(target.value)
                    and self._before_execution(node, target.value)
                ):
                    self._input(node.value)

    def _before_execution(self, node: ast.AST, receiver: ast.expr) -> bool:
        return any(
            source_position(node)[0] < call.lineno
            for binding in self.related(receiver)
            for call in self.executions.get(binding, ())
        )


@final
class _NamespaceEscapes:
    def __init__(self, flow: _NamespaceFlow, receiver: ast.expr) -> None:
        self.flow = flow
        self.receiver = receiver
        self.related = flow.related(receiver)
        self.remaining = _MAX_ESCAPE_NODES
        self.seen: set[ast.AST] = set()
        self.at: ast.Call | None = None

    def call(self, call: ast.Call) -> bool:
        self.remaining = _MAX_ESCAPE_NODES
        self.seen = set()
        self.at = call
        execution = self._execution_escape(call)
        if execution is not None:
            return execution
        if self._native_call(call):
            return False
        values = (*call.args, *(keyword.value for keyword in call.keywords), call.func)
        return any(self._holds(value) for value in values)

    def _execution_escape(self, call: ast.Call) -> bool | None:
        native = self.flow.native
        if not any(native.builtin(call.func, name, call) for name in ("exec", "eval")):
            return None
        arguments = call_arguments(call, ("source", "globals", "locals"))
        if arguments is None or "source" not in arguments:
            return True
        global_scope, local_scope = arguments.get("globals"), arguments.get("locals")
        if _default_scope(global_scope) and (
            local_scope is None or not (self.flow.related(local_scope) & self.related)
        ):
            return True
        scopes = [scope for scope in (global_scope, local_scope) if scope is not None and not _default_scope(scope)]
        if any(not self.flow.plain_dict(scope) for scope in scopes):
            return True
        if any(not (self.flow.related(scope) & self.related) and self._holds(scope) for scope in scopes):
            return True
        return any(keyword.arg == "closure" and self._holds(keyword.value) for keyword in call.keywords)

    def _native_call(self, call: ast.Call) -> bool:
        native = self.flow.native
        if len(call.args) == 1 and not call.keywords:
            if any(native.builtin(call.func, name, call) for name in ("id", "type")):
                return True
            if self._plain_container(call.args[0]) and any(
                native.builtin(call.func, name, call) for name in ("bool", "len")
            ):
                return True
            if native.qualified(call.func, call) in _REFLECTION_INPUTS:
                return True
        if (
            native.dict_call(call)
            and all(self.flow.plain_dict(value) for value in call.args)
            and all(keyword.arg is not None or self.flow.plain_dict(keyword.value) for keyword in call.keywords)
        ):
            return True
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in {"get", "keys", "values", "items", "copy"}
            and self.flow.plain_dict(call.func.value)
        )

    def _plain_container(self, value: ast.expr, *, depth: int = 0) -> bool:
        if depth >= _MAX_DEPTH:
            return False
        if self.flow.plain_dict(value) or isinstance(value, ast.List | ast.Tuple | ast.Set):
            return True
        if isinstance(value, ast.Name):
            assigned = self.flow.assigned(value)
            return assigned is not None and self._plain_container(assigned, depth=depth + 1)
        return isinstance(value, ast.Call) and any(
            self.flow.native.builtin(value.func, name, value) for name in ("list", "tuple", "set", "frozenset")
        )

    def _holds(self, node: ast.AST, *, depth: int = 0) -> bool:
        if depth >= _MAX_DEPTH or self.remaining <= 0:
            return True
        self.remaining -= 1
        if node in self.seen:
            return False
        self.seen.add(node)
        if isinstance(node, ast.Name):
            return self._name(node, depth)
        return any(self._holds(child, depth=depth + 1) for child in ast.iter_child_nodes(node))

    def _name(self, node: ast.Name, depth: int) -> bool:
        binding = self.flow.binding(node)
        if binding in self.related:
            return True
        if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return self._holds(binding, depth=depth + 1)
        assigned = self.flow.assigned(node)
        if assigned is None:
            return False
        if isinstance(assigned, ast.Call) and self._scalar_call(assigned):
            return False
        return self._holds(assigned, depth=depth + 1) or any(
            self._holds(value, depth=depth + 1) for value in self._stored(node)
        )

    def _scalar_call(self, call: ast.Call) -> bool:
        return (
            len(call.args) == 1
            and not call.keywords
            and any(self.flow.native.builtin(call.func, name, call) for name in ("bool", "id", "len", "type"))
        )

    def _stored(self, value: ast.Name) -> Iterator[ast.expr]:
        roots = self._carrier_roots(value)
        if roots is None:
            yield self.receiver
            return
        for node in self.flow.nodes:
            if self.at is None or source_position(node) >= source_position(self.at):
                continue
            yield from self._stored_values(node, roots)

    def _stored_values(self, node: ast.AST, roots: set[ast.AST]) -> Iterator[ast.expr]:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Subscript) and self._same_carrier(target.value, roots) for target in targets):
                yield node.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr not in {"get", "keys", "values", "items", "copy", "count", "index"}
            and self._same_carrier(node.func.value, roots)
        ):
            yield from node.args
            yield from (keyword.value for keyword in node.keywords)

    def _same_carrier(self, value: ast.expr, roots: set[ast.AST]) -> bool:
        other = self._carrier_roots(value)
        return other is None or bool(roots & other)

    def _carrier_roots(self, value: ast.expr, *, depth: int = 0) -> set[ast.AST] | None:
        if depth >= _MAX_DEPTH:
            return None
        binding = self.flow.binding(value)
        found: set[ast.AST] = {binding} if binding is not None else set()
        match value:
            case ast.Name():
                assigned = self.flow.assigned(value)
                if isinstance(assigned, ast.Name | ast.Subscript):
                    previous = self._carrier_roots(assigned, depth=depth + 1)
                    return None if previous is None else found | previous
            case ast.Subscript():
                return self._carrier_roots(value.value, depth=depth + 1)
            case _:
                pass
        return found


def _default_scope(value: ast.expr | None) -> bool:
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def _accepted_branch(node: ast.AST, parent: ast.AST) -> bool:
    if isinstance(parent, ast.IfExp):
        return node is parent.body
    return isinstance(parent, ast.If) and node in parent.body


def source_position(node: ast.AST) -> SourcePosition:
    return (
        SourcePosition(node.lineno, node.col_offset) if isinstance(node, ast.stmt | ast.expr) else SourcePosition(0, 0)
    )


def _identity_read(read: ast.Name, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    return isinstance(parent, ast.Compare) and all(isinstance(operator, ast.Is | ast.IsNot) for operator in parent.ops)


def _stub(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Pass) or (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and (statement.value.value is Ellipsis or isinstance(statement.value.value, str))
    )


def builtin_object(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> bool:
    candidate = facts.qualified(node, at) == "builtins.object" or (
        isinstance(node, ast.Name)
        and node.id == "object"
        and not facts.shadowed(node.id, at)
        and facts.provenance.binding(node.id, at) is None
    )
    if not candidate:
        return False
    context = facts.context
    if facts.provenance.builtin_namespace_untouched and not context.dynamic_namespace:
        return True
    native = NativeObjectContracts(context, facts)
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name):
        changed = native.namespace_replaced(root.id) if root.id == "object" else native.namespace_rebound(root.id)
        if changed:
            return False
    attribute_mutation = any(
        isinstance(member.ctx, ast.Store | ast.Del)
        and member.attr == "object"
        and _builtins_module(member.value, context)
        for member in context.nodes(ast.Attribute)
    )
    return not attribute_mutation and not any(
        isinstance(call.func, ast.Name)
        and call.func.id in {"setattr", "delattr"}
        and len(call.args) >= _PAIR_ARITY
        and _builtins_module(call.args[0], context)
        and (not isinstance(call.args[1], ast.Constant) or call.args[1].value == "object")
        for call in context.nodes(ast.Call)
    )


def _builtins_module(node: ast.expr, context: PythonFileContext) -> bool:
    if not isinstance(node, ast.Name):
        return False
    target = context.imports.bindings.get(node.id)
    return target is not None and target.module == "builtins" and target.symbol is None
