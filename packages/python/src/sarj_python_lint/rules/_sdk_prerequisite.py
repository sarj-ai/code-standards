from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet


if TYPE_CHECKING:
    from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
    from sarj_python_lint.rules._project_index import SourceUnit


_SDK_TYPES = frozenset(
    {"openai.OpenAI", "openai.AsyncOpenAI"}
    | {f"{module}.{name}" for module in ("httpx", "httpx2") for name in ("Client", "AsyncClient")}
)
_MAPPINGS = frozenset(
    {"typing.Mapping", "typing.MutableMapping", "collections.abc.Mapping", "collections.abc.MutableMapping"}
)
_OPTIONALS = frozenset({"typing.Optional", "typing_extensions.Optional"})
_UNIONS = frozenset({"typing.Union", "typing_extensions.Union"})
_ANNOTATED = frozenset({"typing.Annotated", "typing_extensions.Annotated"})
_OVERRIDES = frozenset({"typing.override", "typing_extensions.override"})
_LITERALS = frozenset({"typing.Literal", "typing_extensions.Literal"})
_MAX_ANNOTATION_MEMBERS = 64
_REJECTION_STATEMENTS = 2
_MAPPING_ARGUMENTS = 2
_ENUM_BASES = frozenset({"enum.Enum", "enum.IntEnum", "enum.StrEnum"})


@dataclass(frozen=True, slots=True)
class _FieldAssignment:
    target: ast.Attribute
    value: ast.expr


def sdk_prerequisite_diagnostics(facts: AnnotationOrigins, code: str) -> list[Diagnostic]:
    context = facts.context
    if context.tree is None:
        return []
    project = context.session.project or ProjectIndexSet.single(context.path, context.source)
    unit = project.unit_or_source(context.path, context.source, context.tree)
    if unit is None:
        return []
    return [
        finding
        for owner in context.nodes(ast.ClassDef)
        for finding in _class_diagnostics(owner, facts, project, unit, code)
    ]


def _class_diagnostics(
    owner: ast.ClassDef, facts: AnnotationOrigins, project: ProjectIndexSet, unit: SourceUnit, code: str
) -> list[Diagnostic]:
    if owner.decorator_list or owner.type_params or owner.keywords:
        return []
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    findings: list[Diagnostic] = []
    for field, (parameter, registry) in _constructor_fields(methods, facts, project, unit).items():
        if not _unchanged_field(owner, field, registry=registry, facts=facts):
            continue
        if not any(_rejects_dependency(method, field, registry=registry, facts=facts) for method in methods):
            continue
        findings.append(
            Diagnostic(
                path=facts.context.path,
                line=parameter.lineno,
                col=parameter.col_offset + 1,
                code=code,
                severity=Severity.ERROR,
                message=(
                    f"SDK dependency '{parameter.arg}' admits an absent client that an operation rejects; "
                    "declare required non-null dependencies or a complete typed configuration variant "
                    "at construction. Preserve required boundary validation instead of only deleting the guard."
                ),
            )
        )
    return findings


def _constructor_fields(
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef],
    facts: AnnotationOrigins,
    project: ProjectIndexSet,
    unit: SourceUnit,
) -> dict[str, tuple[ast.arg, bool]]:
    constructor = _simple_constructor(methods)
    if constructor is None:
        return {}
    positional = constructor.args.posonlyargs + constructor.args.args
    receiver = positional[0].arg
    parameters = {arg.arg: arg for arg in (*positional[1:], *constructor.args.kwonlyargs)}
    fields: dict[str, tuple[ast.arg, bool]] = {}
    for statement in constructor.body:
        assignment = _field_assignment(statement, receiver)
        if assignment is None:
            continue
        target, value = assignment.target, assignment.value
        registry = (
            isinstance(value, ast.Call)
            and facts.builtin(value.func, "dict", value)
            and len(value.args) == 1
            and not value.keywords
        )
        argument = value.args[0] if registry and isinstance(value, ast.Call) else value
        if not isinstance(argument, ast.Name) or (parameter := parameters.get(argument.id)) is None:
            continue
        if parameter.annotation is None or facts.provenance.bindings.get(constructor, {}).get(argument.id) != (
            parameter,
        ):
            continue
        eligible = (
            _sdk_registry(parameter.annotation, facts, project, unit)
            if registry
            else _sdk_annotation(parameter.annotation, facts, nullable=True)
        )
        if eligible:
            fields[target.attr] = parameter, registry
    return fields


def _simple_constructor(methods: list[ast.FunctionDef | ast.AsyncFunctionDef]) -> ast.FunctionDef | None:
    constructors = [method for method in methods if method.name == "__init__"]
    if len(constructors) != 1 or not isinstance(constructor := constructors[0], ast.FunctionDef):
        return None
    if (
        constructor.decorator_list
        or constructor.type_params
        or not (constructor.args.posonlyargs or constructor.args.args)
    ):
        return None
    for statement in constructor.body:
        if isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        # Validation or registration at construction already owns this boundary.
        return None
    return constructor


def _field_assignment(statement: ast.stmt, receiver: str) -> _FieldAssignment | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign):
        target, value = statement.target, statement.value
    else:
        return None
    if value is None or not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
        return None
    return _FieldAssignment(target, value) if target.value.id == receiver else None


def _sdk_registry(annotation: ast.expr, facts: AnnotationOrigins, project: ProjectIndexSet, unit: SourceUnit) -> bool:
    resolved = facts.resolve_annotation(annotation)
    if resolved is None or not isinstance(resolved.expression, ast.Subscript):
        return False
    node = resolved.expression
    qualified = facts.qualified(node.value, resolved.at)
    if qualified not in _MAPPINGS and not facts.builtin(node.value, "dict", resolved.at):
        return False
    if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != _MAPPING_ARGUMENTS:
        return False
    key, value = node.slice.elts
    key_annotation = facts.resolve_annotation(key, at=resolved.at)
    if key_annotation is None or not _sdk_annotation(value, facts, nullable=False):
        return False
    key = key_annotation.expression
    if isinstance(key, ast.Subscript) and facts.qualified(key.value, key_annotation.at) in _LITERALS:
        members = key.slice.elts if isinstance(key.slice, ast.Tuple) else [key.slice]
        return bool(members) and all(isinstance(member, ast.Constant) for member in members)
    summary = project.class_for(unit, key)
    if summary is None:
        return False
    enum_unit = project.source_unit(summary.symbol.module)
    return enum_unit is not None and project.class_inherits_from(enum_unit, summary.symbol.name, _ENUM_BASES)


def _sdk_annotation(annotation: ast.expr, facts: AnnotationOrigins, *, nullable: bool) -> bool:
    pending = [(annotation, annotation)]
    found_sdk = found_none = False
    for _ in range(_MAX_ANNOTATION_MEMBERS):
        if not pending:
            return found_sdk and (found_none or not nullable)
        node, at = pending.pop()
        resolved = facts.resolve_annotation(node, at=at)
        if resolved is None:
            return False
        node, at = resolved.expression, resolved.at
        if isinstance(node, ast.Constant) and node.value is None:
            found_none = True
            continue
        children = _annotation_children(node, at, facts)
        if children is not None:
            pending.extend((child, at) for child in children)
            continue
        if facts.qualified(node, at) not in _SDK_TYPES:
            return False
        found_sdk = True
    return False


def _annotation_children(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [node.left, node.right]
    if not isinstance(node, ast.Subscript):
        return None
    qualified = facts.qualified(node.value, at)
    members = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
    if qualified in _OPTIONALS and len(members) == 1:
        return [ast.Constant(value=None), members[0]]
    if qualified in _UNIONS:
        return members
    if qualified in _ANNOTATED and len(members) > 1:
        return members[:1]
    return None


def _unchanged_field(owner: ast.ClassDef, field: str, *, registry: bool, facts: AnnotationOrigins) -> bool:
    context = facts.context
    writes = 0
    for node in ast.walk(owner):
        if not isinstance(node, ast.Attribute) or node.attr != field:
            continue
        if isinstance(node.ctx, ast.Store | ast.Del):
            writes += 1
        elif registry:
            parent = context.parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr in {"get", "keys", "values", "items"}:
                continue
            if isinstance(parent, ast.Subscript) and isinstance(parent.ctx, ast.Load):
                continue
            return False
    return writes == 1


def _rejects_dependency(
    method: ast.FunctionDef | ast.AsyncFunctionDef, field: str, *, registry: bool, facts: AnnotationOrigins
) -> bool:
    positional = method.args.posonlyargs + method.args.args
    if method.name == "__init__" or not positional or method.type_params:
        return False
    if any(facts.qualified(decorator, decorator) not in _OVERRIDES for decorator in method.decorator_list):
        return False
    receiver = positional[0].arg
    for index, statement in enumerate(method.body):
        if isinstance(statement, ast.Return | ast.Raise):
            break
        if not isinstance(statement, ast.If) or statement.orelse or not _immediate_rejection(statement.body):
            continue
        selected = _none_guard(statement.test)
        if selected is None or not _selects_field(selected, method, receiver, field, registry=registry, facts=facts):
            continue
        if _called_after(method.body[index + 1 :], selected):
            return True
    return False


def _selects_field(
    selected: ast.expr,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver: str,
    field: str,
    *,
    registry: bool,
    facts: AnnotationOrigins,
) -> bool:
    if not registry:
        return _owned_field(selected, receiver, field)
    if not isinstance(selected, ast.Name):
        return False
    bindings = facts.provenance.bindings.get(method, {}).get(selected.id, ())
    if len(bindings) != 1:
        return False
    assignment = facts.context.parents.get(bindings[0])
    lookup = assignment.value if isinstance(assignment, ast.Assign | ast.AnnAssign) else None
    return _registry_lookup(lookup, receiver, field)


def _owned_field(node: ast.AST, receiver: str, field: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == field
        and isinstance(node.value, ast.Name)
        and node.value.id == receiver
    )


def _registry_lookup(node: ast.expr | None, receiver: str, field: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _owned_field(node.func.value, receiver, field)
        and len(node.args) == 1
        and not node.keywords
    )


def _none_guard(node: ast.expr) -> ast.expr | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Is):
        return None
    left, right = node.left, node.comparators[0]
    if isinstance(left, ast.Constant) and left.value is None:
        return right
    return left if isinstance(right, ast.Constant) and right.value is None else None


def _immediate_rejection(body: list[ast.stmt]) -> bool:
    if len(body) == _REJECTION_STATEMENTS:
        first = body[0]
        if not isinstance(first, ast.Assign) or len(first.targets) != 1 or not isinstance(first.targets[0], ast.Name):
            return False
    elif len(body) != 1:
        return False
    last = body[-1]
    return isinstance(last, ast.Raise) and last.exc is not None


def _called_after(statements: list[ast.stmt], selected: ast.expr) -> bool:
    target = ast.dump(selected)
    pending: list[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        if isinstance(node, ast.Call) and any(ast.dump(part) == target for part in ast.walk(node.func)):
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False
