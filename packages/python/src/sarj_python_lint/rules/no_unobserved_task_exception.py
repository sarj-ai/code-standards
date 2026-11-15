from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._async_lifecycle import AsyncApiProof
from sarj_python_lint.rules.cancel_owned_task_without_join import unjoined_lifespan_child


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_LOOP_SOURCES = ("asyncio.get_running_loop", "asyncio.get_event_loop", "asyncio.new_event_loop")
_INERT_TASK_METHODS = frozenset(
    {
        "cancel",
        "cancelled",
        "cancelling",
        "done",
        "get_context",
        "get_coro",
        "get_loop",
        "get_name",
        "remove_done_callback",
        "set_name",
        "uncancel",
    }
)
_CONTAINER_INSERTS = frozenset({"add", "append"})
_CONTAINER_REMOVALS = frozenset({"discard", "remove"})
_CONTAINER_MEMBERSHIP = _CONTAINER_INSERTS | _CONTAINER_REMOVALS
_CONTAINER_ELEMENTS = frozenset({"get", "pop"})
_CONTAINER_COPIES = frozenset({"list", "tuple", "set", "frozenset", "sorted"})
_CONTAINER_BUILDERS = frozenset({"set", "list", "dict"})
_ATTRIBUTE_REFLECTION = frozenset({"getattr", "setattr", "delattr"})
_MESSAGE = (
    "nothing observes this stored task's outcome, so its failure surfaces only as "
    '"Task exception was never retrieved" at garbage collection; await or gather it where its owner stops, '
    "or add a done callback that logs task.exception()"
)
_BAD = """import asyncio


class Recorder:
    def start(self) -> None:
        self._upload = asyncio.create_task(self._send())

    def stop(self) -> None:
        self._upload.cancel()

    async def _send(self) -> None:
        await asyncio.sleep(1)
"""
_GOOD = _BAD.replace(
    "    def stop(self) -> None:\n        self._upload.cancel()\n",
    "    async def stop(self) -> None:\n        self._upload.cancel()\n"
    "        await asyncio.gather(self._upload, return_exceptions=True)\n",
)


class _Kind(Enum):
    TASK = auto()
    CONTAINER = auto()


@dataclass(frozen=True, slots=True)
class _Slot:
    kind: _Kind
    owner: ast.AST
    name: str


type _Successors = list[_Slot] | None


@final
class NoUnobservedTaskException(Rule):
    id = "no-unobserved-task-exception"
    code = "SARJ574"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Observe the outcome of every stored asyncio task.",
        rationale=(
            "A failed task that nothing awaits, gathers or inspects reports its exception only as "
            '"Task exception was never retrieved" when it is garbage-collected: late, without the logging '
            "context of the code that started it, and never while a reference keeps it alive."
        ),
        remediation=(
            "Give the task one owner that observes its outcome: await it, or gather it with "
            "return_exceptions=True where the owner stops; create it with TaskGroup.create_task inside the scope "
            "that waits for it; or add a done callback that checks task.cancelled() and logs task.exception() "
            "with the starting code's context. Returning the task or passing it to the component that joins it "
            "also observes it."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Recognizes import-proven asyncio.create_task, asyncio.ensure_future of a call, and create_task on a loop from asyncio.get_running_loop, get_event_loop or new_event_loop. TaskGroup tasks and custom factories are not reported. Ruff RUF006 owns discarded results and never-read local bindings.",
            "Follows a task through local and closure names, private module names, private attributes of its own class, and set, list or dict containers those names build. Public attributes, parameters, other objects' attributes, global or nonlocal rebinding and reflective attribute access abstain because another component may own the task. Subclasses in other files are not inspected.",
            "Await, result(), exception(), return, yield, asyncio.gather/wait/wait_for/shield and every unrecognized consumer count as observation, including asyncio.wait results that are never read. A done callback observes unless it resolves in the file to a container discard/remove or to a function whose task parameter is only cancelled, inspected for state or discarded.",
            "A coroutine resolved in the file whose whole body is one try statement with a non-re-raising except Exception or BaseException handler observes its own failures. Lifespan tasks reported by cancel-owned-task-without-join are left to that rule.",
            "Observation is not flow-sensitive: an observation of any binding of the same name, attribute or container counts for every task stored there.",
        ),
        examples=(
            RuleExample(
                example_id="cancelled-without-observation",
                title="A stored task is only cancelled, so its failure is never retrieved",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/recorder.py", _BAD),),
                focus_path=PurePosixPath("app/recorder.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="owner-gathers-task",
                title="The owner gathers the task when it stops",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/recorder.py", _GOOD),),
                focus_path=PurePosixPath("app/recorder.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        if "create_task" not in context.symbol_source and "ensure_future" not in context.symbol_source:
            return []
        analysis = _TaskObservation(context)
        return [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.ERROR,
                message=_MESSAGE,
            )
            for call in context.nodes(ast.Call)
            if analysis.unobserved(call) and not context.suppressions.is_suppressed(call.lineno, self.code)
        ]


@final
class _TaskObservation:
    def __init__(self, context: PythonFileContext) -> None:
        self._context = context
        self._proof = AsyncApiProof(context)
        self._parents = context.parents
        self._inventory = context.binding_inventory
        self._lifespan_children = frozenset(
            child for call in context.nodes(ast.Call) if (child := unjoined_lifespan_child(self._proof, call))
        )
        self._attributes: defaultdict[str, list[ast.Attribute]] = defaultdict(list)
        for node in context.nodes(ast.Attribute):
            self._attributes[node.attr].append(node)
        self._reflected = _reflected_attributes(context)

    def unobserved(self, call: ast.Call) -> bool:
        if not self._creates_task(call) or isinstance(self._parents.get(call), ast.Expr):
            return False
        if self._self_observing(call.args[0], call):
            return False
        statement = self._parents.get(call)
        if isinstance(statement, ast.Assign) and any(target in self._lifespan_children for target in statement.targets):
            return False
        initial = self._expression_slots(call, _Kind.TASK)
        if not initial or self._ruff_owned(initial):
            return False
        pending = list(initial)
        seen: set[_Slot] = set()
        while pending:
            slot = pending.pop()
            if slot in seen:
                continue
            seen.add(slot)
            reads = self._slot_reads(slot)
            if reads is None:
                return False
            for read in reads:
                successors = self._expression_slots(read, slot.kind)
                if successors is None:
                    return False
                pending.extend(successors)
        return True

    def _ruff_owned(self, slots: list[_Slot]) -> bool:
        return all(
            slot.kind is _Kind.TASK
            and isinstance(slot.owner, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
            and not self._slot_reads(slot)
            for slot in slots
        )

    def _creates_task(self, call: ast.Call) -> bool:
        if not call.args or isinstance(call.args[0], ast.Starred):
            return False
        if self._proof.imported(call.func, "asyncio.create_task"):
            return True
        if self._proof.imported(call.func, "asyncio.ensure_future"):
            return isinstance(call.args[0], ast.Call)
        match call.func:
            case ast.Attribute(value=loop, attr="create_task"):
                return self._event_loop(loop, call)
            case _:
                return False

    def _self_observing(self, coroutine: ast.expr, at: ast.AST) -> bool:
        match coroutine:
            case ast.Call(func=ast.Name(id=name)):
                function = self._proof.provenance.binding(name, at)
            case ast.Call(func=ast.Attribute(value=ast.Name() as receiver, attr=attribute)):
                owner = self._method_class(receiver)
                function = _class_method(owner, attribute) if owner is not None else None
            case _:
                return False
        if not isinstance(function, ast.AsyncFunctionDef) or function.decorator_list:
            return False
        match _without_docstring(function.body):
            case [ast.Try(orelse=[], finalbody=[], handlers=handlers)]:
                return any(self._absorbs_failures(handler) for handler in handlers)
            case _:
                return False

    def _absorbs_failures(self, handler: ast.ExceptHandler) -> bool:
        caught = handler.type
        broad = caught is None or (
            isinstance(caught, ast.Name)
            and caught.id in {"Exception", "BaseException"}
            and self._builtin(caught.id, handler)
        )
        return broad and not any(isinstance(node, ast.Raise) for node in ast.walk(handler))

    def _event_loop(self, expression: ast.expr, at: ast.AST) -> bool:
        if isinstance(expression, ast.Name):
            assigned = self._proof.assignment(expression, at)
            if assigned is None:
                return False
            expression = assigned.value
        return isinstance(expression, ast.Call) and any(
            self._proof.imported(expression.func, source) for source in _LOOP_SOURCES
        )

    def _expression_slots(self, node: ast.expr, kind: _Kind) -> _Successors:
        parent = self._parents.get(node)
        match parent:
            case ast.Expr() | ast.Compare() | ast.UnaryOp(op=ast.Not()):
                return []
            case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test) | ast.Assert(test=test) if (
                test is node
            ):
                return []
            case ast.BoolOp() if self._truth_test(parent):
                return []
            case ast.Assign(value=value) | ast.AnnAssign(value=value) | ast.NamedExpr(value=value) if value is node:
                return self._assignment_slots(parent, kind)
            case ast.Attribute(value=receiver, ctx=ast.Load()) if receiver is node:
                return self._member_slots(parent, kind)
            case ast.Call(func=function) if function is not node and node in parent.args:
                return self._argument_slots(parent, kind)
            case _:
                return self._structural_slots(node, parent, kind)

    def _structural_slots(self, node: ast.expr, parent: ast.AST | None, kind: _Kind) -> _Successors:
        if kind is _Kind.CONTAINER:
            return self._container_use_slots(node, parent)
        if isinstance(parent, ast.expr) and _collection_element(node, parent):
            return self._expression_slots(parent, _Kind.CONTAINER)
        return None

    def _container_use_slots(self, node: ast.expr, parent: ast.AST | None) -> _Successors:
        match parent:
            case ast.Subscript(value=receiver) if receiver is node:
                return self._expression_slots(parent, _Kind.TASK) if isinstance(parent.ctx, ast.Load) else []
            case ast.comprehension(iter=iterated) | ast.For(iter=iterated) if iterated is node:
                slot = self._storage_slot(parent.target, _Kind.TASK)
                return None if slot is None else [slot]
            case _:
                return None

    def _truth_test(self, node: ast.BoolOp) -> bool:
        parent = self._parents.get(node)
        match parent:
            case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test) | ast.Assert(test=test):
                return test is node
            case ast.UnaryOp(op=ast.Not()) | ast.Expr():
                return True
            case ast.BoolOp():
                return self._truth_test(parent)
            case _:
                return False

    def _assignment_slots(self, statement: ast.Assign | ast.AnnAssign | ast.NamedExpr, kind: _Kind) -> _Successors:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        slots: list[_Slot] = []
        for target in targets:
            slot = (
                self._container_slot(target.value)
                if isinstance(target, ast.Subscript)
                else self._storage_slot(target, kind)
            )
            if slot is None:
                return None
            slots.append(slot)
        if isinstance(statement, ast.NamedExpr):
            following = self._expression_slots(statement, kind)
            if following is None:
                return None
            slots.extend(following)
        return slots

    def _member_slots(self, member: ast.Attribute, kind: _Kind) -> _Successors:
        call = self._parents.get(member)
        if not isinstance(call, ast.Call):
            return None
        if call.func is not member:
            return [] if kind is _Kind.CONTAINER and _removal_callback(member, call) else None
        if kind is _Kind.TASK:
            if member.attr in _INERT_TASK_METHODS:
                return []
            if member.attr == "add_done_callback" and len(call.args) == 1 and not call.keywords:
                return self._callback_slots(call.args[0], call)
            return None
        if member.attr in _CONTAINER_MEMBERSHIP or member.attr == "clear":
            return []
        if member.attr in _CONTAINER_ELEMENTS:
            return self._expression_slots(call, _Kind.TASK)
        if member.attr == "values" and not call.args:
            return self._expression_slots(call, _Kind.CONTAINER)
        return None

    def _argument_slots(self, call: ast.Call, kind: _Kind) -> _Successors:
        if len(call.args) != 1 or call.keywords:
            return None
        match call.func:
            case ast.Attribute(value=receiver, attr=attribute) if (
                kind is _Kind.TASK and attribute in _CONTAINER_MEMBERSHIP
            ):
                container = self._container_slot(receiver)
                return None if container is None else [container]
            case ast.Name(id="len") if kind is _Kind.CONTAINER and self._builtin("len", call):
                return []
            case ast.Name(id=builtin) if (
                kind is _Kind.CONTAINER and builtin in _CONTAINER_COPIES and self._builtin(builtin, call)
            ):
                return self._expression_slots(call, _Kind.CONTAINER)
            case _:
                return None

    def _callback_slots(self, callback: ast.expr, at: ast.AST) -> _Successors:
        match callback:
            case ast.Attribute(value=receiver, attr=attribute) if attribute in _CONTAINER_REMOVALS:
                container = self._container_slot(receiver)
                return None if container is None else [container]
            case ast.Lambda():
                return _parameter_slot(callback, 0)
            case ast.Name(id=name):
                binding = self._proof.provenance.binding(name, at)
                if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef) and not binding.decorator_list:
                    return _parameter_slot(binding, 0)
                return None
            case ast.Attribute(value=ast.Name() as receiver, attr=attribute):
                owner = self._method_class(receiver)
                method = _class_method(owner, attribute) if owner is not None else None
                return None if method is None else _parameter_slot(method, 1)
            case _:
                return None

    def _storage_slot(self, target: ast.expr, kind: _Kind) -> _Slot | None:
        match target:
            case ast.Name(id=name):
                owner = self._defining_scope(name, target)
                if (
                    owner is None
                    or isinstance(owner, ast.ClassDef)
                    or name in self._inventory.external_bindings
                    or (isinstance(owner, ast.Module) and not _private(name))
                ):
                    return None
                return _Slot(kind, owner, name)
            case ast.Attribute(value=ast.Name() as receiver, attr=attribute) if (
                _private(attribute) and self._reflected is not None and attribute not in self._reflected
            ):
                owner = self._method_class(receiver)
                return None if owner is None else _Slot(kind, owner, attribute)
            case _:
                return None

    def _container_slot(self, expression: ast.expr) -> _Slot | None:
        slot = self._storage_slot(expression, _Kind.CONTAINER)
        if slot is None:
            return None
        values = self._slot_values(slot)
        if not values or not all(self._builds_container(value) for value in values):
            return None
        return slot

    def _builds_container(self, value: ast.expr | None) -> bool:
        match value:
            case ast.List() | ast.Set() | ast.Dict() | ast.ListComp() | ast.SetComp() | ast.DictComp():
                return True
            case ast.Call(func=ast.Name(id=builtin), args=[], keywords=[]) if builtin in _CONTAINER_BUILDERS:
                return self._builtin(builtin, value)
            case ast.Call(func=function, args=[], keywords=[]):
                return self._proof.imported(function, "weakref.WeakSet")
            case ast.Call(
                func=function, args=[], keywords=[ast.keyword(arg="default_factory", value=ast.Name(id=factory))]
            ):
                return (
                    factory in _CONTAINER_BUILDERS
                    and self._builtin(factory, value)
                    and self._proof.imported(function, "dataclasses.field")
                )
            case _:
                return False

    def _slot_values(self, slot: _Slot) -> list[ast.expr | None] | None:
        if isinstance(slot.owner, ast.ClassDef):
            attributes = self._owned_attributes(slot)
            if attributes is None:
                return None
            targets: list[ast.AST] = [node for node in attributes if isinstance(node.ctx, ast.Store)]
            targets.extend(
                binding
                for binding in self._inventory.bindings.get(slot.owner, {}).get(slot.name, ())
                if isinstance(binding, ast.Name)
            )
        else:
            targets = list(self._inventory.bindings.get(slot.owner, {}).get(slot.name, ()))
        return [self._stored_value(target) for target in targets if not self._declaration(target)]

    def _declaration(self, target: ast.AST) -> bool:
        statement = self._parents.get(target)
        return isinstance(statement, ast.AnnAssign) and statement.value is None

    def _stored_value(self, target: ast.AST) -> ast.expr | None:
        statement = self._parents.get(target)
        match statement:
            case ast.Assign(targets=[only], value=value) if only is target:
                return value
            case ast.AnnAssign(target=annotated, value=value) if annotated is target:
                return value
            case _:
                return None

    def _slot_reads(self, slot: _Slot) -> list[ast.expr] | None:
        if isinstance(slot.owner, ast.ClassDef):
            attributes = self._owned_attributes(slot)
            return None if attributes is None else [node for node in attributes if isinstance(node.ctx, ast.Load)]
        return [
            read
            for read in self._inventory.reads.get(slot.name, ())
            if self._defining_scope(slot.name, read) is slot.owner
        ]

    def _owned_attributes(self, slot: _Slot) -> list[ast.Attribute] | None:
        attributes = self._attributes.get(slot.name, [])
        if any(
            not isinstance(node.value, ast.Name) or self._method_class(node.value) is not slot.owner
            for node in attributes
        ):
            return None
        return attributes

    def _defining_scope(self, name: str, node: ast.AST) -> ast.AST | None:
        scope = self._inventory.scope(node)
        enclosing = False
        while scope is not None:
            visible = not (enclosing and isinstance(scope, ast.ClassDef))
            if visible and name in self._inventory.bindings.get(scope, {}):
                return scope
            enclosing = True
            scope = self._inventory.scope(scope)
        return None

    def _method_class(self, receiver: ast.Name) -> ast.ClassDef | None:
        binding = self._proof.provenance.binding(receiver.id, receiver)
        arguments = self._parents.get(binding) if isinstance(binding, ast.arg) else None
        method = self._parents.get(arguments) if isinstance(arguments, ast.arguments) else None
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) or not isinstance(arguments, ast.arguments):
            return None
        positional = [*arguments.posonlyargs, *arguments.args]
        owner = self._parents.get(method)
        if not positional or positional[0] is not binding or not isinstance(owner, ast.ClassDef):
            return None
        static = any(
            isinstance(decorator, ast.Name) and decorator.id == "staticmethod" for decorator in method.decorator_list
        )
        return None if static else owner

    def _builtin(self, name: str, at: ast.AST) -> bool:
        return self._context.imports.builtin_is_unshadowed(name) and self._proof.provenance.binding(name, at) is None


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    match body:
        case [ast.Expr(value=ast.Constant(value=str())), *rest]:
            return rest
        case _:
            return body


def _collection_element(node: ast.expr, collection: ast.expr) -> bool:
    match collection:
        case ast.List(ctx=ast.Load()) | ast.Tuple(ctx=ast.Load()) | ast.Set():
            return True
        case ast.Dict(values=values):
            return node in values
        case ast.ListComp(elt=element) | ast.SetComp(elt=element) | ast.GeneratorExp(elt=element):
            return element is node
        case ast.DictComp(value=value):
            return value is node
        case _:
            return False


def _removal_callback(member: ast.Attribute, call: ast.Call) -> bool:
    return (
        member.attr in _CONTAINER_REMOVALS
        and member in call.args
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_done_callback"
    )


def _parameter_slot(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, index: int) -> _Successors:
    positional = [*function.args.posonlyargs, *function.args.args]
    return [_Slot(_Kind.TASK, function, positional[index].arg)] if len(positional) > index else None


def _class_method(owner: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    methods = [
        statement
        for statement in owner.body
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef) and statement.name == name
    ]
    return methods[0] if len(methods) == 1 and not methods[0].decorator_list else None


def _reflected_attributes(context: PythonFileContext) -> frozenset[str] | None:
    names: set[str] = set()
    for call in context.nodes(ast.Call):
        if not isinstance(call.func, ast.Name) or call.func.id not in _ATTRIBUTE_REFLECTION:
            continue
        match call.args:
            case [_, ast.Constant(value=str() as name), *_]:
                names.add(name)
            case _:
                return None
    return frozenset(names)


def _private(name: str) -> bool:
    return name.startswith("_") and not name.endswith("__")
