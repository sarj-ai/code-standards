from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, Final, Literal, final, override

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
    is_suppressed,
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


type _Kind = Literal["list", "dict", "set"]
type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _Comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
_MAX_BRANCH_DEPTH = 32
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes", "complex"})
_MUTATORS: Final[dict[_Kind, frozenset[str]]] = {
    "list": frozenset(
        {
            "append",
            "extend",
            "insert",
            "pop",
            "remove",
            "clear",
            "sort",
            "reverse",
            "__setitem__",
            "__delitem__",
            "__iadd__",
            "__imul__",
            "__init__",
        }
    ),
    "dict": frozenset(
        {"clear", "pop", "popitem", "setdefault", "update", "__setitem__", "__delitem__", "__ior__", "__init__"}
    ),
    "set": frozenset(
        {
            "add",
            "clear",
            "discard",
            "pop",
            "remove",
            "update",
            "difference_update",
            "intersection_update",
            "symmetric_difference_update",
            "__iand__",
            "__ior__",
            "__isub__",
            "__ixor__",
            "__init__",
        }
    ),
}
_OPERATOR_WRITES: Final[dict[str, tuple[frozenset[_Kind], int]]] = {
    "operator.setitem": (frozenset({"list", "dict"}), 3),
    "operator.delitem": (frozenset({"list", "dict"}), 2),
    "operator.iadd": (frozenset({"list"}), 2),
    "operator.iconcat": (frozenset({"list"}), 2),
    "operator.imul": (frozenset({"list"}), 2),
    "operator.iand": (frozenset({"set"}), 2),
    "operator.isub": (frozenset({"set"}), 2),
    "operator.ixor": (frozenset({"set"}), 2),
    "operator.ior": (frozenset({"dict", "set"}), 2),
}
_IDENTITY_ARGUMENTS: Final[dict[str, int]] = {
    "typing.cast": 1,
    "typing.assert_type": 0,
    "typing_extensions.cast": 1,
    "typing_extensions.assert_type": 0,
}
_IDENTITY_CALL_ARITY = 2
_LINEAR = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete, ast.Expr, ast.Pass)
_DEFERRED_OR_REBINDING = (
    ast.Lambda,
    ast.NamedExpr,
    ast.Yield,
    ast.YieldFrom,
)


@dataclass(frozen=True, slots=True)
class _Borrowed:
    parameter: str
    kind: _Kind


@dataclass(frozen=True, slots=True)
class _Mutation:
    node: ast.expr | ast.stmt
    owner: _Borrowed


@dataclass(frozen=True, slots=True)
class _Evaluation:
    node: ast.AST
    origins: dict[str, _Borrowed]


@dataclass(frozen=True, slots=True)
class _TerminalPaths:
    terminal: bool
    returns_value: bool


type _AssignedValue = _Borrowed | tuple[_AssignedValue, ...] | None


@final
class NoMutatingContainerTransform(Rule):
    id = "no-mutating-container-transform"
    code = "SARJ520"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return container replacements without mutating borrowed builtin inputs.",
        rationale="A container-valued transformation can change caller aliases before returning its result. Copying after the write leaves the original input changed.",
        remediation="Copy each changed container before writing, return a fresh replacement, or expose a separate command returning None. Keep documented in-place contracts explicit; do not discard the operation or add a dummy assignment.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks undecorated functions and methods with a direct builtin list/dict/set/tuple/frozenset return annotation, typed primitive mutable builtin container inputs, and assignments, returns, raises and structured if branches. Terminal paths must return a value or raise, with at least one value return. Returned container kinds and element types do not change borrowed input ownership.",
            "Direct unshadowed builtin staticmethod/classmethod and canonical typing.final markers preserve the method body in plain class namespaces. Custom, patched, inherited or metaclass-prepared namespaces and multiple binding markers remain excluded.",
            "Wildcard providers, type-parameter names that shadow builtin annotations, and method annotations in inherited, decorated or metaclass-prepared class namespaces do not prove builtin primitive ownership.",
            "Tracks direct aliases and conditional-expression aliases with one proven borrowed owner, item writes/deletions, known builtin mutators and supported in-place operators. Rebinding to a fresh local builder ends the borrowed root's provenance.",
            "Canonical source-resolved operator item writes/deletions and supported in-place functions are checked with positional arity and builtin kind contracts. Patched, escaped or ambiguous operator providers and unknown functional helpers are excluded.",
            "Direct unshadowed builtin list/dict/set mutation descriptors and explicit mutating special methods use the same borrowed-target contract. Unknown classes, read methods and fresh local targets remain excluded.",
            "Source-proven typing and typing_extensions cast/assert_type calls preserve borrowed identity. Two positional arguments are supported; cast also accepts its native typ/val keyword forms. Positional-only assert_type, duplicate/unknown arguments and opaque expansions are not guessed. Copying before the helper still ends borrowed provenance.",
            "Branches retain only origins shared by every continuing path; uncertain joins lose provenance. Proven literal truth selects reachable statement/expression branches and respects boolean short-circuiting; return/raise paths stop flow. Eager comprehensions isolate target bindings; their outermost iterable uses the enclosing scope.",
            "Boolean value selections preserve aliases only when every reachable result has one proven borrowed owner. Unknown conditions that can return unrelated values lose provenance.",
            "Comprehension operands follow generator/filter order. Empty literal iterables and literal-false filters prevent later operands and bodies from being visited; effects in earlier operands remain checked.",
            "Native collection literals supply truth facts for empty literals, explicit members and directly empty expansions. Contents are still evaluated; unknown spreads and application truth methods remain unresolved.",
            "Literal primitive equality/order and singleton identity comparisons supply branch facts. Comparison chains stop before later operands after a proven false link; unknown application comparisons are never evaluated.",
            "Synchronous generator expressions passed as the sole argument of a direct unshadowed native list/tuple/set/frozenset constructor are eagerly consumed and share comprehension flow. Other generator expressions evaluate only their outer iterable at creation; their bodies, filters and later iterables remain deferred, including asynchronous generators.",
            "Local annotated assignments visit their value and evaluated target operands, not deferred annotation expressions; an annotation without a value does not perform an item write.",
            "Chained assignment and deletion targets execute in order. Exact tuple/list literal destructuring captures right-side origins before binding targets in order; opaque, starred and mismatched destructuring remain excluded.",
            "More than 32 nested branches, loops, try/context-manager orchestration, closures, assignment expressions, opaque type aliases, unknown receivers and dynamic namespaces are excluded.",
            "Model-valued inputs and framework validators retain their existing rule owners. Mutation of nested descendants, receiver state, I/O and scalar command/result APIs are outside this rule's supported contract.",
            "Generated and vendored sources are excluded; maintained tests are checked. No automatic copying, deletion, or command rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="sorts-borrowed-input",
                title="Returning a list does not hide its mutation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/counts.py",
                        "def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counts.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="sorts-local-copy",
                title="Build the replacement before changing it",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/counts.py",
                        "def ordered(values: list[int]) -> list[int]:\n    result = list(values)\n    result.sort()\n    return result\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counts.py"),
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
        analysis = _ContainerTransforms(context)
        return [
            Diagnostic(
                path=context.path,
                line=mutation.node.lineno,
                col=mutation.node.col_offset + 1,
                code=self.code,
                message=f"This container-valued transformation mutates borrowed {mutation.owner.kind} input `{mutation.owner.parameter}`; copy before writing or use a command returning None.",
                severity=Severity.WARNING,
            )
            for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
            for mutation in analysis.mutations(function)
            if not is_suppressed(context.source_lines, mutation.node.lineno, self.code)
        ]


@final
class _ContainerTransforms:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)

    @cached_property
    def native_calls(self) -> dict[ast.Call, str]:
        if self.provenance.mock_namespace_patching:
            return {}
        calls: dict[ast.Call, str] = {}
        for call in self.context.nodes(ast.Call):
            if any(isinstance(argument, ast.Starred) for argument in call.args):
                continue
            qualified = self.provenance.runtime_import_name(call.func)
            if qualified is not None:
                calls[call] = qualified
        return calls

    @cached_property
    def argument_writes(self) -> dict[ast.Call, frozenset[_Kind]]:
        calls: dict[ast.Call, frozenset[_Kind]] = {}
        for call, qualified in self.native_calls.items():
            contract = _OPERATOR_WRITES.get(qualified)
            if contract is None:
                continue
            kinds, arity = contract
            if len(call.args) == arity and not call.keywords:
                calls[call] = kinds
        for call in self.context.nodes(ast.Call):
            if not call.args or isinstance(call.args[0], ast.Starred):
                continue
            if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
                continue
            name = call.func.value.id
            for kind, methods in _MUTATORS.items():
                if name == kind and call.func.attr in methods and self.context.imports.builtin_is_unshadowed(name):
                    calls[call] = frozenset({kind})
        return calls

    @cached_property
    def identity_calls(self) -> dict[ast.Call, ast.expr]:
        calls: dict[ast.Call, ast.expr] = {}
        for call, qualified in self.native_calls.items():
            argument = _IDENTITY_ARGUMENTS.get(qualified)
            if argument is None:
                continue
            if len(call.args) == _IDENTITY_CALL_ARITY and not call.keywords:
                calls[call] = call.args[argument]
            elif qualified in {"typing.cast", "typing_extensions.cast"}:
                value = _cast_value_argument(call)
                if value is not None:
                    calls[call] = value
        return calls

    def annotation_builtin(self, name: str, at: _Function) -> bool:
        if not self.context.imports.builtin_is_unshadowed(name):
            return False
        current: ast.AST | None = at
        while current is not None:
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and any(
                isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple) and parameter.name == name
                for parameter in current.type_params
            ):
                return False
            if isinstance(current, ast.ClassDef) and (current.bases or current.keywords or current.decorator_list):
                return False
            current = self.context.parents.get(current)
        return True

    def kind(self, annotation: ast.expr | None, at: _Function, *, primitive_elements: bool) -> _Kind | None:
        annotation = AnnotationSemantics.parse(annotation)
        if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
            return None
        match annotation.value.id:
            case "list" | "dict" | "set" as name:
                pass
            case _:
                return None
        if not self.annotation_builtin(name, at):
            return None
        elements = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        if len(elements) != (2 if name == "dict" else 1):
            return None
        if primitive_elements and not all(
            isinstance(element, ast.Name) and element.id in _PRIMITIVES and self.annotation_builtin(element.id, at)
            for element in elements
        ):
            return None
        return name

    def returns_container(self, annotation: ast.expr | None, at: _Function) -> bool:
        annotation = AnnotationSemantics.parse(annotation)
        if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
            return False
        name = annotation.value.id
        if name not in {"tuple", "frozenset"}:
            return self.kind(annotation, at, primitive_elements=False) is not None
        if not self.annotation_builtin(name, at):
            return False
        elements = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return name == "tuple" or len(elements) == 1

    def deferred(self, node: ast.AST) -> bool:
        return isinstance(node, _DEFERRED_OR_REBINDING)

    def eager_generator(self, node: ast.GeneratorExp) -> bool:
        parent = self.context.parents.get(node)
        return (
            isinstance(parent, ast.Call)
            and parent.args == [node]
            and not parent.keywords
            and isinstance(parent.func, ast.Name)
            and parent.func.id in {"list", "tuple", "set", "frozenset"}
            and self.context.imports.builtin_is_unshadowed(parent.func.id)
            and not self.provenance.mock_namespace_patching
            and not any(generator.is_async for generator in node.generators)
        )

    def decorators_preserve_body(self, function: _Function) -> bool:
        if not function.decorator_list:
            return True
        if not self._plain_class_namespace(function) or self.provenance.mock_namespace_patching:
            return False
        binders = 0
        for decorator in function.decorator_list:
            if self._native_method_binder(decorator):
                binders += 1
            elif self.provenance.runtime_import_name(decorator) != "typing.final":
                return False
        return binders <= 1

    def _plain_class_namespace(self, function: _Function) -> bool:
        owner = self.provenance.scope(function)
        return isinstance(owner, ast.ClassDef) and not (
            owner.bases or owner.keywords or owner.decorator_list or owner.type_params
        )

    def _native_method_binder(self, decorator: ast.expr) -> bool:
        return (
            isinstance(decorator, ast.Name)
            and decorator.id in {"staticmethod", "classmethod"}
            and self.context.imports.builtin_is_unshadowed(decorator.id)
            and self.provenance.runtime_binding(decorator.id, decorator) is None
        )

    def mutations(self, function: _Function) -> list[_Mutation]:
        if (
            not self.decorators_preserve_body(function)
            or not self.returns_container(function.returns, function)
            or self.provenance.dynamic_namespace
            or self.provenance.wildcard
            or not self.provenance.builtin_namespace_untouched
        ):
            return []
        if not _supported_body(function.body) or any(
            self.deferred(node) for statement in function.body for node in ast.walk(statement)
        ):
            return []
        ending = _terminal_paths(function.body)
        if not ending.terminal or not ending.returns_value:
            return []
        parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        origins = {
            argument.arg: _Borrowed(argument.arg, kind)
            for argument in parameters
            if (kind := self.kind(argument.annotation, function, primitive_elements=True)) is not None
        }
        if not origins:
            return []
        eager_generators = frozenset(
            node for node in ast.walk(function) if isinstance(node, ast.GeneratorExp) and self.eager_generator(node)
        )
        flow = _ContainerFlow(origins, self.argument_writes, self.identity_calls, eager_generators)
        for statement in function.body:
            flow.statement(statement)
        return flow.events


@final
class _ContainerFlow:
    def __init__(
        self,
        origins: dict[str, _Borrowed],
        operator_calls: Mapping[ast.Call, frozenset[_Kind]],
        identity_calls: Mapping[ast.Call, ast.expr],
        eager_generators: frozenset[ast.GeneratorExp],
    ) -> None:
        self.origins = origins
        self.operator_calls = operator_calls
        self.identity_calls = identity_calls
        self.eager_generators = eager_generators
        self.events: list[_Mutation] = []
        self.active = True

    def statement(self, statement: ast.stmt) -> None:
        if not self.active:
            return
        match statement:
            case ast.If():
                self._conditional(statement)
                return
            case ast.Assign():
                self._evaluate(statement.value)
                value = self._assigned_value(statement.value)
                for target in statement.targets:
                    self._assignment(target, value)
                return
            case ast.Delete():
                for target in statement.targets:
                    self._assignment(target, None)
                return
            case _:
                pass
        self._evaluate(statement)
        self._bindings(statement)
        if isinstance(statement, ast.Return | ast.Raise):
            self.active = False

    def _evaluate(self, expression: ast.AST) -> None:
        pending = [_Evaluation(expression, self.origins)]
        while pending:
            current = pending.pop()
            event = _mutation(current.node, current.origins, self.operator_calls)
            if event is not None:
                self.events.append(event)
            pending.extend(_evaluated_children(current, self.eager_generators))

    def _conditional(self, statement: ast.If) -> None:
        self._evaluate(statement.test)
        truth = _literal_truth(statement.test)
        if truth is not None:
            chosen = self._fork(statement.body if truth else statement.orelse)
            self.origins, self.active = chosen.origins, chosen.active
            self.events.extend(chosen.events)
            return
        branches = [self._fork(statement.body), self._fork(statement.orelse)]
        self.events.extend(event for branch in branches for event in branch.events)
        continuing = [branch for branch in branches if branch.active]
        self.active = bool(continuing)
        if not continuing:
            self.origins = {}
            return
        first, *rest = continuing
        self.origins = {
            name: owner
            for name, owner in first.origins.items()
            if all(branch.origins.get(name) == owner for branch in rest)
        }

    def _fork(self, statements: list[ast.stmt]) -> _ContainerFlow:
        branch = _ContainerFlow(self.origins.copy(), self.operator_calls, self.identity_calls, self.eager_generators)
        for statement in statements:
            branch.statement(statement)
        return branch

    def _bindings(self, statement: ast.stmt) -> None:
        match statement:
            case ast.AnnAssign(target=target, value=value) if value is not None:
                self._assign(target, _borrowed_origin(value, self.origins, self.identity_calls))
            case ast.AugAssign(target=ast.Name(id=name), op=operation):
                owner = self.origins.get(name)
                if owner is not None and _in_place(owner.kind, operation):
                    self.events.append(_Mutation(statement, owner))
                else:
                    self.origins.pop(name, None)
            case _:
                pass

    def _assigned_value(self, value: ast.expr) -> _AssignedValue:
        if isinstance(value, ast.Tuple | ast.List):
            return tuple(self._assigned_value(element) for element in value.elts)
        return _borrowed_origin(value, self.origins, self.identity_calls)

    def _assignment(self, target: ast.expr, value: _AssignedValue) -> None:
        if isinstance(target, ast.Tuple | ast.List):
            values = (
                value if isinstance(value, tuple) and len(value) == len(target.elts) else (None,) * len(target.elts)
            )
            for element, assigned in zip(target.elts, values, strict=True):
                self._assignment(element, assigned)
            return
        self._evaluate(target)
        self._assign(target, value if isinstance(value, _Borrowed) else None)

    def _assign(self, target: ast.expr, owner: _Borrowed | None) -> None:
        match target:
            case ast.Name(id=name):
                self.origins.pop(name, None)
                if owner is not None:
                    self.origins[name] = owner
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                for element in elements:
                    self._assign(element, None)
            case ast.Starred(value=value):
                self._assign(value, None)
            case ast.Attribute(value=ast.Name(id=name)):
                original = self.origins.get(name)
                if original is not None:
                    self.origins = {key: value for key, value in self.origins.items() if value != original}
            case _:
                pass


def _mutation(
    node: ast.AST, origins: dict[str, _Borrowed], operator_calls: Mapping[ast.Call, frozenset[_Kind]]
) -> _Mutation | None:
    match node:
        case ast.Call(args=[ast.Name(id=name), *_]) if node in operator_calls:
            owner = origins.get(name)
            if owner is not None and owner.kind in operator_calls[node]:
                return _Mutation(node, owner)
        case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=method)):
            owner = origins.get(name)
            if owner is not None and method in _MUTATORS[owner.kind]:
                return _Mutation(node, owner)
        case ast.Subscript(value=ast.Name(id=name), ctx=ast.Store() | ast.Del()):
            owner = origins.get(name)
            if owner is not None and owner.kind != "set":
                return _Mutation(node, owner)
        case _:
            pass
    return None


def _evaluated_children(current: _Evaluation, eager_generators: frozenset[ast.GeneratorExp]) -> list[_Evaluation]:
    node, origins = current.node, current.origins
    match node:
        case ast.AnnAssign(target=target, value=value):
            if value is None:
                return [_Evaluation(child, origins) for child in ast.iter_child_nodes(target)]
            return [_Evaluation(target, origins), _Evaluation(value, origins)]
        case ast.BoolOp():
            return _boolean_operands(node, origins)
        case ast.Compare():
            return _comparison_operands(node, origins)
        case ast.IfExp():
            return _conditional_operands(node, origins)
        case ast.GeneratorExp() if node not in eager_generators:
            return [_Evaluation(node.generators[0].iter, origins)]
        case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
            return _comprehension_operands(node, origins)
        case _:
            return [_Evaluation(child, origins) for child in ast.iter_child_nodes(node)]


def _boolean_operands(node: ast.BoolOp, origins: dict[str, _Borrowed]) -> list[_Evaluation]:
    operands: list[_Evaluation] = []
    for operand in node.values:
        operands.append(_Evaluation(operand, origins))
        truth = _literal_truth(operand)
        if (isinstance(node.op, ast.And) and truth is False) or (isinstance(node.op, ast.Or) and truth is True):
            break
    return operands


def _conditional_operands(node: ast.IfExp, origins: dict[str, _Borrowed]) -> list[_Evaluation]:
    truth = _literal_truth(node.test)
    if truth is None:
        alternatives = [node.body, node.orelse]
    elif truth:
        alternatives = [node.body]
    else:
        alternatives = [node.orelse]
    return [_Evaluation(node.test, origins), *(_Evaluation(child, origins) for child in alternatives)]


def _comparison_operands(node: ast.Compare, origins: dict[str, _Borrowed]) -> list[_Evaluation]:
    left = node.left
    operands = [_Evaluation(left, origins)]
    for operation, right in zip(node.ops, node.comparators, strict=True):
        operands.append(_Evaluation(right, origins))
        if _literal_comparison(left, operation, right) is False:
            break
        left = right
    return operands


def _comprehension_operands(node: _Comprehension, origins: dict[str, _Borrowed]) -> list[_Evaluation]:
    scoped = _comprehension_origins(node, origins)
    operands = [_Evaluation(node.generators[0].iter, origins)]
    for index, generator in enumerate(node.generators):
        if index:
            operands.append(_Evaluation(generator.iter, scoped))
        if _empty_literal_iterable(generator.iter):
            return operands
        operands.append(_Evaluation(generator.target, scoped))
        for condition in generator.ifs:
            operands.append(_Evaluation(condition, scoped))
            if _literal_truth(condition) is False:
                return operands
    if isinstance(node, ast.DictComp):
        operands.extend((_Evaluation(node.key, scoped), _Evaluation(node.value, scoped)))
    else:
        operands.append(_Evaluation(node.elt, scoped))
    return operands


def _comprehension_origins(node: _Comprehension, origins: dict[str, _Borrowed]) -> dict[str, _Borrowed]:
    targets = {
        child.id
        for generator in node.generators
        for child in ast.walk(generator.target)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }
    return {name: owner for name, owner in origins.items() if name not in targets}


def _empty_literal_iterable(expression: ast.expr) -> bool:
    match expression:
        case ast.List(elts=[]) | ast.Tuple(elts=[]) | ast.Set(elts=[]) | ast.Dict(keys=[]):
            return True
        case ast.Constant(value=str() | bytes() as value):
            return not value
        case _:
            return False


def _literal_truth(expression: ast.expr) -> bool | None:
    match expression:
        case ast.Constant(value=value):
            return bool(value)
        case ast.List() | ast.Tuple() | ast.Set() | ast.Dict():
            return _literal_collection_truth(expression)
        case ast.Compare():
            return _comparison_truth(expression)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            truth = _literal_truth(operand)
            return None if truth is None else not truth
        case ast.BoolOp(op=operation, values=operands):
            truth = None
            for operand in operands:
                truth = _literal_truth(operand)
                if (
                    truth is None
                    or (isinstance(operation, ast.And) and not truth)
                    or (isinstance(operation, ast.Or) and truth)
                ):
                    break
            return truth
        case ast.IfExp(test=test, body=body, orelse=otherwise):
            truth = _literal_truth(test)
            return None if truth is None else _literal_truth(body if truth else otherwise)
        case _:
            return None


def _comparison_truth(expression: ast.Compare) -> bool | None:
    left = expression.left
    for operation, right in zip(expression.ops, expression.comparators, strict=True):
        truth = _literal_comparison(left, operation, right)
        if truth is not True:
            return truth
        left = right
    return True


def _literal_collection_truth(expression: ast.List | ast.Tuple | ast.Set | ast.Dict) -> bool | None:
    if isinstance(expression, ast.Dict):
        explicit_member = any(key is not None for key in expression.keys)
        empty = all(_empty_literal_iterable(value) for value in expression.values)
    else:
        explicit_member = any(not isinstance(element, ast.Starred) for element in expression.elts)
        empty = all(
            isinstance(element, ast.Starred) and _empty_literal_iterable(element.value) for element in expression.elts
        )
    if explicit_member:
        return True
    return False if empty else None


def _literal_comparison(left: ast.expr, operation: ast.cmpop, right: ast.expr) -> bool | None:
    if not isinstance(left, ast.Constant) or not isinstance(right, ast.Constant):
        return None
    first, second = left.value, right.value
    match operation:
        case ast.Eq():
            return first == second
        case ast.NotEq():
            return first != second
        case ast.Is() | ast.IsNot():
            return _singleton_identity(first, second, negated=isinstance(operation, ast.IsNot))
        case _:
            pass
    match first, second:
        case (int() | float() as a, int() | float() as b):
            return _scalar_order(a, operation, b)
        case (str() as a, str() as b):
            return _scalar_order(a, operation, b)
        case (bytes() as a, bytes() as b):
            return _scalar_order(a, operation, b)
        case _:
            return None


def _scalar_order[T: (int, float, str, bytes)](left: T, operation: ast.cmpop, right: T) -> bool | None:
    match operation:
        case ast.Lt():
            return left < right
        case ast.LtE():
            return left <= right
        case ast.Gt():
            return left > right
        case ast.GtE():
            return left >= right
        case _:
            return None


def _singleton_identity(left: object, right: object, *, negated: bool) -> bool | None:
    if not ((left is None or isinstance(left, bool)) and (right is None or isinstance(right, bool))):
        return None
    same = left is right
    return not same if negated else same


def _borrowed_origin(
    value: ast.expr, origins: dict[str, _Borrowed], identity_calls: Mapping[ast.Call, ast.expr]
) -> _Borrowed | None:
    while isinstance(value, ast.Call) and value in identity_calls:
        value = identity_calls[value]
    match value:
        case ast.Name(id=name):
            return origins.get(name)
        case ast.IfExp(test=test, body=body, orelse=otherwise):
            truth = _literal_truth(test)
            if truth is not None:
                return _borrowed_origin(body if truth else otherwise, origins, identity_calls)
            first = _borrowed_origin(body, origins, identity_calls)
            second = _borrowed_origin(otherwise, origins, identity_calls)
            return first if first is not None and first == second else None
        case ast.BoolOp():
            return _boolean_origin(value, origins, identity_calls)
        case _:
            return None


def _boolean_origin(
    value: ast.BoolOp, origins: dict[str, _Borrowed], identity_calls: Mapping[ast.Call, ast.expr]
) -> _Borrowed | None:
    candidates: list[_Borrowed | None] = []
    for index, operand in enumerate(value.values):
        truth = _literal_truth(operand)
        continues = isinstance(value.op, ast.And) if truth else isinstance(value.op, ast.Or)
        if truth is None or not continues or index == len(value.values) - 1:
            candidates.append(_borrowed_origin(operand, origins, identity_calls))
        if truth is not None and not continues:
            break
    first, *rest = candidates
    return first if first is not None and all(candidate == first for candidate in rest) else None


def _in_place(kind: _Kind, operation: ast.operator) -> bool:
    return (
        (kind == "list" and isinstance(operation, ast.Add | ast.Mult))
        or (kind == "dict" and isinstance(operation, ast.BitOr))
        or (kind == "set" and isinstance(operation, ast.BitOr | ast.BitAnd | ast.BitXor | ast.Sub))
    )


def _supported_body(statements: list[ast.stmt]) -> bool:
    pending = [(statement, 0) for statement in statements]
    while pending:
        statement, depth = pending.pop()
        if isinstance(statement, ast.If):
            if depth >= _MAX_BRANCH_DEPTH:
                return False
            pending.extend((child, depth + 1) for child in (*statement.body, *statement.orelse))
        elif _compound_targets(statement) or not isinstance(statement, (*_LINEAR, ast.Return, ast.Raise)):
            return False
    return True


def _compound_targets(statement: ast.stmt) -> bool:
    match statement:
        case ast.Assign(targets=targets, value=value):
            return any(not _supported_assignment(target, value) for target in targets)
        case _:
            return False


def _supported_assignment(target: ast.expr, value: ast.expr) -> bool:
    if not isinstance(target, ast.Tuple | ast.List):
        return not isinstance(target, ast.Starred)
    if not isinstance(value, ast.Tuple | ast.List) or len(target.elts) != len(value.elts):
        return False
    return all(
        not isinstance(element, ast.Starred)
        and not isinstance(assigned, ast.Starred)
        and _supported_assignment(element, assigned)
        for element, assigned in zip(target.elts, value.elts, strict=True)
    )


def _terminal_paths(statements: list[ast.stmt]) -> _TerminalPaths:
    if not statements:
        return _TerminalPaths(terminal=False, returns_value=False)
    match statements[-1]:
        case ast.Return(value=value):
            returns_value = value is not None and not (isinstance(value, ast.Constant) and value.value is None)
            return _TerminalPaths(terminal=returns_value, returns_value=returns_value)
        case ast.Raise():
            return _TerminalPaths(terminal=True, returns_value=False)
        case ast.If(body=body, orelse=otherwise):
            first = _terminal_paths(body)
            second = _terminal_paths(otherwise)
            return _TerminalPaths(
                terminal=first.terminal and second.terminal,
                returns_value=first.returns_value or second.returns_value,
            )
        case _:
            return _TerminalPaths(terminal=False, returns_value=False)


def _cast_value_argument(call: ast.Call) -> ast.expr | None:
    if len(call.args) > _IDENTITY_CALL_ARITY:
        return None
    values: dict[str, ast.expr] = dict(zip(("typ", "val"), call.args, strict=False))
    for keyword in call.keywords:
        if keyword.arg not in {"typ", "val"} or keyword.arg in values:
            return None
        values[keyword.arg] = keyword.value
    return values.get("val") if values.keys() == {"typ", "val"} else None
