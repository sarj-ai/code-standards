from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex


_MAX_PATHS = 64


class _ReturnKind(Enum):
    FIXED = auto()
    OPEN = auto()
    UNKNOWN = auto()


@dataclass(slots=True)
class _Record:
    keys: set[str] = field(default_factory=set)
    open: bool = False


@dataclass(slots=True)
class _State:
    names: dict[str, int] = field(default_factory=dict)
    records: dict[int, _Record] = field(default_factory=dict)
    next_identity: int = 0

    def clone(self) -> _State:
        return _State(
            names=dict(self.names),
            records={identity: _Record(set(record.keys), record.open) for identity, record in self.records.items()},
            next_identity=self.next_identity,
        )

    def bind_record(self, name: str, keys: set[str]) -> None:
        identity = self.next_identity
        self.next_identity += 1
        self.names[name] = identity
        self.records[identity] = _Record(keys)

    def detach(self, name: str) -> None:
        identity = self.names.pop(name, None)
        if identity is not None and identity not in self.names.values():
            self.records.pop(identity, None)

    def record(self, name: str) -> _Record | None:
        identity = self.names.get(name)
        return self.records.get(identity) if identity is not None else None


@dataclass(slots=True)
class _Flow:
    active: list[_State] = field(default_factory=list)
    returned: list[_ReturnKind] = field(default_factory=list)


def builds_fixed_record(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    imports: ImportIndex | None = None,
) -> bool:
    flow = _Analyzer(
        imports,
        locally_bound=_function_bound_names(node),
        externally_bound=_function_external_names(node),
    ).block(node.body, [_State()])
    return bool(flow.returned) and all(kind is _ReturnKind.FIXED for kind in flow.returned)


class _Analyzer:
    def __init__(
        self,
        imports: ImportIndex | None,
        *,
        locally_bound: set[str],
        externally_bound: set[str],
    ) -> None:
        self.imports: ImportIndex | None = imports
        self.locally_bound: set[str] = locally_bound
        self.externally_bound: set[str] = externally_bound

    def block(self, statements: list[ast.stmt], states: list[_State]) -> _Flow:
        flow = _Flow(active=states)
        for statement in statements:
            next_states: list[_State] = []
            for state in flow.active:
                statement_flow = self.statement(statement, state)
                next_states.extend(statement_flow.active)
                flow.returned.extend(statement_flow.returned)
            if len(next_states) > _MAX_PATHS:
                flow.active = []
                flow.returned.append(_ReturnKind.UNKNOWN)
                return flow
            flow.active = next_states
            if not flow.active:
                break
        return flow

    def statement(self, statement: ast.stmt, state: _State) -> _Flow:
        match statement:
            case ast.Return(value=value):
                return _Flow(returned=[self.return_kind(value, state)])
            case ast.Raise():
                return _Flow()
            case ast.Assign() | ast.AnnAssign():
                return self.assignment_statement(statement, state)
            case ast.AugAssign(target=target, op=operator, value=value):
                self._augmented_assignment(target, operator, value, state)
            case ast.Delete(targets=targets):
                for target in targets:
                    self.open_target(target, state)
            case ast.Import(names=aliases):
                self._detach_imports(aliases, state, from_import=False)
            case ast.ImportFrom(names=aliases):
                self._detach_imports(aliases, state, from_import=True)
            case ast.Expr(value=ast.Call() as call):
                self.call(call, state)
            case ast.If():
                return self.if_statement(statement, state)
            case ast.Match():
                return self.match_statement(statement, state)
            case ast.Try():
                return self.try_statement(statement, state)
            case ast.For() | ast.AsyncFor() | ast.While():
                return self._loop_statement(statement, state)
            case ast.With() | ast.AsyncWith():
                return self.with_statement(statement, state)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                self._nested_definition(statement, name, state)
            case _:
                self._inspect_fallback(statement, state)
        return _Flow(active=[state])

    def _augmented_assignment(
        self,
        target: ast.expr,
        operator: ast.operator,
        value: ast.expr,
        state: _State,
    ) -> None:
        if isinstance(operator, ast.BitOr):
            self.mapping_update(target, value, state)
            return
        self.open_target(target, state)

    def _detach_imports(
        self,
        aliases: list[ast.alias],
        state: _State,
        *,
        from_import: bool,
    ) -> None:
        for alias in aliases:
            if from_import and alias.name == "*":
                continue
            default_name = alias.name if from_import else alias.name.partition(".")[0]
            state.detach(alias.asname or default_name)

    def _loop_statement(self, statement: ast.stmt, state: _State) -> _Flow:
        self.invalidate_loop(statement, state)
        has_return = any(isinstance(child, ast.Return) for child in ast.walk(statement))
        returned = [_ReturnKind.UNKNOWN] if has_return else []
        return _Flow(active=[state], returned=returned)

    def _nested_definition(self, statement: ast.stmt, name: str, state: _State) -> None:
        self._mark_loaded_records_open(statement, state)
        state.detach(name)

    def _inspect_fallback(self, statement: ast.stmt, state: _State) -> None:
        for child in ast.walk(statement):
            match child:
                case ast.Call():
                    self.call(child, state)
                case ast.NamedExpr(target=target):
                    self.rebind_target(target, state)
                case _:
                    pass

    def assignment_statement(self, statement: ast.Assign | ast.AnnAssign, state: _State) -> _Flow:
        match statement:
            case ast.Assign(targets=targets, value=value):
                self._plain_assignment(targets, value, state)
            case ast.AnnAssign(target=target, value=None):
                self.rebind_target(target, state)
            case ast.AnnAssign(target=target, value=ast.expr() as value):
                self.escape_expression(value, state)
                if not isinstance(target, ast.Name):
                    self.escape_loaded_records(value, state)
                self.assign(target, value, state)
            case _:
                pass
        return _Flow(active=[state])

    def _plain_assignment(self, targets: list[ast.expr], value: ast.expr, state: _State) -> None:
        self.escape_expression(value, state)
        if any(not isinstance(target, ast.Name) for target in targets):
            self.escape_loaded_records(value, state)
        if self._bind_static_assignment(targets, value, state):
            return
        for target in targets:
            self.assign(target, value, state)

    def _bind_static_assignment(self, targets: list[ast.expr], value: ast.expr, state: _State) -> bool:
        target_names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not target_names or len(target_names) != len(targets):
            return False
        keys = self.record_keys(value)
        if keys is None or self.externally_bound.intersection(target_names):
            return False
        first, *aliases = target_names
        state.bind_record(first, keys)
        identity = state.names[first]
        for name in aliases:
            state.names[name] = identity
        return True

    def if_statement(self, statement: ast.If, state: _State) -> _Flow:
        self.escape_expression(statement.test, state)
        left = self.block(statement.body, [state.clone()])
        right = self.block(statement.orelse, [state.clone()]) if statement.orelse else _Flow(active=[state.clone()])
        return _merge_flows(left, right)

    def match_statement(self, statement: ast.Match, state: _State) -> _Flow:
        self.escape_expression(statement.subject, state)
        flow = _Flow()
        for case in statement.cases:
            branch_state = state.clone()
            for name in _pattern_names(case.pattern):
                branch_state.detach(name)
            if case.guard is not None:
                self.escape_expression(case.guard, branch_state)
            _extend_flow(flow, self.block(case.body, [branch_state]))
        if not any(_is_unguarded_irrefutable(case) for case in statement.cases):
            flow.active.append(state.clone())
        return flow

    def try_statement(self, statement: ast.Try, state: _State) -> _Flow:
        flow = self.block([*statement.body, *statement.orelse], [state.clone()])
        for handler in statement.handlers:
            _extend_flow(flow, self._exception_handler(handler, state))
        if statement.finalbody:
            self._apply_finally(statement.finalbody, flow)
        return flow

    def _exception_handler(self, handler: ast.ExceptHandler, state: _State) -> _Flow:
        handler_state = state.clone()
        for record in handler_state.records.values():
            record.open = True
        if handler.name is not None:
            handler_state.detach(handler.name)
        return self.block(handler.body, [handler_state])

    def _apply_finally(self, finalbody: list[ast.stmt], flow: _Flow) -> None:
        has_suspended_return = bool(flow.returned)
        final_flow = self.block(finalbody, flow.active)
        flow.active = final_flow.active
        flow.returned.extend(final_flow.returned)
        # A return suspends before ``finally`` runs. Return outcomes do not
        # retain their state, so abstain instead of claiming that a record
        # returned from the try/handler cannot be mutated or replaced.
        if has_suspended_return:
            flow.returned.append(_ReturnKind.UNKNOWN)

    def with_statement(self, statement: ast.With | ast.AsyncWith, state: _State) -> _Flow:
        for item in statement.items:
            self.escape_expression(item.context_expr, state)
            if item.optional_vars is not None:
                self.rebind_target(item.optional_vars, state)
        return self.block(statement.body, [state])

    def return_kind(self, value: ast.expr | None, state: _State) -> _ReturnKind:
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            return _ReturnKind.FIXED
        fixed = self.fixed_expression(value, state)
        if fixed is True:
            return _ReturnKind.FIXED
        if fixed is False:
            return _ReturnKind.OPEN
        return _ReturnKind.UNKNOWN

    def fixed_expression(self, value: ast.expr, state: _State) -> bool | None:
        match value:
            case ast.Name(id=name):
                record = state.record(name)
                return None if record is None else bool(record.keys) and not record.open
            case ast.Dict():
                keys = self.record_keys(value)
                return False if keys is None else bool(keys)
            case ast.List(elts=[]):
                return False
            case ast.List(elts=elements):
                members = [self.fixed_expression(element, state) for element in elements]
                return all(member is True for member in members)
            case ast.ListComp(elt=element):
                return self.fixed_expression(element, state)
            case _:
                keys = self.record_keys(value)
                return bool(keys) if keys is not None else None

    def record_keys(self, value: ast.expr) -> set[str] | None:
        match value:
            case ast.Dict():
                return _literal_dict_keys(value)
            case ast.Call(func=func) if self.builtin_dict(func):
                return self._dict_call_keys(value)
            case _:
                return None

    def _dict_call_keys(self, call: ast.Call) -> set[str] | None:
        if len(call.args) > 1 or any(keyword.arg is None for keyword in call.keywords):
            return None
        keys = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
        if not call.args:
            return keys
        base = self.record_keys(call.args[0])
        if base is None:
            return None
        keys.update(base)
        return keys

    def builtin_dict(self, node: ast.expr) -> bool:
        root = _root_name(node)
        if root is not None and root in self.locally_bound:
            return False
        if isinstance(node, ast.Name) and node.id == "dict":
            return self.imports is None or self.imports.builtin_is_unshadowed("dict")
        return self.imports is not None and self.imports.resolves(node, sources=frozenset({"builtins"}), symbol="dict")

    def assign(self, target: ast.expr, value: ast.expr, state: _State) -> None:
        match target:
            case ast.Name(id=name):
                self._assign_name(name, value, state)
            case ast.Subscript():
                self._assign_subscript(target, state)
            case _:
                self.rebind_target(target, state)

    def _assign_name(self, name: str, value: ast.expr, state: _State) -> None:
        if name in self.externally_bound:
            state.detach(name)
            return
        if isinstance(value, ast.Name) and value.id in state.names:
            state.names[name] = state.names[value.id]
            return
        keys = self.record_keys(value)
        if keys is not None:
            state.bind_record(name, keys)
            return
        state.detach(name)

    def _assign_subscript(self, target: ast.Subscript, state: _State) -> None:
        root = _root_name(target)
        record = state.record(root) if root is not None else None
        if record is None:
            return
        key = _literal_string(target.slice)
        if key is None:
            record.open = True
            return
        record.keys.add(key)

    def mapping_update(self, target: ast.expr, value: ast.expr, state: _State) -> None:
        root = _root_name(target)
        record = state.record(root) if root is not None else None
        if record is None:
            return
        keys = self.record_keys(value)
        if keys is None:
            record.open = True
        else:
            record.keys.update(keys)

    def call(self, call: ast.Call, state: _State) -> None:
        if self._record_method_call(call, state):
            return
        for argument in _call_arguments(call):
            self._mark_loaded_records_open(argument, state)

    def _record_method_call(self, call: ast.Call, state: _State) -> bool:
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            return False
        record = state.record(call.func.value.id)
        if record is None:
            return False
        for argument in _call_arguments(call):
            self.escape_expression(argument, state)
        match call.func.attr:
            case "update":
                self._apply_update_call(record, call)
            case "setdefault":
                self._apply_setdefault_call(record, call)
            case _:
                record.open = True
        return True

    def _apply_update_call(self, record: _Record, call: ast.Call) -> None:
        if len(call.args) > 1 or any(keyword.arg is None for keyword in call.keywords):
            record.open = True
            return
        keys = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
        if call.args:
            base = self.record_keys(call.args[0])
            if base is None:
                record.open = True
                return
            keys.update(base)
        record.keys.update(keys)

    @staticmethod
    def _apply_setdefault_call(record: _Record, call: ast.Call) -> None:
        if call.args:
            key = _literal_string(call.args[0])
            if key is not None:
                record.keys.add(key)
                return
        record.open = True

    def escape_expression(self, value: ast.expr, state: _State) -> None:
        if isinstance(value, (ast.Lambda, ast.Dict, ast.List, ast.Set, ast.Tuple)):
            self._mark_loaded_records_open(value, state)
        for child in ast.walk(value):
            match child:
                case ast.Call():
                    self.call(child, state)
                case ast.NamedExpr(target=target):
                    self.rebind_target(target, state)
                case _:
                    pass

    def escape_loaded_records(self, value: ast.expr, state: _State) -> None:
        self._mark_loaded_records_open(value, state)

    def _mark_loaded_records_open(self, node: ast.AST, state: _State) -> None:
        for name in _loaded_names(node):
            record = state.record(name)
            if record is not None:
                record.open = True

    def open_target(self, target: ast.expr, state: _State) -> None:
        root = _root_name(target)
        if root is None:
            return
        record = state.record(root)
        if record is not None:
            record.open = True

    def rebind_target(self, target: ast.expr, state: _State) -> None:
        for name in _stored_names(target):
            state.detach(name)

    def invalidate_loop(self, node: ast.stmt, state: _State) -> None:
        for child in ast.walk(node):
            match child:
                case ast.Name(id=name, ctx=ast.Store()):
                    record = state.record(name)
                    if record is not None:
                        record.open = True
                    state.detach(name)
                case ast.Call():
                    self.call(child, state)
                case ast.Subscript(ctx=ast.Store()):
                    self.open_target(child, state)
                case _:
                    pass


def _extend_flow(destination: _Flow, source: _Flow) -> None:
    destination.active.extend(source.active)
    destination.returned.extend(source.returned)


def _merge_flows(*flows: _Flow) -> _Flow:
    merged = _Flow()
    for flow in flows:
        _extend_flow(merged, flow)
    return merged


def _literal_dict_keys(node: ast.Dict) -> set[str] | None:
    if any(key is None for key in node.keys):
        return None
    keys = {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return keys if len(keys) == len(node.keys) else None


def _call_arguments(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(keyword.value for keyword in call.keywords)]


def _literal_string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _loaded_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}


def _stored_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }


def _is_unguarded_irrefutable(case: ast.match_case) -> bool:
    return case.guard is None and isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


def _pattern_names(pattern: ast.pattern) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(pattern):
        match node:
            case ast.MatchAs(name=name) | ast.MatchStar(name=name) if name is not None:
                names.add(name)
            case ast.MatchMapping(rest=rest) if rest is not None:
                names.add(rest)
            case _:
                pass
    return names


def _function_bound_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = _argument_names(node.args)
    for statement in node.body:
        for child in ast.walk(statement):
            names.update(_names_bound_by_node(child))
    return names


def _argument_names(arguments: ast.arguments) -> set[str]:
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _names_bound_by_node(node: ast.AST) -> set[str]:
    match node:
        case (
            ast.Name(id=name, ctx=ast.Store() | ast.Del())
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            return {name}
        case ast.Import(names=aliases):
            return {alias.asname or alias.name.partition(".")[0] for alias in aliases}
        case ast.ImportFrom(names=aliases):
            return {alias.asname or alias.name for alias in aliases if alias.name != "*"}
        case ast.ExceptHandler(name=name) if name is not None:
            return {name}
        case _:
            return set()


def _function_external_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        name
        for statement in node.body
        for child in ast.walk(statement)
        if isinstance(child, (ast.Global, ast.Nonlocal))
        for name in child.names
    }
