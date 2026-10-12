from __future__ import annotations

import ast
from dataclasses import dataclass
import math
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
from sarj_python_lint.rules._pydantic_field_contract import FIELD_SOURCES, TYPING_SOURCES, direct_models, unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_NUMERIC_BOUNDS = frozenset({"gt", "ge", "lt", "le"})
_LENGTH_BOUNDS = frozenset({"min_length", "max_length"})
_KINDS = frozenset({"int", "float", "str", "list"})
_PASSIVE_OPTIONS = frozenset(
    {
        "default",
        "default_factory",
        "description",
        "title",
        "alias",
        "validation_alias",
        "serialization_alias",
        "strict",
        "validate_default",
        "repr",
        "exclude",
        "frozen",
    }
)


@dataclass(frozen=True, slots=True)
class _Bound:
    value: int | float
    exclusive: bool


@final
class NoImpossiblePydanticFieldBounds(Rule):
    id = "no-impossible-pydantic-field-bounds"
    code = "SARJ491"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Pydantic field bounds must admit at least one value.",
        rationale="Contradictory literal constraints reject every field value, including integer intervals with no integer member.",
        remediation="Correct the conflicting bounds so the declared field domain admits the intended values.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only plain direct module-level BaseModel subclasses and built-in int, float, str and list fields are inspected.",
            "Bounds must be finite literals; int and length bounds must be integers, and float bounds must convert exactly.",
            "Unknown metadata, nullable types, repeated bound names, methods, dynamic namespaces and generated files are excluded.",
            "Visible namespace APIs, dynamic module access, ambiguous imports and escaped or mutated imported objects exclude the file.",
            "No autofix chooses a domain or changes validation behavior.",
        ),
        examples=(
            RuleExample(
                example_id="empty-integer-interval",
                title="No integer lies strictly between zero and one",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="integer-singleton",
                title="Zero is admitted by the interval",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    value: int = Field(ge=0, lt=1)\n",
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
        if "Field" not in context.symbol_source and "pydantic" not in context.symbol_source:
            return []
        diagnostics: list[Diagnostic] = []
        for field in _candidate_fields(context):
            contract = _field_contract(field, context)
            if contract is None or not _empty_interval(*contract):
                continue
            if is_suppressed(context.source_lines, field.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    context.path,
                    field.lineno,
                    field.col_offset + 1,
                    self.code,
                    "These literal Field bounds admit no values. Correct the bounds for the declared field type.",
                    severity=Severity.ERROR,
                )
            )
        return diagnostics


def _candidate_fields(context: PythonFileContext) -> list[ast.AnnAssign]:
    fields: list[ast.AnnAssign] = []
    for model in direct_models(context):
        if any(isinstance(member, (ast.Assign, ast.AnnAssign)) and _names_config(member) for member in model.body):
            continue
        unique = unique_members(model)
        fields.extend(
            member
            for member in model.body
            if isinstance(member, ast.AnnAssign)
            and isinstance(member.target, ast.Name)
            and member.target.id in unique
            and not member.target.id.startswith("_")
        )
    return fields


def _names_config(node: ast.Assign | ast.AnnAssign) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(target, ast.Name) and target.id == "model_config" for target in targets)


def _field_contract(field: ast.AnnAssign, context: PythonFileContext) -> tuple[str, dict[str, int | float]] | None:
    annotation = field.annotation
    calls: list[ast.Call] = []
    if isinstance(annotation, ast.Subscript) and context.imports.resolves(
        annotation.value, sources=TYPING_SOURCES, symbol="Annotated"
    ):
        if not isinstance(annotation.slice, ast.Tuple):
            return None
        annotation, *metadata = annotation.slice.elts
        for item in metadata:
            if not isinstance(item, ast.Call) or not context.imports.resolves(
                item.func, sources=FIELD_SOURCES, symbol="Field"
            ):
                return None
            calls.append(item)
    type_node = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if (
        not isinstance(type_node, ast.Name)
        or type_node.id not in _KINDS
        or not context.imports.builtin_is_unshadowed(type_node.id)
    ):
        return None
    kind = type_node.id
    if isinstance(annotation, ast.Subscript) != (kind == "list"):
        return None
    if isinstance(field.value, ast.Call):
        if not context.imports.resolves(field.value.func, sources=FIELD_SOURCES, symbol="Field"):
            return None
        calls.append(field.value)
    bounds = _literal_bounds(calls, kind)
    return None if bounds is None else (kind, bounds)


def _literal_bounds(calls: list[ast.Call], kind: str) -> dict[str, int | float] | None:
    if any(call.args for call in calls):
        return None
    bounds: dict[str, int | float] = {}
    allowed = _NUMERIC_BOUNDS if kind in {"int", "float"} else _LENGTH_BOUNDS
    for keyword in (keyword for call in calls for keyword in call.keywords):
        name = keyword.arg
        if name in _PASSIVE_OPTIONS:
            continue
        if name is None or name not in allowed or name in bounds:
            return None
        value = _bound_value(keyword.value, kind)
        if value is None:
            return None
        bounds[name] = value
    return bounds


def _bound_value(node: ast.expr, kind: str) -> int | float | None:
    value = _number(node)
    if value is None:
        return None
    if kind == "float":
        return value if _exact_float_bound(value) else None
    if not isinstance(value, int) or (kind in {"str", "list"} and value < 0):
        return None
    return value


def _exact_float_bound(value: float) -> bool:
    try:
        converted = float(value)
    except OverflowError:
        return False
    return math.isfinite(converted) and converted == value


def _number(node: ast.expr) -> int | float | None:
    match node:
        case ast.Constant(value=value) if type(value) is int:
            return value
        case ast.Constant(value=float() as value):
            return value if math.isfinite(value) else None
        case ast.UnaryOp(op=ast.UAdd() | ast.USub() as operator, operand=operand):
            value = _number(operand)
            return None if value is None else -value if isinstance(operator, ast.USub) else value
        case _:
            return None


def _empty_interval(kind: str, bounds: dict[str, int | float]) -> bool:
    lowers = [_Bound(value, name == "gt") for name, value in bounds.items() if name in {"gt", "ge", "min_length"}]
    uppers = [_Bound(value, name == "lt") for name, value in bounds.items() if name in {"lt", "le", "max_length"}]
    if not lowers or not uppers:
        return False
    lower = max(lowers, key=lambda bound: (bound.value, bound.exclusive))
    upper = min(uppers, key=lambda bound: (bound.value, not bound.exclusive))
    if kind != "float":
        return lower.value + int(lower.exclusive) > upper.value - int(upper.exclusive)
    return lower.value > upper.value or (lower.value == upper.value and (lower.exclusive or upper.exclusive))
