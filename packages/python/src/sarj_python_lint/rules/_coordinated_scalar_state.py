from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._ast_index import statement_blocks


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _TypeKey = str | ast.ClassDef | tuple[_TypeKey, ...]
_MAX_NODES = 8192
_MAX_FUNCTION_NODES = 4096
_MAX_DEPTH = 8
_SCALAR_TYPES = frozenset({"str", "int", "bool", "bytes", "float"})


@dataclass(frozen=True)
class _AccessPath:
    root: ast.arg
    parts: tuple[str, ...]


@dataclass(frozen=True)
class _Member:
    root: ast.arg
    annotation: _TypeKey
    path: tuple[str, ...]


@dataclass(frozen=True)
class _Assignment:
    member: _Member
    value: bool | None


@dataclass(frozen=True)
class _Pair:
    annotation: _TypeKey
    owner_path: tuple[str, ...]
    resource: str
    flag: str


@dataclass(frozen=True)
class _Reset:
    pair: _Pair
    statement: ast.stmt
    function: _Function


def coordinated_scalar_state_diagnostics(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if context.tree is None or len(context.nodes(ast.AST)) > _MAX_NODES:
        return []
    facts = AnnotationOrigins(context)
    functions = [
        node
        for node in context.tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.decorator_list
        and not node.type_params
        and len(list(ast.walk(node))) <= _MAX_FUNCTION_NODES
    ]
    consumers = _consumers(functions, facts)
    findings: list[Diagnostic] = []
    reported: set[_Pair] = set()
    for reset in _resets(functions, facts):
        if reset.pair in reported or reset.pair not in consumers:
            continue
        consumer, scope = consumers[reset.pair]
        if scope is reset.function or context.suppressions.is_suppressed(reset.statement.lineno, code):
            continue
        reported.add(reset.pair)
        findings.append(_diagnostic(reset, consumer, scope, context, code))
    return findings


def _consumers(functions: list[_Function], facts: AnnotationOrigins) -> dict[_Pair, tuple[ast.If, _Function]]:
    consumers: dict[_Pair, tuple[ast.If, _Function]] = {}
    for function in functions:
        nodes = _owned_nodes(function, facts)
        if any(isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del) for node in nodes):
            continue
        for node in nodes:
            if isinstance(node, ast.If) and (pair := _consumer(node, facts)) is not None:
                consumers.setdefault(pair, (node, function))
    return consumers


def _resets(functions: list[_Function], facts: AnnotationOrigins) -> list[_Reset]:
    resets: list[_Reset] = []
    for function in functions:
        for node in _owned_nodes(function, facts):
            if not isinstance(node, ast.If):
                continue
            for first, second in pairwise(node.body):
                if (pair := _reset(node, first, second, facts)) is not None:
                    resets.append(_Reset(pair, first, function))
    return resets


def _diagnostic(reset: _Reset, consumer: ast.If, scope: _Function, context: PythonFileContext, code: str) -> Diagnostic:
    prefix = ".".join(reset.pair.owner_path)
    fields = ", ".join(f"`{prefix + '.' if prefix else ''}{name}`" for name in (reset.pair.resource, reset.pair.flag))
    return Diagnostic(
        context.path,
        reset.statement.lineno,
        reset.statement.col_offset + 1,
        code,
        f"{fields} have an ownership-guarded None/False reset at {reset.function.name}:{reset.statement.lineno} "
        f"and a joint resource-consuming guard at {scope.name}:{consumer.lineno}. "
        "If these values share one lifetime, use an optional typed owner with a non-null resource; "
        "preserve independent flags and external contracts after review.",
        severity=Severity.WARNING,
    )


def _owned_nodes(function: _Function, facts: AnnotationOrigins) -> list[ast.AST]:
    return [node for node in ast.walk(function) if facts.provenance.scope(node) is function]


def _reset(guard: ast.If, first: ast.stmt, second: ast.stmt, facts: AnnotationOrigins) -> _Pair | None:
    left = _literal_assignment(first, guard, facts)
    right = _literal_assignment(second, guard, facts)
    if left is None or right is None:
        return None
    resource, flag = (left, right) if left.value is None else (right, left)
    if resource.value is not None or flag.value is not False or (pair := _pair(resource.member, flag.member)) is None:
        return None
    match guard.test:
        case ast.Compare(left=left, ops=[ast.Is()], comparators=[right]):
            for owned, expected in ((left, right), (right, left)):
                if _member(owned, guard, facts) != resource.member:
                    continue
                path = _path(expected, guard, facts)
                if path is not None and not path.parts and path.root is not resource.member.root:
                    return pair
        case _:
            pass
    return None


def _literal_assignment(statement: ast.stmt, guard: ast.If, facts: AnnotationOrigins) -> _Assignment | None:
    match statement:
        case ast.Assign(targets=[target], value=ast.Constant(value=value)) if value is None or value is False:
            member = _member(target, guard, facts)
            return _Assignment(member, value) if member is not None else None
        case _:
            return None


def _consumer(node: ast.If, facts: AnnotationOrigins) -> _Pair | None:
    match node.test:
        case ast.BoolOp(op=ast.And(), values=[left, right]):
            for present, flag_test in ((left, right), (right, left)):
                resource = _present_member(present, node, facts)
                flag = _negative_member(flag_test, node, facts)
                if resource is not None and flag is not None and _controls_operation(node, resource, facts):
                    return _pair(resource, flag)
        case _:
            pass
    return None


def _negative_member(flag_test: ast.expr, guard: ast.If, facts: AnnotationOrigins) -> _Member | None:
    if not isinstance(flag_test, ast.UnaryOp) or not isinstance(flag_test.op, ast.Not):
        return None
    return _member(flag_test.operand, guard, facts)


def _controls_operation(guard: ast.If, resource: _Member, facts: AnnotationOrigins) -> bool:
    for statement in guard.body:
        if _unsafe_prefix(statement, facts):
            return False
        if _direct_operation(statement, resource, guard, facts):
            return True
    return False


def _present_member(node: ast.expr, guard: ast.If, facts: AnnotationOrigins) -> _Member | None:
    match node:
        case ast.Compare(left=left, ops=[ast.IsNot()], comparators=[right]):
            if isinstance(right, ast.Constant) and right.value is None:
                return _member(left, guard, facts)
            if isinstance(left, ast.Constant) and left.value is None:
                return _member(right, guard, facts)
        case _:
            pass
    return None


def _direct_operation(statement: ast.stmt, resource: _Member, guard: ast.If, facts: AnnotationOrigins) -> bool:
    match statement:
        case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver))):
            return _member(receiver, guard, facts) == resource
        case _:
            return False


def _unsafe_prefix(statement: ast.stmt, facts: AnnotationOrigins) -> bool:
    if not isinstance(statement, ast.Expr | ast.Pass):
        return True
    for node in ast.walk(statement):
        if isinstance(node, ast.Await | ast.Yield | ast.YieldFrom):
            return True
        if isinstance(node, ast.comprehension) and node.is_async:
            return True
        if isinstance(node, ast.Call) and any(
            facts.builtin(node.func, name, node.func) for name in ("setattr", "delattr")
        ):
            return True
    return False


def _pair(resource: _Member, flag: _Member) -> _Pair | None:
    if resource.root is not flag.root or resource.path[:-1] != flag.path[:-1] or resource.path == flag.path:
        return None
    return _Pair(resource.annotation, resource.path[:-1], resource.path[-1], flag.path[-1])


def _member(node: ast.expr, guard: ast.If, facts: AnnotationOrigins) -> _Member | None:
    path = _path(node, guard, facts)
    if path is None or not path.parts or path.root.annotation is None:
        return None
    annotation = _annotation_key(path.root.annotation, facts)
    return _Member(path.root, annotation, path.parts) if annotation is not None else None


def _path(node: ast.expr, control: ast.stmt, facts: AnnotationOrigins, depth: int = 0) -> _AccessPath | None:
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(node, ast.Attribute):
        parent = _path(node.value, control, facts, depth + 1)
        return _AccessPath(parent.root, (*parent.parts, node.attr)) if parent is not None else None
    if not isinstance(node, ast.Name):
        return None
    binding = facts.provenance.binding(node.id, node)
    if isinstance(binding, ast.arg):
        return _AccessPath(binding, ())
    if not isinstance(binding, ast.Name):
        return None
    statement = facts.context.parents.get(binding)
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        return None
    if not _immediately_precedes(statement, control, facts):
        return None
    return _path(statement.value, statement, facts, depth + 1)


def _immediately_precedes(statement: ast.stmt, control: ast.stmt, facts: AnnotationOrigins) -> bool:
    scope = facts.provenance.scope(statement)
    if not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    return any(
        first is statement and second is control
        for block in statement_blocks(scope.body)
        for first, second in pairwise(block)
    )


def _annotation_key(
    node: ast.expr, facts: AnnotationOrigins, depth: int = 0, *, at: ast.expr | None = None
) -> _TypeKey | None:
    if depth >= _MAX_DEPTH or (resolved := facts.resolve_annotation(node, at=at)) is None:
        return None
    value = resolved.expression
    if isinstance(value, ast.Name | ast.Attribute):
        return _nominal_type_key(value, resolved.at, facts)
    if not isinstance(value, ast.Subscript):
        return None
    elements = value.slice.elts if isinstance(value.slice, ast.Tuple) else [value.slice]
    keys: list[_TypeKey] = []
    for part in [value.value, *elements]:
        key = _annotation_key(part, facts, depth + 1, at=resolved.at)
        if key is None:
            return None
        keys.append(key)
    return tuple(keys)


def _nominal_type_key(value: ast.Name | ast.Attribute, at: ast.expr, facts: AnnotationOrigins) -> _TypeKey | None:
    qualified = facts.qualified(value, at)
    if qualified in {"typing.Any", "typing_extensions.Any", "builtins.object"}:
        return None
    if qualified is not None:
        return qualified
    if not isinstance(value, ast.Name):
        return None
    binding = facts.provenance.binding(value.id, at)
    if isinstance(binding, ast.ClassDef):
        return binding
    if value.id in _SCALAR_TYPES and facts.builtin(value, value.id, at):
        return f"builtins.{value.id}"
    return None
