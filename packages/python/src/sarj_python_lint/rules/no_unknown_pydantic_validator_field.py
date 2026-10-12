from __future__ import annotations

import ast
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
from sarj_python_lint.rules._pydantic_field_contract import DECORATOR_SOURCES, direct_models, unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_FIELD_DECORATORS = frozenset({"field_validator", "field_serializer"})
_DESCRIPTOR_STACK_SIZE = 2


@final
class NoUnknownPydanticValidatorField(Rule):
    id = "no-unknown-pydantic-validator-field"
    code = "SARJ492"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Pydantic field decorators must target declared fields.",
        rationale="A field validator or serializer naming a missing field prevents the model from being constructed.",
        remediation="Use the declared field name, or explicitly set check_fields=False for a validator intended for subclass fields.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct module-level BaseModel subclasses with a static namespace and resolved field decorators are inspected.",
            "Unknown inheritance, computed fields, custom decorators, overwritten methods, wildcard fields and uncertain check_fields are excluded.",
            "Visible namespace APIs, dynamic module access, ambiguous imports and escaped or mutated imported objects exclude the file.",
            "One diagnostic is emitted per decorator even if several field targets are missing.",
        ),
        examples=(
            RuleExample(
                example_id="missing-field",
                title="Decorator targets a field the model does not declare",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\nclass Model(BaseModel):\n    value: int\n    @field_validator('missing')\n    @classmethod\n    def check(cls, value: int) -> int: return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-field",
                title="Decorator names the declared field",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\nclass Model(BaseModel):\n    value: int\n    @field_validator('value')\n    @classmethod\n    def check(cls, value: int) -> int: return value\n",
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
        if not any(name in context.symbol_source for name in _FIELD_DECORATORS):
            return []
        diagnostics: list[Diagnostic] = []
        for model in direct_models(context, methods=True):
            for decorator, missing in _missing_decorators(model, context):
                if is_suppressed(context.source_lines, decorator.lineno, self.code):
                    continue
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        decorator.lineno,
                        decorator.col_offset + 1,
                        self.code,
                        f"This field decorator targets undeclared fields: {', '.join(sorted(missing))}. Correct the field name or explicitly defer field checks.",
                        severity=Severity.ERROR,
                    )
                )
        return diagnostics


def _missing_decorators(model: ast.ClassDef, context: PythonFileContext) -> list[tuple[ast.expr, frozenset[str]]]:
    methods = [node for node in model.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if any(not _known_stack(method, context) for method in methods):
        return []
    fields = frozenset(
        node.target.id for node in model.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    )
    unique = unique_members(model)
    result: list[tuple[ast.expr, frozenset[str]]] = []
    for method in methods:
        if method.name not in unique or not method.decorator_list:
            continue
        decorator = method.decorator_list[0]
        targets = _field_targets(decorator, context)
        if targets is not None and (missing := targets - fields):
            result.append((decorator, missing))
    return result


def _known_stack(method: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    decorators = method.decorator_list
    if not decorators:
        return True
    outer = decorators[0]
    if (
        not isinstance(outer, ast.Call)
        or context.imports.resolved_symbol(outer.func, sources=DECORATOR_SOURCES) not in _FIELD_DECORATORS
    ):
        return False
    if len(decorators) == 1:
        return True
    if len(decorators) != _DESCRIPTOR_STACK_SIZE:
        return False
    inner = decorators[1]
    return (
        isinstance(inner, ast.Name)
        and inner.id in {"classmethod", "staticmethod"}
        and context.imports.builtin_is_unshadowed(inner.id)
    )


def _field_targets(node: ast.expr, context: PythonFileContext) -> frozenset[str] | None:
    if (
        not isinstance(node, ast.Call)
        or context.imports.resolved_symbol(node.func, sources=DECORATOR_SOURCES) not in _FIELD_DECORATORS
    ):
        return None
    if any(keyword.arg is None for keyword in node.keywords):
        return None
    if any(not isinstance(keyword.value, (ast.Constant, ast.Name, ast.Attribute)) for keyword in node.keywords):
        return None
    for keyword in node.keywords:
        if keyword.arg == "check_fields" and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value in {True, None}
        ):
            return None
    targets: set[str] = set()
    for argument in node.args:
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str) or argument.value == "*":
            return None
        targets.add(argument.value)
    return frozenset(targets)
