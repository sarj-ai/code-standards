from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._local_source import unshadowed_import_namespace
from sarj_python_lint.rules._opaque_contracts import statement_dominates
from sarj_python_lint.rules._type_guard_symbols import guard_symbols_ambiguous


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules.require_pydantic_for_mapping_shape import MappingShapeFacts


_MESSAGE_TYPES = frozenset({"livekit.agents.llm.ChatMessage", "livekit.agents.llm.chat_context.ChatMessage"})
_MODULE_ROOTS = frozenset(owner.partition(".")[0] for owner in _MESSAGE_TYPES)
_MAX_GET_ARGUMENTS = 2
_PATCH_TARGETS = frozenset(
    {"unittest.mock.patch", "unittest.mock.patch.object", "unittest.mock.patch.multiple", "unittest.mock.patch.dict"}
)


def sdk_metadata_reads(facts: MappingShapeFacts) -> list[ast.Call]:
    context = facts.context
    candidates = _conditional_reads(context)
    if not candidates or not any(
        target.module == "livekit" or target.module.startswith("livekit.")
        for target in context.module_imports.bindings.values()
    ):
        return []
    if not _api_contract_available(facts):
        return []
    assertions = context.nodes(ast.Assert)
    closed: dict[ast.AST, bool] = {}
    found: dict[ast.AST, ast.Call] = {}
    for call in candidates:
        if facts.raw_boundary(call) or context.suppressions.is_suppressed(call.lineno, "SARJ535"):
            continue
        receiver = call.func
        if not isinstance(receiver, ast.Attribute) or not isinstance(receiver.value, ast.Attribute):
            continue
        value = receiver.value.value
        if isinstance(value, ast.Name) and (binding := _typed_receiver(value, call, facts, assertions, closed)):
            found.setdefault(binding, call)
    return list(found.values())


def _conditional_reads(context: PythonFileContext) -> list[ast.Call]:
    candidates = [
        call
        for call in context.nodes(ast.Call)
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "extra"
        and isinstance(call.func.value.value, ast.Name)
        and 1 <= len(call.args) <= _MAX_GET_ARGUMENTS
        and not call.keywords
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and _condition(call, context)
    ]
    return sorted(candidates, key=lambda node: (node.lineno, node.col_offset))


def _api_contract_available(facts: MappingShapeFacts) -> bool:
    if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
        return False
    if guard_symbols_ambiguous(facts.context, frozenset({"isinstance"})) or not _external_api(facts):
        return False
    return not any(
        facts.qualified(call.func, call) in _PATCH_TARGETS for call in facts.context.nodes(ast.Call)
    ) and _class_uses_are_stable(facts)


def _external_api(facts: MappingShapeFacts) -> bool:
    context = facts.context
    return all(
        unshadowed_import_namespace(context.path, namespace, facts=context.session.first_party)
        for namespace in _MODULE_ROOTS
    )


def _class_uses_are_stable(facts: MappingShapeFacts) -> bool:
    context = facts.context
    for node in context.nodes(ast.Name, ast.Attribute):
        if facts.qualified(node, node) not in _MESSAGE_TYPES:
            continue
        parent = context.parents.get(node)
        if isinstance(parent, ast.Call) and (
            parent.func is node or (_type_test(parent, facts) is not None and parent.args[1] is node)
        ):
            continue
        current: ast.AST = node
        while isinstance(parent, ast.Subscript | ast.BinOp | ast.Tuple | ast.List):
            current, parent = parent, context.parents.get(parent)
        match parent:
            case ast.arg(annotation=annotation) | ast.AnnAssign(annotation=annotation) if annotation is current:
                continue
            case ast.FunctionDef(returns=annotation) | ast.AsyncFunctionDef(returns=annotation) if (
                annotation is current
            ):
                continue
            case _:
                return False
    return True


def _condition(call: ast.Call, context: PythonFileContext) -> bool:
    current: ast.AST = call
    while (parent := context.parents.get(current)) is not None:
        if isinstance(parent, ast.If | ast.While | ast.IfExp):
            return parent.test is current
        if not isinstance(parent, ast.BoolOp) and not (
            isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)
        ):
            return False
        current = parent
    return False


def _type_test(node: ast.AST | None, facts: MappingShapeFacts) -> ast.Call | None:
    match node:
        case ast.Call(func=func, args=[_, _], keywords=[]) if facts.builtin(func, "isinstance", node):
            return node
        case _:
            return None


def _typed_receiver(
    value: ast.Name,
    call: ast.Call,
    facts: MappingShapeFacts,
    assertions: Sequence[ast.Assert],
    closed: dict[ast.AST, bool],
) -> ast.AST | None:
    binding = facts.provenance.runtime_binding(value.id, value)
    if binding is None:
        return None
    if binding not in closed:
        closed[binding] = _closed_receiver(value, binding, facts)
    if not closed[binding]:
        return None
    annotation = binding.annotation if isinstance(binding, ast.arg) else None
    parent = facts.context.parents.get(binding)
    if isinstance(parent, ast.AnnAssign):
        annotation = parent.annotation
    if annotation is not None and _message_annotation(annotation, facts):
        return binding
    for assertion in assertions:
        test = _type_test(assertion.test, facts)
        if test is None:
            continue
        if (
            _same_binding(test.args[0], value, facts)
            and _message_annotation(test.args[1], facts)
            and statement_dominates(assertion, call, facts.context)
        ):
            return binding
    return None


def _closed_receiver(value: ast.Name, binding: ast.AST, facts: MappingShapeFacts) -> bool:
    if value.id in facts.provenance.mutated | facts.provenance.external_bindings:
        return False
    return all(_receiver_read(read, facts) for read in facts.provenance.binding_reads(value.id, binding))


def _receiver_read(read: ast.Name, facts: MappingShapeFacts) -> bool:
    parent = facts.context.parents.get(read)
    if _type_test(parent, facts) is not None and isinstance(parent, ast.Call) and parent.args[0] is read:
        return True
    if not isinstance(parent, ast.Attribute) or parent.value is not read or not isinstance(parent.ctx, ast.Load):
        return False
    outer = facts.context.parents.get(parent)
    if isinstance(outer, ast.Call) and outer.func is parent:
        return False
    if parent.attr != "extra":
        return True
    return (
        isinstance(outer, ast.Attribute)
        and outer.attr == "get"
        and isinstance(call := facts.context.parents.get(outer), ast.Call)
        and call.func is outer
    )


def _message_annotation(annotation: ast.expr, facts: MappingShapeFacts) -> bool:
    resolved = facts.resolve_annotation(annotation)
    return resolved is not None and facts.qualified(resolved.expression, resolved.at) in _MESSAGE_TYPES


def _same_binding(left: ast.expr, right: ast.Name, facts: MappingShapeFacts) -> bool:
    return (
        isinstance(left, ast.Name)
        and (binding := facts.provenance.runtime_binding(left.id, left)) is not None
        and binding is facts.provenance.runtime_binding(right.id, right)
    )
