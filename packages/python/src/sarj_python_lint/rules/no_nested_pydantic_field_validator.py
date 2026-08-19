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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.functional_validators"})


@final
class NoNestedPydanticFieldValidator(Rule):
    id = "no-nested-pydantic-field-validator"
    code = "SARJ424"
    documentation = RuleDocumentation(
        summary="Do not place an outer Pydantic model's field validator inside a nested helper class.",
        rationale=(
            "A decorator indented into a nested class registers on that class, not on the outer Pydantic model, "
            "so the declared field silently loses validation."
        ),
        remediation="Move the field-validator method into the outer model class.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct BaseModel subclasses and validators directly owned by one nested class are inspected.",
            "Nested BaseModel subclasses validating their own fields are excluded.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="validator-nested-in-config",
                title="Validator accidentally belongs to Config",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\n\n"
                        "class Settings(BaseModel):\n"
                        "    language: str\n"
                        "    class Config:\n"
                        "        extra = 'forbid'\n"
                        "        @field_validator('language')\n"
                        "        @classmethod\n"
                        "        def normalize(cls, value):\n"
                        "            return value.lower()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validator-owned-by-model",
                title="Validator belongs to the model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, field_validator\n\n"
                        "class Settings(BaseModel):\n"
                        "    language: str\n"
                        "    @field_validator('language')\n"
                        "    @classmethod\n"
                        "    def normalize(cls, value):\n"
                        "        return value.lower()\n",
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
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for outer in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_model(outer, imports):
                continue
            outer_fields = _direct_fields(outer)
            for nested in (statement for statement in outer.body if isinstance(statement, ast.ClassDef)):
                if _is_direct_model(nested, imports):
                    continue
                nested_fields = _direct_fields(nested)
                for function in (
                    statement
                    for statement in nested.body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    for decorator, fields in _field_validators(function, imports):
                        misplaced = sorted((fields & outer_fields) - nested_fields)
                        if not misplaced:
                            continue
                        diagnostics.append(
                            Diagnostic(
                                path=path,
                                line=decorator.lineno,
                                col=decorator.col_offset + 1,
                                code=self.code,
                                message=(
                                    f"Validator for outer field(s) {', '.join(f'`{name}`' for name in misplaced)} "
                                    f"is nested inside `{nested.name}`; move it to `{outer.name}`."
                                ),
                            )
                        )
        return diagnostics


def _is_direct_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return len(node.bases) == 1 and imports.resolves(
        node.bases[0], sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel"
    )


def _direct_fields(node: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not statement.target.id.startswith("_")
        and statement.target.id != "model_config"
    )


def _field_validators(
    node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex
) -> tuple[tuple[ast.Call, frozenset[str]], ...]:
    validators: list[tuple[ast.Call, frozenset[str]]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not imports.resolves(
            decorator.func, sources=_PYDANTIC_SOURCES, symbol="field_validator"
        ):
            continue
        fields = frozenset(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
        validators.append((decorator, fields))
    return tuple(validators)
