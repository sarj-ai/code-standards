"""SARJ418 enforces a lower bound promised by an ordinal Pydantic field.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_require_pydantic_ordinal_lower_bound.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_ORDINAL = re.compile(r"\b(?P<minimum>\d+)\s+for\s+(?:the\s+)?first\b", re.IGNORECASE)


@final
class RequirePydanticOrdinalLowerBound(Rule):
    id = "require-pydantic-ordinal-lower-bound"
    code = "SARJ418"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Encode a documented Pydantic ordinal minimum as a runtime lower bound.",
        rationale="A prose-only minimum weakens validation and generated JSON Schema relative to the documented contract.",
        remediation="Use a constrained integer type or matching `Field(ge=...)` metadata.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The default and the `N for the first ...` description phrase must both be literal and equal.",
            "Names and defaults alone never imply a range.",
        ),
        examples=(
            RuleExample(
                example_id="ordinal-prose-only",
                title="An ordinal minimum exists only in prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "class Detail(BaseModel):\n    retry_attempt_number: int = Field(default=1, description='1 for the first attempt')\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="ordinal-bound-encoded",
                title="An ordinal minimum is enforced",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "class Detail(BaseModel):\n    retry_attempt_number: int = Field(default=1, ge=1, description='1 for the first attempt')\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and _is_model(node)):
            validators = _validated_fields(cls)
            for field in cls.body:
                if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                    continue
                call = field.value
                if not isinstance(call, ast.Call) or _tail(call.func) != "Field" or field.target.id in validators:
                    continue
                default = _literal_keyword(call, "default")
                description = _literal_keyword(call, "description")
                if not isinstance(default, int) or isinstance(default, bool) or not isinstance(description, str):
                    continue
                match = _ORDINAL.search(description)
                if (
                    match is None
                    or int(match.group("minimum")) != default
                    or _has_lower_bound(field.annotation, call, default)
                ):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=field.lineno,
                        col=field.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"`{field.target.id}` documents minimum {default} but does not enforce it; add `ge={default}` or an equivalent constrained integer type",
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _is_model(cls: ast.ClassDef) -> bool:
    return any(_tail(base).endswith("BaseModel") for base in cls.bases)


def _literal_keyword(call: ast.Call, name: str) -> object:
    keyword = next((item for item in call.keywords if item.arg == name), None)
    if keyword is None:
        return None
    return keyword.value.value if isinstance(keyword.value, ast.Constant) else None


def _has_lower_bound(annotation: ast.expr, call: ast.Call, minimum: int) -> bool:
    names = {_tail(node) for node in ast.walk(annotation) if isinstance(node, (ast.Name, ast.Attribute))}
    if minimum == 1 and "PositiveInt" in names:
        return True
    if minimum == 0 and ("NonNegativeInt" in names or "PositiveInt" in names):
        return True
    for candidate in [call, *[node for node in ast.walk(annotation) if isinstance(node, ast.Call)]]:
        ge = _literal_keyword(candidate, "ge")
        gt = _literal_keyword(candidate, "gt")
        if isinstance(ge, int) and ge >= minimum:
            return True
        if isinstance(gt, int) and gt >= minimum - 1:
            return True
    return False


def _validated_fields(cls: ast.ClassDef) -> frozenset[str]:
    fields: set[str] = set()
    for function in cls.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if isinstance(decorator, ast.Call) and _tail(decorator.func) == "field_validator":
                fields.update(
                    argument.value
                    for argument in decorator.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                )
    return frozenset(fields)


def _tail(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Subscript(value=value):
            return _tail(value)
        case _:
            return ""
