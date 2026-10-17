from __future__ import annotations

import ast
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
    is_suppressed,
)
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._resource_provenance import ResourceProvenance
from sarj_python_lint.rules._type_guard_symbols import (
    builtin_guard_symbol,
    guard_symbols_ambiguous,
    unique_guard_function_names,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


_BUILTINS = frozenset({"object", "str", "int", "bool", "float", "bytes", "dict", "list", "set", "tuple", "isinstance"})
_TYPING = frozenset(
    {
        "TypeGuard",
        "TypeIs",
        "TypedDict",
        "NamedTuple",
        "Required",
        "NotRequired",
        "ReadOnly",
        "Annotated",
        "Literal",
        "Optional",
        "Union",
    }
)
_WRAPPERS = frozenset({"Required", "NotRequired", "ReadOnly"})
_MAX_ANNOTATION_NODES = 256
_ISINSTANCE_ARITY = 2
_BAD = "from typing import TypedDict, TypeGuard\nclass Payload(TypedDict):\n    text: str\ndef is_payload(value: object) -> TypeGuard[Payload]:\n    return isinstance(value, dict)\n"
_GOOD = _BAD.replace("TypeGuard[Payload]", "TypeGuard[dict[object, object]]")
_NAMED = _BAD.replace("TypedDict", "NamedTuple").replace("value, dict", "value, tuple")


@final
class NoShallowRecordTypeGuard(Rule):
    id = "no-shallow-record-type-guard"
    code = "SARJ514"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not promise a local record's contract from a container-only check.",
        rationale="An empty dict or tuple passes a container-only check while lacking a TypedDict's required key or a NamedTuple's named attributes and record API. A guard annotation makes callers trust that missing contract.",
        remediation="Validate the required record shape and field contracts, or keep an honest container return type. For a NamedTuple, checking its actual class can establish nominal membership; tuple membership alone cannot.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks unique, undecorated, non-generic module functions with one object parameter and a sole direct builtin isinstance check of that same parameter, optionally after a docstring.",
            "Targets must be stable, unescaped local class declarations directly inheriting import-proven typing or typing_extensions TypedDict or NamedTuple. TypedDict targets need a required key; every NamedTuple target promises its nominal record API. Inheritance, class decorators, methods, aliases, imported targets and opaque field annotations abstain.",
            "TypedDict total=False and NotRequired-only declarations are preserved. Canonical Required and ReadOnly wrappers are recognized; unknown class options and computed requiredness abstain. NamedTuple constructor defaults do not make named attributes optional, and even zero-field records promise methods absent from plain tuple.",
            "Only bounded builtin and canonical typing field annotations with literal metadata are analyzed. Class-scope shadows, record rebinding, namespace mutation or escape, and repeated function names abstain conservatively.",
            "Constrained input types, public overload contracts, content validators and helpers are not inferred. This rule proves missing shape; it does not claim that key presence alone validates field contents.",
            "Authored tests remain checked; generated and vendor files are excluded. No autofix invents validation or changes narrowing at callers.",
        ),
        examples=(
            RuleExample(
                example_id="unchecked-required-key",
                title="A dictionary check does not prove a required key",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/guards.py", _BAD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="honest-container-contract",
                title="Unchecked contents retain a container contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/guards.py", _GOOD),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="unchecked-named-attribute",
                scenario="named-tuple-shape",
                title="Tuple membership does not establish a named record",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/guards.py", _NAMED),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nominal-named-tuple-membership",
                scenario="named-tuple-shape",
                title="Check the actual named tuple class for nominal membership",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/guards.py", _NAMED.replace("value, tuple", "value, Payload")),),
                focus_path=PurePosixPath("app/guards.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        signals = context.symbol_source
        if context.tree is None or context.generated or not ("TypeGuard" in signals or "TypeIs" in signals):
            return []
        if not ("TypedDict" in signals or "NamedTuple" in signals) or guard_symbols_ambiguous(
            context, _BUILTINS, typing_symbols=_TYPING
        ):
            return []
        provenance = ResourceProvenance(context, require_static_namespace=True)
        records = _record_containers(context, provenance)
        unique_names = unique_guard_function_names(context)
        findings: list[Diagnostic] = []
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in unique_names:
                continue
            statement = _shallow_record_return(function, records, context, provenance)
            if statement is not None and not is_suppressed(context.source_lines, statement.lineno, self.code):
                findings.append(
                    Diagnostic(
                        context.path,
                        statement.lineno,
                        statement.col_offset + 1,
                        self.code,
                        "Container-only isinstance does not prove this local record's required shape; validate its fields or retain an honest container contract.",
                        severity=Severity.WARNING,
                    )
                )
        return findings


def _shallow_record_return(
    function: ast.FunctionDef,
    records: Mapping[ast.ClassDef, str],
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> ast.Return | None:
    parameter = _guard_parameter(function, context)
    record = _guard_record(function.returns, context, provenance)
    container = records.get(record) if record is not None else None
    if parameter is None or container is None:
        return None
    statement = _single_return(function)
    call = statement.value if statement is not None else None
    if not isinstance(call, ast.Call) or call.keywords or len(call.args) != _ISINSTANCE_ARITY:
        return None
    value, checked = call.args
    if not isinstance(value, ast.Name) or value.id != parameter.arg:
        return None
    if builtin_guard_symbol(call.func, context.imports, _BUILTINS) != "isinstance":
        return None
    return statement if builtin_guard_symbol(checked, context.imports, _BUILTINS) == container else None


def _guard_parameter(function: ast.FunctionDef, context: PythonFileContext) -> ast.arg | None:
    positional = (*function.args.posonlyargs, *function.args.args)
    if function.decorator_list or function.type_params:
        return None
    if len(positional) != 1 or function.args.kwonlyargs or function.args.vararg or function.args.kwarg:
        return None
    parameter = positional[0]
    if builtin_guard_symbol(parameter.annotation, context.module_imports, _BUILTINS) != "object":
        return None
    return parameter


def _guard_record(
    annotation: ast.expr | None, context: PythonFileContext, provenance: ResourceProvenance
) -> ast.ClassDef | None:
    if not isinstance(annotation, ast.Subscript) or context.module_imports.resolved_symbol(
        annotation.value, sources=TYPING_SOURCES
    ) not in {"TypeGuard", "TypeIs"}:
        return None
    if not isinstance(annotation.slice, ast.Name):
        return None
    record = provenance.binding(annotation.slice.id, annotation.slice)
    return record if isinstance(record, ast.ClassDef) else None


def _single_return(function: ast.FunctionDef) -> ast.Return | None:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body[0] if len(body) == 1 and isinstance(body[0], ast.Return) else None


def _record_containers(context: PythonFileContext, provenance: ResourceProvenance) -> dict[ast.ClassDef, str]:
    records: dict[ast.ClassDef, str] = {}
    if context.tree is None:
        return records
    for node in context.tree.body:
        if isinstance(node, ast.ClassDef) and (container := _record_container(node, context, provenance)):
            records[node] = container
    return records


def _record_container(record: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> str | None:
    if record.decorator_list or record.type_params or len(record.bases) != 1:
        return None
    kind = context.imports.resolved_symbol(record.bases[0], sources=TYPING_SOURCES)
    if kind not in {"TypedDict", "NamedTuple"} or not _stable_record(record, context, provenance):
        return None
    total = _total(record, kind)
    if total is None:
        return None
    required = _required_fields(record, total=total, named=kind == "NamedTuple", context=context)
    return ("dict" if kind == "TypedDict" else "tuple") if required else None


def _total(record: ast.ClassDef, kind: str) -> bool | None:
    if not record.keywords:
        return True
    if kind != "TypedDict" or len(record.keywords) != 1:
        return None
    option = record.keywords[0]
    return (
        option.value.value
        if option.arg == "total" and isinstance(option.value, ast.Constant) and isinstance(option.value.value, bool)
        else None
    )


def _required_fields(record: ast.ClassDef, *, total: bool, named: bool, context: PythonFileContext) -> bool:
    fields = _record_fields(record, context)
    if fields is None:
        return False
    names = {name for name, _member in fields}
    annotation_names = {
        node.id for _name, member in fields for node in ast.walk(member.annotation) if isinstance(node, ast.Name)
    }
    if not names.isdisjoint(annotation_names):
        return False
    if named:
        return _named_fields_valid([member for _name, member in fields])
    return all(member.value is None for _name, member in fields) and any(
        _field_required(member.annotation, total=total, context=context) for _name, member in fields
    )


def _record_fields(record: ast.ClassDef, context: PythonFileContext) -> list[tuple[str, ast.AnnAssign]] | None:
    fields: set[str] = set()
    members: list[tuple[str, ast.AnnAssign]] = []
    for member in record.body:
        if isinstance(member, ast.Pass) or (
            isinstance(member, ast.Expr)
            and isinstance(member.value, ast.Constant)
            and isinstance(member.value.value, str)
        ):
            continue
        if not isinstance(member, ast.AnnAssign) or not isinstance(member.target, ast.Name):
            return None
        name = member.target.id
        if name in fields or name.startswith("_") or not _safe_field_annotation(member.annotation, context):
            return None
        fields.add(name)
        members.append((name, member))
    return members


def _named_fields_valid(fields: list[ast.AnnAssign]) -> bool:
    default_seen = False
    for field in fields:
        if field.value is not None and not isinstance(field.value, ast.Constant):
            return False
        if field.value is None and default_seen:
            return False
        default_seen |= field.value is not None
    return True


def _safe_field_annotation(annotation: ast.expr, context: PythonFileContext) -> bool:
    pending = [annotation]
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > _MAX_ANNOTATION_NODES:
            return False
        children = _annotation_children(node, context)
        if children is None:
            return False
        if visited + len(pending) + len(children) > _MAX_ANNOTATION_NODES:
            return False
        pending.extend(children)
    return True


def _annotation_children(node: ast.expr, context: PythonFileContext) -> list[ast.expr] | None:
    match node:
        case ast.Constant(value=None):
            return []
        case ast.Name() | ast.Attribute():
            return [] if builtin_guard_symbol(node, context.imports, _BUILTINS) is not None else None
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return [left, right]
        case ast.Subscript():
            return _subscription_children(node, context)
        case _:
            return None


def _subscription_children(node: ast.Subscript, context: PythonFileContext) -> list[ast.expr] | None:
    symbol = context.imports.resolved_symbol(node.value, sources=TYPING_SOURCES)
    if symbol not in _TYPING and builtin_guard_symbol(node.value, context.imports, _BUILTINS) is None:
        return None
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if len(members) > _MAX_ANNOTATION_NODES:
        return None
    match symbol:
        case "Literal":
            return [] if all(isinstance(member, ast.Constant) for member in members) else None
        case "Annotated":
            return [members[0]] if members and all(isinstance(member, ast.Constant) for member in members[1:]) else None
        case _:
            return members


def _field_required(annotation: ast.expr, *, total: bool, context: PythonFileContext) -> bool:
    required = total
    while isinstance(annotation, ast.Subscript):
        symbol = context.imports.resolved_symbol(annotation.value, sources=TYPING_SOURCES)
        if symbol not in _WRAPPERS | {"Annotated"}:
            break
        if symbol in {"Required", "NotRequired"}:
            required = symbol == "Required"
        annotation = (
            annotation.slice.elts[0]
            if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts
            else annotation.slice
        )
    return required


def _stable_record(record: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if record.name in provenance.mutated or record.name in provenance.external_bindings:
        return False
    return all(
        _record_read(read, context)
        for read in provenance.reads.get(record.name, ())
        if provenance.binding(read.id, read) is record
    )


def _record_read(read: ast.Name, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    match parent:
        case ast.Call(func=func) if func is read:
            return True
        case ast.Call(func=func, args=[_, target]) if target is read:
            return builtin_guard_symbol(func, context.imports, _BUILTINS) == "isinstance"
        case _:
            pass
    node: ast.AST = read
    while (parent := context.parents.get(node)) is not None:
        match parent:
            case ast.arg(annotation=annotation) | ast.AnnAssign(annotation=annotation):
                return annotation is node
            case ast.FunctionDef(returns=returns) | ast.AsyncFunctionDef(returns=returns):
                return returns is node
            case ast.Call() | ast.stmt() | ast.Lambda():
                return False
            case _:
                node = parent
    return False
