from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pydantic_field_contract import (
    DECORATOR_SOURCES,
    TYPING_SOURCES,
    direct_models,
    unique_members,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PAIR_ARITY = 2
_BUILTIN_SOURCES = frozenset({"builtins"})
_INHABITED_SCALARS = frozenset({"str", "int", "float", "bool", "bytes", "complex"})
_EMPTY_CONTAINERS = frozenset({"list", "dict", "set", "frozenset", "tuple"})


@dataclass(frozen=True, slots=True)
class _Requirement:
    guard: ast.If
    tag: str
    value: str
    payload: str


@final
class PreferDiscriminatedModelUnion(Rule):
    id = "prefer-discriminated-model-union"
    code = "SARJ510"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Represent literal-tag-dependent required fields with discriminated model variants.",
        rationale=(
            "A nullable field remains statically nullable even when an after validator requires it for a literal "
            "tag. A union of models with distinct Literal tags carries that dependency in the type and supports "
            "safe narrowing without repeating runtime guards."
        ),
        remediation=(
            "Consider a discriminated union of model variants. Make the payload non-nullable only in variants "
            "proven to reject None, and preserve every other accepted field combination, defaults, aliases and wire shape. "
            "Independent optional fields can remain optional within each variant."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct module-level import-proven Pydantic BaseModel subclasses with one direct after model validator are inspected.",
            "The validator must contain only direct guards and a final return of its instance; each guard must reject a two-part conjunction of literal-tag equality and nullable-field identity with None, using a literal exception message or a local assignment of that message.",
            "Tags must use an imported Literal of at least two distinct strings; payloads must explicitly include None in a union or imported Optional.",
            "Every non-null payload member must have a source-proven inhabited built-in scalar or container type; opaque aliases, custom types and None-only or bottom-type unions are excluded.",
            "A field required by every admitted tag value is a common field constraint rather than evidence for a discriminated union and is excluded.",
            "Other validators, inherited models, computed tags, helper validation, model mutation, ambiguous namespaces, tests and generated files are excluded.",
            "This warning requests domain modeling review; it does not require absent payloads in other variants or change external compatibility automatically.",
        ),
        examples=(
            RuleExample(
                example_id="literal-tag-dependent-payload",
                title="An after validator encodes a field dependency that its type cannot express",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal, Self\nfrom pydantic import BaseModel, model_validator\n"
                        "class Delivery(BaseModel):\n    kind: Literal['email', 'pickup']\n    address: str | None = None\n"
                        "    @model_validator(mode='after')\n    def validate_address(self) -> Self:\n"
                        "        if self.kind == 'email' and self.address is None:\n"
                        "            raise ValueError('Email requires an address')\n        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="variants-preserve-other-accepted-states",
                title="Only the email variant requires an address; pickup preserves its optional address",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Annotated, Literal\nfrom pydantic import BaseModel, Field\n"
                        "class EmailDelivery(BaseModel):\n    kind: Literal['email']\n    address: str\n"
                        "class PickupDelivery(BaseModel):\n    kind: Literal['pickup']\n    address: str | None = None\n"
                        "type Delivery = Annotated[EmailDelivery | PickupDelivery, Field(discriminator='kind')]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            is_test_path(context.path)
            or "None" not in context.symbol_source
            or "model_validator" not in context.symbol_source
        ):
            return []
        diagnostics: list[Diagnostic] = []
        for model in direct_models(context, methods=True):
            requirements = _model_requirements(model, context)
            if not requirements:
                continue
            first = requirements[0]
            if is_suppressed(context.source_lines, first.guard.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    context.path,
                    first.guard.lineno,
                    first.guard.col_offset + 1,
                    self.code,
                    f"`{model.name}` requires nullable `{first.payload}` when `{first.tag}` is {first.value!r}. "
                    "Consider a discriminated model union with that payload non-nullable in the matching variant; "
                    "preserve every other accepted combination and the external contract.",
                    severity=Severity.WARNING,
                )
            )
        return diagnostics


def _model_requirements(model: ast.ClassDef, context: PythonFileContext) -> list[_Requirement]:
    methods = [member for member in model.body if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(methods) != 1 or not isinstance(methods[0], ast.FunctionDef):
        return []
    validator = methods[0]
    instance = _validator_instance(validator, context)
    if instance is None:
        return []
    unique = unique_members(model)
    fields = {
        member.target.id: member.annotation
        for member in model.body
        if isinstance(member, ast.AnnAssign)
        and isinstance(member.target, ast.Name)
        and member.target.id in unique
        and not member.target.id.startswith("_")
    }
    body = validator.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if not body or not isinstance(body[-1], ast.Return) or not _is_instance(body[-1].value, instance):
        return []
    requirements: list[_Requirement] = []
    for statement in body[:-1]:
        requirement = _guard_requirement(statement, fields, instance, context)
        if requirement is None:
            return []
        requirements.append(requirement)
    return _variant_specific_requirements(requirements, fields, context)


def _variant_specific_requirements(
    requirements: list[_Requirement], fields: dict[str, ast.expr], context: PythonFileContext
) -> list[_Requirement]:
    required_tags: dict[tuple[str, str], set[str]] = {}
    for requirement in requirements:
        required_tags.setdefault((requirement.tag, requirement.payload), set()).add(requirement.value)
    return [
        requirement
        for requirement in requirements
        if required_tags[requirement.tag, requirement.payload] < _literal_strings(fields[requirement.tag], context)
    ]


def _validator_instance(validator: ast.FunctionDef, context: PythonFileContext) -> str | None:
    arguments = validator.args
    positional = [*arguments.posonlyargs, *arguments.args]
    if len(positional) != 1 or len(validator.decorator_list) != 1:
        return None
    if arguments.vararg is not None or arguments.kwarg is not None or arguments.kwonlyargs or arguments.defaults:
        return None
    decorator = validator.decorator_list[0]
    match decorator:
        case ast.Call(args=[], keywords=[ast.keyword(arg="mode", value=ast.Constant(value="after"))]):
            if context.imports.resolves(decorator.func, sources=DECORATOR_SOURCES, symbol="model_validator"):
                return positional[0].arg
        case _:
            pass
    return None


def _guard_requirement(
    statement: ast.stmt, fields: dict[str, ast.expr], instance: str, context: PythonFileContext
) -> _Requirement | None:
    if not isinstance(statement, ast.If) or statement.orelse or not _rejection_body(statement.body, context):
        return None
    if (
        not isinstance(statement.test, ast.BoolOp)
        or not isinstance(statement.test.op, ast.And)
        or len(statement.test.values) != _PAIR_ARITY
    ):
        return None
    for tag_test, payload_test in (statement.test.values, list(reversed(statement.test.values))):
        tagged = _tag_test(tag_test, instance)
        payload = _none_test(payload_test, instance)
        if tagged is None or payload is None or payload not in fields or tagged[0] not in fields:
            continue
        tag, value = tagged
        if tag != payload and value in _literal_strings(fields[tag], context) and _nullable(fields[payload], context):
            return _Requirement(statement, tag, value, payload)
    return None


def _tag_test(node: ast.expr, instance: str) -> tuple[str, str] | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return None
    for attribute, literal in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
        field = _instance_field(attribute, instance)
        if field is not None and isinstance(literal, ast.Constant) and isinstance(literal.value, str):
            return field, literal.value
    return None


def _none_test(node: ast.expr, instance: str) -> str | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Is):
        return None
    for attribute, literal in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
        if isinstance(literal, ast.Constant) and literal.value is None:
            return _instance_field(attribute, instance)
    return None


def _instance_field(node: ast.expr, instance: str) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) and _is_instance(node.value, instance) else None


def _is_instance(node: ast.expr | None, instance: str) -> bool:
    return isinstance(node, ast.Name) and node.id == instance


def _literal_strings(annotation: ast.expr, context: PythonFileContext) -> frozenset[str]:
    if not isinstance(annotation, ast.Subscript) or not context.imports.resolves(
        annotation.value, sources=TYPING_SOURCES, symbol="Literal"
    ):
        return frozenset()
    values = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    strings = frozenset(
        value.value for value in values if isinstance(value, ast.Constant) and isinstance(value.value, str)
    )
    return strings if len(strings) > 1 and len(strings) == len(values) else frozenset()


def _nullable(annotation: ast.expr, context: PythonFileContext) -> bool:
    members = _union_members(annotation, context)
    non_null = [member for member in members if not _is_none(member)]
    return (
        len(non_null) < len(members)
        and bool(non_null)
        and all(_non_none_witness(member, context) for member in non_null)
    )


def _union_members(annotation: ast.expr, context: PythonFileContext) -> list[ast.expr]:
    members: list[ast.expr] = []
    pending = [annotation]
    while pending:
        member = pending.pop()
        if isinstance(member, ast.Subscript) and context.imports.resolves(
            member.value, sources=TYPING_SOURCES, symbol="Optional"
        ):
            if isinstance(member.slice, ast.Tuple):
                members.append(member)
            else:
                members.append(ast.Constant(value=None))
                pending.append(member.slice)
        elif isinstance(member, ast.BinOp) and isinstance(member.op, ast.BitOr):
            pending.extend((member.right, member.left))
        else:
            members.append(member)
    return members


def _non_none_witness(annotation: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(annotation, ast.Subscript):
        builtin = _builtin_type(annotation.value, context)
        if builtin not in _EMPTY_CONTAINERS:
            return False
        if builtin != "tuple":
            return True
        arguments = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return not arguments or (
            len(arguments) == _PAIR_ARITY
            and isinstance(arguments[-1], ast.Constant)
            and arguments[-1].value is Ellipsis
        )
    return _builtin_type(annotation, context) in _INHABITED_SCALARS | _EMPTY_CONTAINERS


def _builtin_type(annotation: ast.expr, context: PythonFileContext) -> str | None:
    if isinstance(annotation, ast.Name) and context.imports.builtin_is_unshadowed(annotation.id):
        return annotation.id
    return context.imports.resolved_symbol(annotation, sources=_BUILTIN_SOURCES)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _rejection_body(body: list[ast.stmt], context: PythonFileContext) -> bool:
    if len(body) == 1:
        return _rejection(body[0], context)
    match body:
        case [ast.Assign(targets=[ast.Name(id=message)], value=ast.Constant(value=str())), rejection]:
            return _rejection(rejection, context, message=message)
        case _:
            return False


def _rejection(statement: ast.stmt, context: PythonFileContext, *, message: str | None = None) -> bool:
    return (
        isinstance(statement, ast.Raise)
        and statement.cause is None
        and isinstance(statement.exc, ast.Call)
        and isinstance(statement.exc.func, ast.Name)
        and statement.exc.func.id in {"ValueError", "AssertionError"}
        and context.imports.builtin_is_unshadowed(statement.exc.func.id)
        and not statement.exc.keywords
        and all(
            isinstance(argument, ast.Constant) or (message is not None and _is_instance(argument, message))
            for argument in statement.exc.args
        )
    )
