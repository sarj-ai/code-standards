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
from sarj_python_lint.rules._pydantic_field_contract import (
    DECORATOR_SOURCES,
    TYPING_SOURCES,
    direct_models,
    unique_members,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Primitive = str | bytes | int | float | complex | bool | None
_SCALARS = frozenset({"str", "bytes", "int", "float", "complex", "bool"})
_MODEL_CALLS = frozenset({"model_validate", "model_validate_json", "model_validate_strings", "model_construct"})
_MAX_ANNOTATION_NODES = 256
_MAX_ANNOTATION_DEPTH = 32
_VALIDATOR_ARITY = 2
_DECORATOR_STACK_SIZE = 2
_BAD = "from pydantic import BaseModel, field_validator\nclass Payload(BaseModel):\n    text: str\n    @field_validator('text', mode='after')\n    @classmethod\n    def replace(cls, value: str) -> int:\n        return 3\n"


@dataclass(frozen=True, slots=True)
class _Returned:
    node: ast.expr
    value: _Primitive


@final
class NoInvalidPydanticValidatorReturn(Rule):
    id = "no-invalid-pydantic-validator-return"
    code = "SARJ515"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="A terminal field validator must not return a literal contradicting its stored field type.",
        rationale="Pydantic trusts the result of after and plain field validators without validating it against the field again. A correctly annotated validator can therefore store an integer in a string field while the model still promises a string to callers.",
        remediation="Return a value satisfying every targeted field's stored contract. Split validators for different field domains, or perform input conversion in a before validator so the normal field validation follows it. Preserve intentional validation chains and wire serializers.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks stable direct module-level BaseModel classes containing one synchronous field-validator method, plain annotated fields, and optional literal defaults. Inheritance, configuration, custom methods, field metadata, class decorators and escaped or mutated model classes are excluded.",
            "The validator must have the canonical field_validator/classmethod stack, explicit literal field targets, mode after or plain (including omitted default after), two required positional parameters, and a sole primitive literal return, optionally after a docstring. Before, wrap, serializer, unknown and composed validator contracts abstain.",
            "Only contradictions with builtin scalar types, None, canonical Optional/Union and closed string Literal domains are proved. Numeric assignability preserves bool as int and int as float/complex. Opaque aliases, numeric Literal domains, containers and annotation graphs exceeding fixed budgets abstain.",
            "Every targeted field must exist; unknown-field diagnostics belong to their existing owner. Multiple validators are excluded because a later validator can repair an intermediate value. One diagnostic identifies all contradictory fields for the returned literal.",
            "Generated and vendor files are excluded; authored tests remain checked. No autofix changes validation phase, chooses domain values or narrows a public contract.",
        ),
        examples=(
            RuleExample(
                example_id="invalid-after-output",
                title="An after validator stores an incompatible primitive unchanged",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/models.py", _BAD),),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="valid-after-output",
                title="The validator output satisfies the stored field contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py", _BAD.replace("-> int", "-> str").replace("return 3", "return 'ready'")
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="plain-output-is-not-revalidated",
                scenario="validation-phase",
                title="A plain validator also bypasses subsequent field validation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/models.py", _BAD.replace("mode='after'", "mode='plain'")),),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="before-output-is-revalidated",
                scenario="validation-phase",
                title="Input conversion is followed by ordinary field validation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        _BAD.replace("text: str", "text: int")
                        .replace("mode='after'", "mode='before'")
                        .replace("-> int", "-> str")
                        .replace("return 3", "return '3'"),
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
        if context.tree is None or context.generated or "field_validator" not in context.symbol_source:
            return []
        annotations = [node.annotation for node in context.nodes(ast.AnnAssign)]
        if any(sum(1 for _ in ast.walk(annotation)) > _MAX_ANNOTATION_NODES for annotation in annotations):
            return []
        provenance = context.static_resource_provenance
        findings: list[Diagnostic] = []
        for model in direct_models(context, methods=True):
            proof = _model_return(model, context, provenance)
            if proof is None:
                continue
            returned, fields = proof
            if not is_suppressed(context.source_lines, returned.node.lineno, self.code):
                findings.append(
                    Diagnostic(
                        context.path,
                        returned.node.lineno,
                        returned.node.col_offset + 1,
                        self.code,
                        f"This terminal validator returns a literal outside the stored contract of {', '.join(sorted(fields))}. Return valid field values or validate converted input before storing it.",
                        severity=Severity.ERROR,
                    )
                )
        return findings


def _model_return(
    model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance
) -> tuple[_Returned, frozenset[str]] | None:
    if not _stable_model(model, context, provenance):
        return None
    methods = [member for member in model.body if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(methods) != 1 or not isinstance(methods[0], ast.FunctionDef):
        return None
    fields = _plain_fields(model)
    if fields is None:
        return None
    validator = methods[0]
    targets = _targets(validator, context)
    returned = _returned_literal(validator)
    if targets is None or returned is None or not targets <= fields.keys():
        return None
    rejected = frozenset(name for name in targets if _rejects(fields[name], returned.value, context, depth=0))
    return (returned, rejected) if rejected else None


def _plain_fields(model: ast.ClassDef) -> dict[str, ast.expr] | None:
    fields: dict[str, ast.expr] = {}
    unique = unique_members(model)
    if unique & (_SCALARS | {"Literal", "Optional", "Union", "classmethod", "field_validator"}):
        return None
    for member in model.body:
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
            if member.target.id not in unique or member.target.id.startswith("_"):
                return None
            if member.value is not None and not isinstance(member.value, ast.Constant):
                return None
            fields[member.target.id] = member.annotation
        elif not isinstance(member, (ast.FunctionDef, ast.Pass)) and not (
            isinstance(member, ast.Expr)
            and isinstance(member.value, ast.Constant)
            and isinstance(member.value.value, str)
        ):
            return None
    return fields


def _stable_model(model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if model.name in provenance.mutated or model.name in provenance.external_bindings:
        return False
    return all(
        _stable_model_read(read, context)
        for read in provenance.reads.get(model.name, ())
        if provenance.binding(read.id, read) is model
    )


def _stable_model_read(read: ast.Name, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    if isinstance(parent, ast.Call) and parent.func is read:
        return True
    if isinstance(parent, (ast.arg, ast.AnnAssign)) and parent.annotation is read:
        return True
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent.returns is read:
        return True
    if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr in _MODEL_CALLS:
        call = context.parents.get(parent)
        return isinstance(call, ast.Call) and call.func is parent
    return False


def _targets(validator: ast.FunctionDef, context: PythonFileContext) -> frozenset[str] | None:
    arguments = validator.args
    if validator.type_params or len(validator.decorator_list) != _DECORATOR_STACK_SIZE:
        return None
    if (
        len((*arguments.posonlyargs, *arguments.args)) != _VALIDATOR_ARITY
        or arguments.vararg
        or arguments.kwarg
        or arguments.kwonlyargs
        or arguments.defaults
    ):
        return None
    outer, inner = validator.decorator_list
    if not (
        isinstance(inner, ast.Name)
        and inner.id == "classmethod"
        and context.imports.builtin_is_unshadowed("classmethod")
        and isinstance(outer, ast.Call)
        and context.imports.resolves(outer.func, sources=DECORATOR_SOURCES, symbol="field_validator")
    ):
        return None
    if len(outer.keywords) > 1 or any(
        keyword.arg != "mode"
        or not isinstance(keyword.value, ast.Constant)
        or keyword.value.value not in {"after", "plain"}
        for keyword in outer.keywords
    ):
        return None
    targets: set[str] = set()
    for argument in outer.args:
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str) or argument.value == "*":
            return None
        targets.add(argument.value)
    return frozenset(targets) if targets else None


def _returned_literal(validator: ast.FunctionDef) -> _Returned | None:
    body = validator.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    value = body[0].value
    if isinstance(value, ast.Constant) and (
        value.value is None or isinstance(value.value, (str, bytes, int, float, complex, bool))
    ):
        return _Returned(value, value.value)
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, (ast.USub, ast.UAdd))
        and isinstance(value.operand, ast.Constant)
        and isinstance(value.operand.value, (int, float, complex))
    ):
        number = value.operand.value
        return _Returned(value, -number if isinstance(value.op, ast.USub) else +number)
    return None


def _rejects(annotation: ast.expr, value: _Primitive, context: PythonFileContext, *, depth: int) -> bool:
    if depth > _MAX_ANNOTATION_DEPTH:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value is None and value is not None
    if isinstance(annotation, ast.Name) and context.imports.builtin_is_unshadowed(annotation.id):
        return _scalar_rejects(annotation.id, value)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _rejects(annotation.left, value, context, depth=depth + 1) and _rejects(
            annotation.right, value, context, depth=depth + 1
        )
    if not isinstance(annotation, ast.Subscript):
        return False
    return _subscript_rejects(annotation, value, context, depth=depth)


def _scalar_rejects(name: str, value: _Primitive) -> bool:
    match name:
        case "str":
            return not isinstance(value, str)
        case "bytes":
            return not isinstance(value, bytes)
        case "bool":
            return not isinstance(value, bool)
        case "int":
            return not isinstance(value, int)
        case "float":
            return not isinstance(value, (int, float))
        case "complex":
            return not isinstance(value, (int, float, complex))
        case _:
            return False


def _subscript_rejects(annotation: ast.Subscript, value: _Primitive, context: PythonFileContext, *, depth: int) -> bool:
    members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    wrapper = context.imports.resolved_symbol(annotation.value, sources=TYPING_SOURCES)
    if wrapper == "Optional" and len(members) == 1:
        return value is not None and _rejects(members[0], value, context, depth=depth + 1)
    if wrapper == "Union" and members:
        return all(_rejects(member, value, context, depth=depth + 1) for member in members)
    if (
        wrapper == "Literal"
        and members
        and all(isinstance(member, ast.Constant) and isinstance(member.value, str) for member in members)
    ):
        return not any(isinstance(member, ast.Constant) and member.value == value for member in members)
    return False
