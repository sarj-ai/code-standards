from __future__ import annotations

import ast
import itertools
from typing import TYPE_CHECKING

from sarj_python_lint.rules._annotation_origins import AnnotationOrigins, type_parameter_shadow
from sarj_python_lint.rules._local_source import LocalSourceFacts, unshadowed_import_namespace
from sarj_python_lint.rules._runtime_names import RuntimeNames
from sarj_python_lint.rules._suite_flow import literal_truth, previous_statements, reachable_branch


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


type _FiniteValue = str | int


_LITERAL_PROVIDERS = frozenset({"typing.Literal", "typing_extensions.Literal"})
_MAX_ALIAS_DEPTH = 8
_MAX_SOURCE_OWNERS = 8
_MAX_REJECTION_DEPTH = 8
_MAX_GUARD_DEPTH = 8
_PROCESS_EXITS = frozenset({"sys.exit", "os._exit", "os.abort"})


def finite_literal_dispatches(context: PythonFileContext) -> list[tuple[ast.If | ast.Match, str]]:
    candidates = _partition_candidates(context)
    if not candidates:
        return []
    domains = _LiteralDomains(context)
    findings: list[tuple[ast.If | ast.Match, str]] = []
    for node, subject in candidates:
        declared = domains.parameter_values(subject)
        if declared is None:
            continue
        values = _reachable_values(node, subject.id, declared, context)
        if values is None:
            continue
        match node:
            case ast.If(test=test):
                selected = _selected_values(test)
                if (
                    selected is not None
                    and selected <= declared
                    and 0 < len(selected & values) < len(values)
                    and _productive_partition(node, context)
                ):
                    findings.append((node, subject.id))
            case ast.Match():
                if _implicit_match_values(node, values, context):
                    findings.append((node, subject.id))
    return findings


def _partition_candidates(context: PythonFileContext) -> list[tuple[ast.If | ast.Match, ast.Name]]:
    candidates: list[tuple[ast.If | ast.Match, ast.Name]] = []
    for node in context.nodes(ast.If, ast.Match):
        match node:
            case ast.If(test=ast.Compare(left=ast.Name() as subject, ops=[ast.Eq() | ast.In()])):
                if _selected_values(node.test) is not None and _terminal_partition(node, context):
                    candidates.append((node, subject))
            case ast.Match(subject=ast.Name() as subject):
                if any(_catchall(case) for case in node.cases):
                    candidates.append((node, subject))
            case _:
                pass
    return candidates


def _terminal_partition(node: ast.If, context: PythonFileContext) -> bool:
    parent = context.parents.get(node)
    if (
        isinstance(parent, ast.If)
        and parent.orelse
        and parent.orelse[0] is node
        and context.source_lines[node.lineno - 1].lstrip().startswith("elif")
    ):
        return False
    if not node.body or not isinstance(node.body[-1], ast.Return):
        return False
    if node.orelse:
        return (
            isinstance(node.orelse[-1], ast.Return)
            and not isinstance(node.orelse[0], ast.If)
            and not _same_statements(node.body, node.orelse)
        )
    following = _following_return(node, context)
    return following is not None and not _same_statements(node.body, [following])


def _same_statements(first: list[ast.stmt], second: list[ast.stmt]) -> bool:
    try:
        return [ast.dump(statement) for statement in first] == [ast.dump(statement) for statement in second]
    except RecursionError:
        return False


def _following_return(node: ast.If, context: PythonFileContext) -> ast.Return | None:
    groups: tuple[list[ast.stmt], ...]
    match context.parents.get(node):
        case ast.FunctionDef() | ast.AsyncFunctionDef() as parent:
            groups = (parent.body,)
        case ast.If() as parent:
            groups = parent.body, parent.orelse
        case _:
            return None
    for statements in groups:
        if node not in statements:
            continue
        index = statements.index(node) + 1
        if index < len(statements) and isinstance(following := statements[index], ast.Return):
            return following
    return None


def _productive_partition(node: ast.If, context: PythonFileContext) -> bool:
    following = _following_return(node, context)
    fallback: list[ast.stmt] = node.orelse or ([following] if following is not None else [])
    return rejecting_body(node.body, node, context) is False and rejecting_body(fallback, node, context) is False


def _selected_values(test: ast.expr) -> frozenset[_FiniteValue] | None:
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return None
    value = test.comparators[0]
    if isinstance(test.ops[0], ast.Eq | ast.NotEq):
        selected = _finite_value(value)
        return None if selected is None else frozenset({selected})
    if not isinstance(test.ops[0], ast.In | ast.NotIn):
        return None
    if not isinstance(value, ast.Tuple | ast.List | ast.Set) or not value.elts:
        return None
    return _finite_values(value.elts)


def _guard_values(
    test: ast.expr, subject: str, values: frozenset[_FiniteValue], depth: int = 0
) -> frozenset[_FiniteValue] | None:
    if depth >= _MAX_GUARD_DEPTH:
        return None
    match test:
        case ast.BoolOp():
            return _logical_guard_values(test, subject, values, depth)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            selected = _guard_values(operand, subject, values, depth + 1)
            return None if selected is None else values - selected
        case ast.Compare(left=ast.Name(id=name)) if name == subject:
            selected = _selected_values(test)
            if selected is None:
                return None
            return values - selected if isinstance(test.ops[0], ast.NotEq | ast.NotIn) else values & selected
        case _:
            return None


def _logical_guard_values(
    test: ast.BoolOp, subject: str, values: frozenset[_FiniteValue], depth: int
) -> frozenset[_FiniteValue] | None:
    parts: list[frozenset[_FiniteValue]] = []
    for expression in test.values:
        selected = _guard_values(expression, subject, values, depth + 1)
        if selected is None:
            return None
        parts.append(selected)
    match test.op:
        case ast.And():
            return values.intersection(*parts)
        case ast.Or():
            return frozenset[_FiniteValue]().union(*parts)
        case _:
            return None


def _reachable_values(
    node: ast.If | ast.Match, subject: str, values: frozenset[_FiniteValue], context: PythonFileContext
) -> frozenset[_FiniteValue] | None:
    child: ast.AST = node
    while (parent := context.parents.get(child)) is not None:
        if isinstance(child, ast.stmt):
            remaining = _suite_values(child, parent, subject, values, context)
            if remaining is None:
                return None
            values = remaining
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            break
        child = parent
    return values


def _suite_values(
    node: ast.stmt, parent: ast.AST, subject: str, values: frozenset[_FiniteValue], context: PythonFileContext
) -> frozenset[_FiniteValue] | None:
    completed = parent.body if isinstance(parent, ast.Try | ast.TryStar) and node in parent.orelse else []
    for previous in (*completed, *previous_statements(node, parent)):
        remaining = _preceding_guard_values(previous, subject, values, context)
        if remaining is None:
            return None
        values = remaining
    match parent:
        case ast.If():
            selected = _guard_values(parent.test, subject, values)
            if selected is None:
                return None if _uses_subject(parent.test, subject, context) else values
            return selected if node in parent.body else values - selected
        case ast.While(test=test) if _uses_subject(test, subject, context):
            return None
        case ast.match_case(guard=guard) if _uses_subject(_case_subject(parent, context), subject, context) or (
            guard is not None and _uses_subject(guard, subject, context)
        ):
            return None
        case _:
            return values


def _case_subject(case: ast.match_case, context: PythonFileContext) -> ast.expr:
    owner = context.parents.get(case)
    return owner.subject if isinstance(owner, ast.Match) else ast.Constant(value=None)


def _preceding_guard_values(
    node: ast.stmt,
    subject: str,
    values: frozenset[_FiniteValue],
    context: PythonFileContext,
    depth: int = 0,
    *,
    narrowed: bool = False,
) -> frozenset[_FiniteValue] | None:
    match node:
        case ast.Assert(test=test):
            selected = _guard_values(test, subject, values)
            if selected is None:
                return None if _uses_subject(test, subject, context) else values
            return selected
        case ast.If():
            return _guard_survivors(node, subject, values, context, depth, narrowed=narrowed)
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return values
        case _ if _may_exit(node, context) and (narrowed or _uses_subject(node, subject, context)):
            return None
        case _:
            return values


def _guard_survivors(
    node: ast.If,
    subject: str,
    values: frozenset[_FiniteValue],
    context: PythonFileContext,
    depth: int,
    *,
    narrowed: bool,
) -> frozenset[_FiniteValue] | None:
    if depth >= _MAX_GUARD_DEPTH:
        return None
    selected = _guard_values(node.test, subject, values)
    if selected is None:
        if _uses_subject(node.test, subject, context):
            return None if _may_exit(node, context) else values
        accepted = rejected = values
    else:
        accepted, rejected = selected, values - selected
    body = _branch_survivors(node.body, subject, accepted, context, depth + 1, narrowed=narrowed or accepted != values)
    orelse = _branch_survivors(
        node.orelse, subject, rejected, context, depth + 1, narrowed=narrowed or rejected != values
    )
    return None if body is None or orelse is None else body | orelse


def _branch_survivors(
    body: list[ast.stmt],
    subject: str,
    values: frozenset[_FiniteValue],
    context: PythonFileContext,
    depth: int,
    *,
    narrowed: bool,
) -> frozenset[_FiniteValue] | None:
    for statement in body:
        if _exit_statement(statement, context):
            return frozenset()
        remaining = _preceding_guard_values(statement, subject, values, context, depth, narrowed=narrowed)
        if remaining is None:
            return None
        values = remaining
    return values


def _exit_statement(node: ast.stmt, context: PythonFileContext) -> bool:
    match node:
        case ast.Return() | ast.Raise() | ast.Break() | ast.Continue():
            return True
        case ast.Assert(test=test):
            return literal_truth(test) is False
        case ast.Expr(value=ast.Call() as call):
            return _never_returns(call, context)
        case _:
            return False


def _never_returns(call: ast.Call, context: PythonFileContext) -> bool:
    return _assert_never_call(call, context) or RuntimeNames(context).imported_qualified(call.func) in _PROCESS_EXITS


def _may_exit(node: ast.AST, context: PythonFileContext) -> bool:
    pending: list[tuple[ast.AST, bool]] = [(node, False)]
    while pending:
        child, in_loop = pending.pop()
        if _exits_here(child, context, in_loop=in_loop):
            return True
        pending.extend(_exit_scope_children(child, in_loop=in_loop))
    return False


def _exits_here(node: ast.AST, context: PythonFileContext, *, in_loop: bool) -> bool:
    match node:
        case ast.Break() | ast.Continue():
            return not in_loop
        case ast.Assert():
            return True
        case ast.stmt():
            return _exit_statement(node, context)
        case ast.Call():
            return _never_returns(node, context)
        case _:
            return False


def _exit_scope_children(node: ast.AST, *, in_loop: bool) -> list[tuple[ast.AST, bool]]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
            return []
        case ast.For() | ast.AsyncFor() | ast.While():
            return [(child, in_loop or child in node.body) for child in ast.iter_child_nodes(node)]
        case _:
            return [(child, in_loop) for child in ast.iter_child_nodes(node)]


def _uses_subject(test: ast.AST, subject: str, context: PythonFileContext) -> bool:
    provenance = context.static_resource_provenance
    binding = provenance.binding(subject, test)
    return any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == subject
        and provenance.binding(subject, node) is binding
        for node in ast.walk(test)
    )


def _finite_values(items: list[ast.expr]) -> frozenset[_FiniteValue] | None:
    values: set[_FiniteValue] = set()
    for item in items:
        value = _finite_value(item)
        if value is None:
            return None
        values.add(value)
    return frozenset(values) if values else None


def _finite_value(node: ast.expr) -> _FiniteValue | None:
    match node:
        case ast.Constant(value=(str() | int()) as value) if not isinstance(value, bool):
            return value
        case ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=int() as value)) if not isinstance(value, bool):
            return -value
        case ast.UnaryOp(op=ast.UAdd(), operand=ast.Constant(value=int() as value)) if not isinstance(value, bool):
            return value
        case _:
            return None


def _catchall(case: ast.match_case) -> bool:
    if case.guard is not None:
        return False
    pattern = case.pattern
    while isinstance(pattern, ast.MatchAs):
        if pattern.pattern is None:
            return True
        pattern = pattern.pattern
    return False


def _implicit_match_values(node: ast.Match, values: frozenset[_FiniteValue], context: PythonFileContext) -> bool:
    explicit: set[_FiniteValue] = set()
    for case in node.cases:
        if case.guard is not None:
            return False
        if _catchall(case):
            if rejecting_body(case.body, case, context) is not False:
                return False
            return bool(explicit & values) and not values.issubset(explicit)
        selected = _pattern_values(case.pattern)
        if selected is None:
            return False
        explicit.update(selected)
    return False


def rejecting_body(body: list[ast.stmt], boundary: ast.AST, context: PythonFileContext, depth: int = 0) -> bool | None:
    if depth >= _MAX_REJECTION_DEPTH:
        return None
    decisions = [_rejection_statement(statement, context, depth) for statement in body]
    sink = next((statement for statement, rejects in zip(body, decisions, strict=True) if rejects is True), None)
    if sink is None:
        return _unproven_body_rejection(body, decisions, boundary, context, depth)
    owner = context.static_resource_provenance.scope(sink)
    if owner is None:
        return None
    index = body.index(sink)
    for statement, decision in zip(body[:index], decisions[:index], strict=True):
        escapes = _statement_escapes(statement, boundary, context, owner, depth)
        if escapes is None:
            return None
        if escapes:
            return (
                _unproven_body_rejection([statement], [decision], boundary, context, depth)
                if decision is None
                else False
            )
        if decision is None:
            return None
    suspends = _suspends_rejection(sink, boundary, context, owner, depth)
    return None if suspends is None else not suspends


def _unproven_body_rejection(
    body: list[ast.stmt], decisions: list[bool | None], boundary: ast.AST, context: PythonFileContext, depth: int
) -> bool | None:
    if None not in decisions:
        return False
    owner = context.static_resource_provenance.scope(body[0])
    if owner is None:
        return None
    for statement, decision in zip(body, decisions, strict=True):
        if _suspends_rejection(statement, boundary, context, owner, depth) is True:
            return False
        if decision is None:
            return None
        escape = _statement_escapes(statement, boundary, context, owner, depth)
        if escape is True:
            return False
        if escape is None:
            return None
    return None


def _suspends_rejection(
    statement: ast.stmt, boundary: ast.AST, context: PythonFileContext, owner: ast.AST, depth: int
) -> bool | None:
    suspensions = [
        _escapes_rejection(child, boundary, context, depth + 1)
        for child in ast.walk(statement)
        if isinstance(child, ast.Yield | ast.YieldFrom)
        and context.static_resource_provenance.scope(_evaluation_anchor(child, context)) is owner
    ]
    if True in suspensions:
        return True
    return None if None in suspensions else False


def _statement_escapes(
    statement: ast.stmt, boundary: ast.AST, context: PythonFileContext, owner: ast.AST, depth: int
) -> bool | None:
    escapes = [
        _escapes_rejection(child, boundary, context, depth + 1)
        for child in ast.walk(statement)
        if isinstance(child, ast.Return | ast.Break | ast.Continue | ast.Yield | ast.YieldFrom)
        and context.static_resource_provenance.scope(_evaluation_anchor(child, context)) is owner
    ]
    if True in escapes:
        return True
    return None if None in escapes else False


def _rejection_statement(node: ast.AST, context: PythonFileContext, depth: int = 0) -> bool | None:
    match node:
        case ast.Raise():
            return True
        case ast.Assert(test=test):
            if literal_truth(test) is False:
                return True
            return None if _eager_rejection(node, context) else False
        case ast.Expr(value=ast.Call() as call) | ast.Return(value=ast.Call() as call) | (ast.Call() as call):
            if _assert_never_call(call, context):
                return True
            return None if _eager_rejection(call, context) else False
        case ast.If():
            return None if _eager_rejection(node.test, context) else _rejecting_if(node, context, depth)
        case ast.Try(finalbody=finalizer) | ast.TryStar(finalbody=finalizer) if finalizer:
            rejects = rejecting_body(finalizer, node, context, depth + 1)
            if rejects is True or (rejects is False and isinstance(finalizer[-1], ast.Return | ast.Raise)):
                return rejects
            return None
        case (
            ast.Try()
            | ast.TryStar()
            | ast.With()
            | ast.AsyncWith()
            | ast.For()
            | ast.AsyncFor()
            | ast.While()
            | ast.Match()
            | ast.ClassDef()
        ):
            return None
        case _:
            return None if _eager_rejection(node, context) else False


def _assert_never_call(call: ast.Call, context: PythonFileContext) -> bool:
    root = call.func
    while isinstance(root, ast.Attribute):
        root = root.value
    provenance = context.static_resource_provenance
    if (
        not isinstance(root, ast.Name)
        or root.id in provenance.mutated | provenance.external_bindings
        or type_parameter_shadow(root.id, _evaluation_anchor(call, context), context)
    ):
        return False
    qualified = RuntimeNames(context).imported_qualified(call.func)
    return qualified in {"typing.assert_never", "typing_extensions.assert_never"} and _typing_provider(
        context, qualified
    )


def _eager_rejection(node: ast.AST, context: PythonFileContext) -> bool:
    return any(
        _assert_never_call(child, context) and _reachable_expression(child, node, context)
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
    )


def _rejecting_if(node: ast.If, context: PythonFileContext, depth: int) -> bool | None:
    bodies: tuple[list[ast.stmt], ...]
    match literal_truth(node.test):
        case True:
            bodies = (node.body,)
        case False:
            bodies = (node.orelse,)
        case None:
            bodies = node.body, node.orelse
    branches = [rejecting_body(body, node, context, depth + 1) for body in bodies]
    return None if None in branches else all(branches)


def _escapes_rejection(node: ast.AST, boundary: ast.AST, context: PythonFileContext, depth: int) -> bool | None:
    if depth >= _MAX_REJECTION_DEPTH:
        return None
    if _empty_delegation(node) or _rejection_statement(node, context, depth) is True:
        return False
    if (
        isinstance(node, ast.Return | ast.Yield | ast.YieldFrom)
        and node.value is not None
        and _eager_rejection(node.value, context)
    ):
        return None
    loop_control = isinstance(node, ast.Break | ast.Continue)
    child: ast.AST = node
    parent = context.parents.get(child)
    while parent is not None and parent is not boundary:
        if not reachable_branch(child, parent):
            return False
        if _uncertain_escape_parent(child, parent, context):
            return None
        prefix = _prefix_rejection(child, parent, context, depth)
        if prefix is None:
            return None
        if prefix:
            return False
        if loop_control and isinstance(parent, ast.For | ast.AsyncFor | ast.While) and child in parent.body:
            return False
        child = parent
        parent = context.parents.get(child)
    return parent is boundary


def _uncertain_escape_parent(child: ast.AST, parent: ast.AST, context: PythonFileContext) -> bool:
    match parent:
        case ast.Try() | ast.TryStar():
            return child in parent.orelse
        case (
            ast.ExceptHandler() | ast.Match() | ast.With() | ast.AsyncWith() | ast.For() | ast.AsyncFor() | ast.While()
        ):
            return True
        case _:
            return _earlier_operand_may_reject(child, parent, context)


def _earlier_operand_may_reject(node: ast.AST, parent: ast.AST, context: PythonFileContext) -> bool:
    operands = _preceding_operands(node, parent)
    if operands is None:
        return True
    return any(_eager_rejection(operand, context) for operand in operands)


def _evaluation_anchor(node: ast.AST, context: PythonFileContext) -> ast.AST:
    scope = context.static_resource_provenance.scope(node)
    while isinstance(scope, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
        if not any(child is node for child in ast.walk(scope.generators[0].iter)):
            break
        node = scope
        scope = context.static_resource_provenance.scope(node)
    return node


def _reachable_expression(node: ast.AST, boundary: ast.AST, context: PythonFileContext) -> bool:
    while node is not boundary:
        parent = context.parents.get(node)
        if parent is None or not reachable_branch(node, parent) or not _eager_child(node, parent, boundary, context):
            return False
        node = parent
    return True


def _eager_child(node: ast.AST, parent: ast.AST, boundary: ast.AST, context: PythonFileContext) -> bool:
    match parent:
        case ast.Lambda():
            return node is not parent.body or _invoked_lambda_body(parent, boundary, context)
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.arg() | ast.AnnAssign():
            return _eager_definition_operand(node, parent, context)
        case ast.TypeAlias() | ast.type_param():
            return False
        case ast.GeneratorExp():
            return node is parent.generators[0]
        case ast.ListComp() | ast.SetComp() | ast.DictComp():
            generators = itertools.takewhile(lambda generator: generator is not node, parent.generators)
            return all(
                literal_truth(generator.iter) is not False
                and all(literal_truth(test) is not False for test in generator.ifs)
                for generator in generators
            )
        case ast.comprehension():
            owner = context.parents.get(parent)
            if isinstance(owner, ast.GeneratorExp):
                return parent is owner.generators[0] and node is parent.iter
            if node is parent.iter:
                return True
            preceding = (
                parent.ifs[: parent.ifs.index(node)] if isinstance(node, ast.expr) and node in parent.ifs else ()
            )
            return literal_truth(parent.iter) is not False and all(
                literal_truth(test) is not False for test in preceding
            )
        case _:
            return True


def _eager_definition_operand(
    node: ast.AST,
    parent: ast.FunctionDef | ast.AsyncFunctionDef | ast.arg | ast.AnnAssign,
    context: PythonFileContext,
) -> bool:
    match parent:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return node not in parent.body and (
                node is parent.args or node in parent.decorator_list or not _deferred_annotations(context)
            )
        case ast.arg():
            return not _deferred_annotations(context)
        case ast.AnnAssign():
            return node is parent.value or node is parent.target


def _deferred_annotations(context: PythonFileContext) -> bool:
    return any(
        statement.module == "__future__" and any(alias.name == "annotations" for alias in statement.names)
        for statement in context.nodes(ast.ImportFrom)
    )


def _invoked_lambda_body(node: ast.Lambda, boundary: ast.AST, context: PythonFileContext) -> bool:
    call = context.parents.get(node)
    if node is boundary or not isinstance(call, ast.Call) or call.func is not node:
        return False
    return not any(
        isinstance(child, ast.Yield | ast.YieldFrom)
        and context.static_resource_provenance.scope(_evaluation_anchor(child, context)) is node
        for child in ast.walk(node.body)
    )


def _preceding_operands(node: ast.AST, parent: ast.AST) -> tuple[ast.AST, ...] | None:
    members: tuple[ast.AST, ...]
    match parent:
        case ast.Call(func=func, args=args, keywords=keywords):
            members = (func, *args, *keywords)
        case (
            ast.List(elts=values)
            | ast.Tuple(elts=values)
            | ast.Set(elts=values)
            | ast.BoolOp(values=values)
            | ast.JoinedStr(values=values)
        ):
            members = tuple(values)
        case ast.Dict(keys=keys, values=values):
            members = _present_operands(itertools.chain.from_iterable(zip(keys, values, strict=True)))
        case ast.BinOp(left=left, right=right) | ast.Subscript(value=left, slice=right):
            members = left, right
        case ast.Compare(left=left, comparators=comparators):
            members = (left, *comparators)
        case ast.If() | ast.IfExp():
            return () if node is parent.test else (parent.test,)
        case ast.Raise(exc=left, cause=right) | ast.Assert(test=left, msg=right):
            members = _present_operands((left, right))
        case ast.arguments(defaults=defaults, kw_defaults=kw_defaults):
            members = (*defaults, *_present_operands(kw_defaults))
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            members = (*parent.decorator_list, parent.args)
        case ast.Assign():
            members = (parent.value, *parent.targets)
        case ast.AugAssign():
            members = parent.target, parent.value
        case ast.AnnAssign():
            members = _present_operands((parent.value, parent.target))
        case ast.FormattedValue(value=left, format_spec=right):
            members = _present_operands((left, right))
        case ast.Slice():
            members = _present_operands((parent.lower, parent.upper, parent.step))
        case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
            return () if node is parent.generators[0] else None
        case ast.comprehension():
            return () if node is parent.iter else None
        case (
            ast.Expr()
            | ast.Return()
            | ast.Yield()
            | ast.YieldFrom()
            | ast.UnaryOp()
            | ast.Starred()
            | ast.keyword()
            | ast.Attribute()
            | ast.NamedExpr()
            | ast.Await()
            | ast.Lambda()
        ):
            return ()
        case _:
            return None
    return members[: members.index(node)] if node in members else None


def _present_operands(values: Iterable[ast.AST | None]) -> tuple[ast.AST, ...]:
    return tuple(value for value in values if value is not None)


def _prefix_rejection(node: ast.AST, parent: ast.AST, context: PythonFileContext, depth: int) -> bool | None:
    if not isinstance(node, ast.stmt):
        return False
    prefix = previous_statements(node, parent)
    return rejecting_body(list(prefix), parent, context, depth + 1) if prefix else False


def _empty_delegation(node: ast.AST) -> bool:
    match node:
        case ast.YieldFrom(value=(ast.Tuple() | ast.List() | ast.Set() | ast.Dict()) as value):
            return literal_truth(value) is False
        case ast.YieldFrom(value=ast.Constant(value=(str() | bytes()) as value)):
            return not value
        case _:
            return False


def _pattern_values(pattern: ast.pattern) -> frozenset[_FiniteValue] | None:
    match pattern:
        case ast.MatchAs(pattern=captured) if captured is not None:
            return _pattern_values(captured)
        case ast.MatchValue(value=expression):
            value = _finite_value(expression)
            return None if value is None else frozenset({value})
        case ast.MatchOr(patterns=alternatives):
            values: set[_FiniteValue] = set()
            for alternative in alternatives:
                part = _pattern_values(alternative)
                if part is None:
                    return None
                values.update(part)
            return frozenset(values)
        case _:
            return None


def _parameter_annotation(context: PythonFileContext, subject: ast.Name) -> ast.expr | None:
    owner = context.parents.get(subject)
    while owner is not None:
        match owner:
            case ast.Lambda() | ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                return None
            case ast.FunctionDef(args=arguments) | ast.AsyncFunctionDef(args=arguments):
                for parameter in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
                    if parameter.arg == subject.id:
                        return parameter.annotation
                return None
            case _:
                owner = context.parents.get(owner)
    return None


def _potential_domain(context: PythonFileContext, annotation: ast.expr) -> bool:
    expression = context.annotation_semantics.parse(annotation)
    if isinstance(expression, ast.Subscript):
        return True
    if not isinstance(expression, ast.Name) or context.tree is None:
        return False
    statements = itertools.chain.from_iterable(
        (statement, *statement.body, *statement.orelse) if isinstance(statement, ast.If) else (statement,)
        for statement in context.tree.body
    )
    return any(_declares_alias_name(statement, expression.id) for statement in statements)


def _declares_alias_name(statement: ast.stmt, name: str) -> bool:
    match statement:
        case ast.Assign(targets=targets):
            return any(isinstance(target, ast.Name) and target.id == name for target in targets)
        case ast.AnnAssign(target=ast.Name(id=declared)) | ast.TypeAlias(name=ast.Name(id=declared)):
            return declared == name
        case ast.ImportFrom(names=names):
            return any((alias.asname or alias.name) == name for alias in names)
        case _:
            return False


class _LiteralDomains:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.owners = {context.path: context}
        self.local_source = LocalSourceFacts(source_inputs=context.session.source_inputs)

    def parameter_values(self, subject: ast.Name) -> frozenset[_FiniteValue] | None:
        context = self.context
        annotation = _parameter_annotation(context, subject)
        if annotation is None or not _potential_domain(context, annotation):
            return None
        provenance = context.static_resource_provenance
        parameter = provenance.binding(subject.id, subject)
        if (
            not isinstance(parameter, ast.arg)
            or parameter.annotation is None
            or provenance.scope(parameter) is not provenance.scope(subject)
            or subject.id in provenance.mutated | provenance.external_bindings
        ):
            return None
        return self._values(context, parameter.annotation, subject)

    def _values(
        self,
        context: PythonFileContext,
        annotation: ast.expr,
        at: ast.AST,
        seen: frozenset[ast.AST] = frozenset(),
    ) -> frozenset[_FiniteValue] | None:
        provenance = context.static_resource_provenance
        expression = context.annotation_semantics.parse(annotation)
        if expression is None or len(seen) >= _MAX_ALIAS_DEPTH:
            return None
        if provenance.wildcard or provenance.dynamic_namespace or provenance.mock_namespace_patching:
            return None
        match expression:
            case ast.Subscript():
                values = _literal_values(context, expression, at)
            case ast.Name():
                values = self._alias_values(context, expression, at, seen)
            case _:
                return None
        return None if values is None or provenance.imported_namespace_hazards else values

    def _alias_values(
        self, context: PythonFileContext, expression: ast.Name, at: ast.AST, seen: frozenset[ast.AST]
    ) -> frozenset[_FiniteValue] | None:
        provenance = context.static_resource_provenance
        if (
            type_parameter_shadow(expression.id, at, context)
            or expression.id in provenance.mutated | provenance.external_bindings
        ):
            return None
        binding = provenance.binding(expression.id, at)
        if binding is None or binding in seen or provenance.scope(binding) is not context.tree:
            return None
        parent = context.parents.get(binding)
        if isinstance(binding, ast.Name):
            value = _alias_value(context, binding)
            return self._values(context, value, value, seen | {binding}) if value is not None else None
        if not isinstance(binding, ast.alias) or not isinstance(parent, ast.ImportFrom):
            return None
        return self._imported_values(context, binding, parent, seen)

    def _imported_values(
        self, context: PythonFileContext, binding: ast.alias, parent: ast.ImportFrom, seen: frozenset[ast.AST]
    ) -> frozenset[_FiniteValue] | None:
        path = self.local_source.resolve_module(
            context.path, parent.module, parent.level, facts=context.session.first_party
        )
        owner = self._owner(path, context) if path is not None else None
        if owner is None or owner.tree is None:
            return None
        targets = owner.static_resource_provenance.bindings.get(owner.tree, {}).get(binding.name, ())
        if (
            len(targets) != 1
            or not isinstance(targets[0], ast.Name)
            or binding.name
            in owner.static_resource_provenance.mutated | owner.static_resource_provenance.external_bindings
        ):
            return None
        target = targets[0]
        value = _alias_value(owner, target)
        return self._values(owner, value, value, seen | {binding, target}) if value is not None else None

    def _owner(self, path: Path, context: PythonFileContext) -> PythonFileContext | None:
        if path not in self.owners:
            if len(self.owners) >= _MAX_SOURCE_OWNERS:
                return None
            module = self.local_source.read_module(path)
            if module is None:
                return None
            from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- construct source owners after analysis-session initialization.

            self.owners[path] = PythonFileContext(path, module.source, context.session)
        return self.owners[path]


def _literal_values(
    context: PythonFileContext, expression: ast.Subscript, at: ast.AST
) -> frozenset[_FiniteValue] | None:
    provenance = context.static_resource_provenance
    root = expression.value
    while isinstance(root, ast.Attribute):
        root = root.value
    provider = provenance.binding(root.id, at) if isinstance(root, ast.Name) else None
    if provider is None or provenance.scope(provider) is not context.tree:
        return None
    qualified = AnnotationOrigins(context).qualified(expression.value, at)
    if qualified not in _LITERAL_PROVIDERS or not _typing_provider(context, qualified):
        return None
    items = expression.slice.elts if isinstance(expression.slice, ast.Tuple) else [expression.slice]
    return _finite_values(items)


def _typing_provider(context: PythonFileContext, qualified: str | None) -> bool:
    return qualified is not None and unshadowed_import_namespace(
        context.path, qualified.partition(".")[0], facts=context.session.first_party
    )


def _alias_value(context: PythonFileContext, binding: ast.Name) -> ast.expr | None:
    if (explicit := context.annotation_semantics.aliases.get(binding.id)) is not None:
        return explicit
    parent = context.parents.get(binding)
    if (
        isinstance(parent, ast.Assign)
        and len(parent.targets) == 1
        and isinstance(context.parents.get(parent), ast.Module)
    ):
        return parent.value
    return None
