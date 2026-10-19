from __future__ import annotations

import ast
from dataclasses import dataclass
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
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


type _Kind = Literal["list", "dict", "set"]
type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MAX_BRANCH_DEPTH = 32
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes", "complex"})
_MUTATORS: Final[dict[_Kind, frozenset[str]]] = {
    "list": frozenset({"append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse"}),
    "dict": frozenset({"clear", "pop", "popitem", "setdefault", "update"}),
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
        }
    ),
}
_LINEAR = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete, ast.Expr, ast.Pass)
_DEFERRED_OR_REBINDING = (
    ast.Lambda,
    ast.GeneratorExp,
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
            "Checks undecorated functions and methods with a direct builtin list/dict/set return annotation, typed primitive builtin container inputs, and assignments, returns, raises and structured if branches ending in a value return. Returned element types do not change borrowed input ownership.",
            "Tracks direct aliases and conditional-expression aliases with one proven borrowed owner, item writes/deletions, known builtin mutators and supported in-place operators. Rebinding to a fresh local builder ends the borrowed root's provenance.",
            "Branches retain only origins shared by every continuing path; uncertain joins lose provenance. Proven literal truth selects reachable statement/expression branches and respects boolean short-circuiting; return/raise paths stop flow. Eager comprehensions isolate target bindings; their outermost iterable uses the enclosing scope.",
            "Comprehension operands follow generator/filter order. Empty literal iterables and literal-false filters prevent later operands and bodies from being visited; effects in earlier operands remain checked.",
            "Local annotated assignments visit their value and evaluated target operands, not deferred annotation expressions; an annotation without a value does not perform an item write.",
            "Multiple assignment/deletion targets, unpacking assignments, more than 32 nested branches, loops, try/context-manager orchestration, closures, generators, assignment expressions, opaque type aliases, unknown receivers and dynamic namespaces are excluded.",
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

    def kind(self, annotation: ast.expr | None, *, primitive_elements: bool) -> _Kind | None:
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
        if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
            return None
        match annotation.value.id:
            case "list" | "dict" | "set" as name:
                pass
            case _:
                return None
        if not self.context.imports.builtin_is_unshadowed(name):
            return None
        elements = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        if len(elements) != (2 if name == "dict" else 1):
            return None
        if primitive_elements and not all(
            isinstance(element, ast.Name)
            and element.id in _PRIMITIVES
            and self.context.imports.builtin_is_unshadowed(element.id)
            for element in elements
        ):
            return None
        return name

    def mutations(self, function: _Function) -> list[_Mutation]:
        if (
            function.decorator_list
            or self.kind(function.returns, primitive_elements=False) is None
            or self.provenance.dynamic_namespace
            or not self.provenance.builtin_namespace_untouched
        ):
            return []
        if not function.body or not isinstance(function.body[-1], ast.Return) or function.body[-1].value is None:
            return []
        if isinstance(function.body[-1].value, ast.Constant) and function.body[-1].value.value is None:
            return []
        if not _supported_body(function.body) or any(
            isinstance(node, _DEFERRED_OR_REBINDING) for statement in function.body for node in ast.walk(statement)
        ):
            return []
        parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        origins = {
            argument.arg: _Borrowed(argument.arg, kind)
            for argument in parameters
            if (kind := self.kind(argument.annotation, primitive_elements=True)) is not None
        }
        if not origins:
            return []
        flow = _ContainerFlow(origins)
        for statement in function.body:
            flow.statement(statement)
        return flow.events


@final
class _ContainerFlow:
    def __init__(self, origins: dict[str, _Borrowed]) -> None:
        self.origins = origins
        self.events: list[_Mutation] = []
        self.active = True

    def statement(self, statement: ast.stmt) -> None:
        if not self.active:
            return
        if isinstance(statement, ast.If):
            self._conditional(statement)
            return
        self._evaluate(statement)
        self._bindings(statement)
        if isinstance(statement, ast.Return | ast.Raise):
            self.active = False

    def _evaluate(self, expression: ast.AST) -> None:
        pending = [_Evaluation(expression, self.origins)]
        while pending:
            current = pending.pop()
            event = _mutation(current.node, current.origins)
            if event is not None:
                self.events.append(event)
            pending.extend(_evaluated_children(current))

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
        branch = _ContainerFlow(self.origins.copy())
        for statement in statements:
            branch.statement(statement)
        return branch

    def _bindings(self, statement: ast.stmt) -> None:
        match statement:
            case ast.Assign(targets=targets, value=value):
                origin = _borrowed_origin(value, self.origins)
                for target in targets:
                    self._assign(target, origin)
            case ast.AnnAssign(target=target, value=value) if value is not None:
                self._assign(target, _borrowed_origin(value, self.origins))
            case ast.AugAssign(target=ast.Name(id=name), op=operation):
                owner = self.origins.get(name)
                if owner is not None and _in_place(owner.kind, operation):
                    self.events.append(_Mutation(statement, owner))
                else:
                    self.origins.pop(name, None)
            case ast.Delete(targets=targets):
                for target in targets:
                    self._assign(target, None)
            case _:
                pass

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


def _mutation(node: ast.AST, origins: dict[str, _Borrowed]) -> _Mutation | None:
    match node:
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


def _evaluated_children(current: _Evaluation) -> list[_Evaluation]:
    node, origins = current.node, current.origins
    match node:
        case ast.AnnAssign(target=target, value=value):
            if value is None:
                return [_Evaluation(child, origins) for child in ast.iter_child_nodes(target)]
            return [_Evaluation(target, origins), _Evaluation(value, origins)]
        case ast.BoolOp():
            return _boolean_operands(node, origins)
        case ast.IfExp():
            return _conditional_operands(node, origins)
        case ast.ListComp() | ast.SetComp() | ast.DictComp():
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


def _comprehension_operands(
    node: ast.ListComp | ast.SetComp | ast.DictComp, origins: dict[str, _Borrowed]
) -> list[_Evaluation]:
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


def _comprehension_origins(
    node: ast.ListComp | ast.SetComp | ast.DictComp, origins: dict[str, _Borrowed]
) -> dict[str, _Borrowed]:
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


def _borrowed_origin(value: ast.expr, origins: dict[str, _Borrowed]) -> _Borrowed | None:
    match value:
        case ast.Name(id=name):
            return origins.get(name)
        case ast.IfExp(test=test, body=body, orelse=otherwise):
            truth = _literal_truth(test)
            if truth is not None:
                return _borrowed_origin(body if truth else otherwise, origins)
            first = _borrowed_origin(body, origins)
            second = _borrowed_origin(otherwise, origins)
            return first if first is not None and first == second else None
        case _:
            return None


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
        case ast.Assign(targets=targets):
            return len(targets) != 1 or isinstance(targets[0], ast.Tuple | ast.List)
        case ast.Delete(targets=targets):
            return len(targets) != 1
        case _:
            return False
