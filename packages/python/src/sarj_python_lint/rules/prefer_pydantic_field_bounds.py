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
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._pydantic_field_contract import DECORATOR_SOURCES, direct_models, unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext

_BAD = "from pydantic import BaseModel, model_validator\nclass Count(BaseModel):\n    value: int\n    @model_validator(mode='after')\n    def positive(self):\n        if self.value < 1:\n            raise ValueError('must be positive')\n        return self\n"
_GOOD = "from pydantic import BaseModel, Field\nclass Count(BaseModel):\n    value: int = Field(ge=1)\n"


@dataclass(frozen=True, slots=True)
class _IntegerGuard:
    method: ast.FunctionDef
    field_name: str


@final
class PreferPydanticFieldBounds(Rule):
    id = "prefer-pydantic-field-bounds"
    code = "SARJ582"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare simple integer field bounds instead of an after-model validator.",
        rationale="A model-wide validator that only rejects one integer field's literal range hides a field constraint from the schema and adds a separate validation path.",
        remediation="Consider Field(gt/ge/lt/le) or a constrained Annotated integer. Preserve default validation, validation order, error locations and messages before removing the model validator; this rule offers no automatic rewrite.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct import-proven Pydantic BaseModel classes with one method are inspected. That method must have exactly one after-model validator decorator, one receiver, one literal integer range rejection with builtin ValueError, and return the same receiver.",
            "Only unique, directly annotated builtin int fields without Field/Annotated metadata are considered. Cross-field checks, float/NaN behavior, transforms, context arguments, custom errors or messages, other hooks/methods, inherited/mixed/dynamic models, tests and generated sources abstain.",
            "This is a warning about a declarative field contract, not a ban on model validators or a proof that moving validation preserves behavior. Defaults may require validate_default; error timing, location and ordering can differ.",
        ),
        examples=(
            RuleExample(
                example_id="model-wide-integer-bound",
                title="A field range is hidden in a model-wide guard",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/model.py", _BAD),),
                focus_path=PurePosixPath("app/model.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-field-bound",
                title="The field schema declares its range",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/model.py", _GOOD),),
                focus_path=PurePosixPath("app/model.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
            or "model_validator" not in context.symbol_source
            or context.tree is None
        ):
            return []
        candidates = {node for node in context.tree.body if isinstance(node, ast.ClassDef) and _potential_bound(node)}
        if not candidates:
            return []
        facts = AnnotationOrigins(context)
        findings: list[Diagnostic] = []
        for model in direct_models(context, methods=True):
            if model not in candidates:
                continue
            guarded = _bounded_integer_guard(model, facts)
            if guarded is None:
                continue
            method, field_name = guarded.method, guarded.field_name
            if context.suppressions.is_suppressed(method.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    method.lineno,
                    method.col_offset + 1,
                    self.code,
                    f"Declare the range of integer field '{field_name}' with Field/Annotated; review defaults, error timing and locations before removing this pure model-wide guard.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _potential_bound(model: ast.ClassDef) -> bool:
    methods = [node for node in model.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    if len(methods) != 1 or not isinstance(methods[0], ast.FunctionDef):
        return False
    body = methods[0].body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    match body:
        case [ast.If(test=test, body=[ast.Raise()], orelse=[]), ast.Return(value=ast.Name(id=receiver))]:
            return _range_field(test, receiver) is not None
        case _:
            return False


def _bounded_integer_guard(model: ast.ClassDef, facts: AnnotationOrigins) -> _IntegerGuard | None:
    methods = [node for node in model.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    if len(methods) != 1 or not isinstance(methods[0], ast.FunctionDef):
        return None
    method = methods[0]
    field_name = _guarded_field(method, facts)
    members = unique_members(model)
    if field_name is None or field_name not in members or method.name not in members:
        return None
    field = next(
        (
            node
            for node in model.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == field_name
        ),
        None,
    )
    return _IntegerGuard(method, field_name) if field is not None and _integer_field(field, facts) else None


def _guarded_field(method: ast.FunctionDef, facts: AnnotationOrigins) -> str | None:
    arguments = method.args
    receivers = (*arguments.posonlyargs, *arguments.args)
    if (
        len(receivers) != 1
        or arguments.kwonlyargs
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.defaults
    ):
        return None
    if len(method.decorator_list) != 1 or not _after_validator(method.decorator_list[0], facts.context):
        return None
    if receivers[0].arg == "cls":
        return None
    body = method.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    match body:
        case [
            ast.If(test=test, body=[ast.Raise(exc=error, cause=None)], orelse=[]),
            ast.Return(value=ast.Name(id=returned)),
        ] if returned == receivers[0].arg:
            return _range_field(test, receivers[0].arg) if _literal_value_error(error, facts) else None
        case _:
            return None


def _after_validator(node: ast.expr, context: PythonFileContext) -> bool:
    return (
        isinstance(node, ast.Call)
        and context.imports.resolves(node.func, sources=DECORATOR_SOURCES, symbol="model_validator")
        and not node.args
        and len(node.keywords) == 1
        and node.keywords[0].arg == "mode"
        and isinstance(node.keywords[0].value, ast.Constant)
        and node.keywords[0].value.value == "after"
    )


def _range_field(node: ast.expr, receiver: str) -> str | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not isinstance(node.ops[0], ast.Lt | ast.LtE | ast.Gt | ast.GtE):
        return None
    for field, bound in [(node.left, node.comparators[0]), (node.comparators[0], node.left)]:
        if (
            isinstance(field, ast.Attribute)
            and isinstance(field.value, ast.Name)
            and field.value.id == receiver
            and _integer_literal(bound)
        ):
            return field.attr
    return None


def _integer_literal(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=bool()):
            return False
        case ast.Constant(value=int()):
            return True
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=int() as value)):
            return not isinstance(value, bool)
        case _:
            return False


def _integer_field(field: ast.AnnAssign, facts: AnnotationOrigins) -> bool:
    annotation = facts.resolve_annotation(field.annotation)
    return (
        annotation is not None
        and facts.builtin(annotation.expression, "int", annotation.at)
        and (field.value is None or _integer_literal(field.value))
    )


def _literal_value_error(node: ast.expr | None, facts: AnnotationOrigins) -> bool:
    return (
        isinstance(node, ast.Call)
        and facts.builtin(node.func, "ValueError", node)
        and not node.keywords
        and (
            not node.args
            or (len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))
        )
    )
