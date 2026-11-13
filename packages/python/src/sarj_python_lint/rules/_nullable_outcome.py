from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._pydantic_field_contract import unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_RECORD_BASES = frozenset(
    {
        "pydantic.BaseModel",
        "pydantic.main.BaseModel",
        "typing.TypedDict",
        "typing_extensions.TypedDict",
        "msgspec.Struct",
    }
)
_RECORD_DECORATORS = frozenset({"dataclasses.dataclass", "attrs.define", "attrs.frozen", "attr.s", "attr.dataclass"})
_IDENTITY_DECORATORS = frozenset({"typing.final", "typing_extensions.final"})
_OPTIONAL = frozenset({"typing.Optional", "typing_extensions.Optional"})
_UNION = frozenset({"typing.Union", "typing_extensions.Union"})
_WRAPPERS = frozenset(
    {
        "typing.Annotated",
        "typing_extensions.Annotated",
        "typing.Required",
        "typing_extensions.Required",
        "typing.NotRequired",
        "typing_extensions.NotRequired",
        "typing.ReadOnly",
        "typing_extensions.ReadOnly",
    }
)
_METADATA = frozenset({"typing.ClassVar", "typing_extensions.ClassVar", "typing.Final", "typing_extensions.Final"})
_LITERAL = frozenset({"typing.Literal", "typing_extensions.Literal"})
_ERROR_FIELDS = frozenset({"error", "err", "failure", "exception", "error_message", "failure_reason"})
_SUCCESS_FIELDS = frozenset({"ok", "passed", "success", "succeeded", "is_success", "is_successful"})
_PAYLOAD_FIELDS = frozenset({"value", "data", "payload", "result", "output", "response"})
_SUCCESS_TAGS = frozenset({"ok", "success", "succeeded", "passed", "complete", "completed"})
_ERROR_TAGS = frozenset({"error", "failure", "failed", "rejected"})
_MAX_MEMBERS = 128
_NUMERIC_PRIMITIVES = frozenset({"int", "float", "complex"})
_NUMERIC_DOMAINS = frozenset(
    {
        "decimal.Decimal",
        "fractions.Fraction",
        "pydantic.PositiveFloat",
        "pydantic.NonNegativeFloat",
        "pydantic.NegativeFloat",
        "pydantic.NonPositiveFloat",
        "pydantic.PositiveInt",
        "pydantic.NonNegativeInt",
        "pydantic.NegativeInt",
        "pydantic.NonPositiveInt",
        "pydantic.FiniteFloat",
        "pydantic.StrictFloat",
        "pydantic.StrictInt",
    }
)


def nullable_outcome_diagnostics(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if context.tree is None or context.generated or context.has_wildcard_import:
        return []
    if not any(name in context.symbol_source for name in _ERROR_FIELDS):
        return []
    facts = AnnotationOrigins(context)
    findings: list[Diagnostic] = []
    for model in context.tree.body:
        if not isinstance(model, ast.ClassDef) or not _record(model, facts):
            continue
        first = _outcome_error(model, _record_fields(model, facts), facts)
        if first is None or context.suppressions.is_suppressed(first.lineno, code):
            continue
        findings.append(
            Diagnostic(
                context.path,
                first.lineno,
                first.col_offset + 1,
                code,
                f"{model.name} combines a nullable error with success/payload state; model recoverable outcomes "
                "as Success | Error variants with an explicit discriminator and non-null variant payloads. "
                "Keep partial progress as typed error context when needed.",
                severity=Severity.WARNING,
            )
        )
    return findings


def _outcome_error(
    model: ast.ClassDef, fields: dict[str, ast.AnnAssign], facts: AnnotationOrigins
) -> ast.AnnAssign | None:
    errors = [field for name, field in fields.items() if _failure_field(name, field.annotation, facts)]
    if not errors:
        return None
    flags = any(name in _SUCCESS_FIELDS and _boolean(field.annotation, facts) for name, field in fields.items())
    finite_tag = any(_outcome_tag(field.annotation, facts) for field in fields.values())
    payload = any(name in _PAYLOAD_FIELDS and _nullable(field.annotation, facts) for name, field in fields.items())
    named_result = model.name.endswith(("Result", "Outcome")) and len(fields) > len(errors)
    return errors[0] if flags or finite_tag or payload or named_result else None


def _record_fields(model: ast.ClassDef, facts: AnnotationOrigins) -> dict[str, ast.AnnAssign]:
    fields: dict[str, ast.AnnAssign] = {}
    unique = unique_members(model)
    for member in model.body:
        match member:
            case ast.AnnAssign(target=ast.Name(id=name)) if name in unique and not name.startswith("_"):
                if not _metadata(member.annotation, facts):
                    fields[name] = member
            case _:
                pass
    return fields


def _record(model: ast.ClassDef, facts: AnnotationOrigins) -> bool:
    decorators = [
        facts.qualified(node.func if isinstance(node, ast.Call) else node, node) for node in model.decorator_list
    ]
    if any(name not in _RECORD_DECORATORS | _IDENTITY_DECORATORS for name in decorators):
        return False
    return (len(model.bases) == 1 and facts.qualified(model.bases[0], model.bases[0]) in _RECORD_BASES) or (
        not model.bases and any(name in _RECORD_DECORATORS for name in decorators)
    )


def _metadata(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(annotation)
    return (
        resolved is not None
        and isinstance(resolved.expression, ast.Subscript)
        and facts.qualified(resolved.expression.value, resolved.at) in _METADATA
    )


def _nullable(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    pending = [(annotation, annotation)]
    for _ in range(_MAX_MEMBERS):
        if not pending:
            return False
        node, at = pending.pop()
        resolved = facts.resolve_annotation(node, at=at)
        if resolved is None:
            continue
        node, at = resolved.expression, resolved.at
        match node:
            case ast.Constant(value=None):
                return True
            case ast.Subscript(value=value) if facts.qualified(value, at) in _OPTIONAL:
                return True
            case _:
                pass
        pending.extend((member, at) for member in _nullable_members(node, at, facts))
    return False


def _nullable_members(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> tuple[ast.expr, ...]:
    match node:
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return left, right
        case ast.Subscript(value=value, slice=inner):
            qualified = facts.qualified(value, at)
            members = tuple(inner.elts) if isinstance(inner, ast.Tuple) else (inner,)
            if qualified in _UNION:
                return members
            if qualified in _WRAPPERS:
                return members[:1]
        case _:
            pass
    return ()


def _boolean(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(annotation)
    return resolved is not None and facts.builtin(resolved.expression, "bool", resolved.at)


def _outcome_tag(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(annotation)
    if resolved is None or not isinstance(resolved.expression, ast.Subscript):
        return False
    node = resolved.expression
    if facts.qualified(node.value, resolved.at) not in _LITERAL:
        return False
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    values = {member.value for member in members if isinstance(member, ast.Constant) and isinstance(member.value, str)}
    return bool(values & _SUCCESS_TAGS) and bool(values & _ERROR_TAGS)


def _failure_field(name: str, annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    return name in _ERROR_FIELDS and _nullable(annotation, facts) and not _numeric_error(annotation, facts)


def _numeric_error(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(annotation)
    if resolved is None:
        return False
    members = [
        member
        for member in facts.context.annotation_semantics.transparent_members(resolved.expression)
        if not (isinstance(member, ast.Constant) and member.value is None)
    ]
    return bool(members) and all(_numeric_member(member, resolved.at, facts) for member in members)


def _numeric_member(member: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> bool:
    qualified = facts.qualified(member, at)
    if qualified is not None and qualified.startswith("pydantic.types."):
        qualified = "pydantic." + qualified.removeprefix("pydantic.types.")
    return any(facts.builtin(member, name, at) for name in _NUMERIC_PRIMITIVES) or qualified in _NUMERIC_DOMAINS
