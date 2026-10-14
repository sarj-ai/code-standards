from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_FIELD_MODULES: Final = frozenset({"pydantic", "pydantic.fields"})
_SCHEMA_MODULES: Final = frozenset({"pydantic.json_schema"})
_MESSAGE = (
    "Field(exclude=True) drops the field from serialization but not from the JSON schema, so generated OpenAPI, "
    "TypeScript and Zod clients still offer it as a settable property. Wrap the annotation in SkipJsonSchema[...] "
    "or use a private attribute."
)


@final
class ExcludedFieldSkipsJsonSchema(Rule):
    id = "excluded-field-skips-json-schema"
    code = "SARJ501"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A Pydantic field with exclude=True is also hidden from the JSON schema with SkipJsonSchema.",
        rationale=(
            "Pydantic's `exclude=True` only affects serialization. The field stays in the model's JSON schema, so "
            "a server-computed value ships as a settable request property in generated clients."
        ),
        remediation="Annotate the field as `SkipJsonSchema[T]` or replace it with a `PrivateAttr`.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Class-body annotated fields whose `Field(...)` resolves to Pydantic and sets literal `exclude=True` are checked.",
            "Any `SkipJsonSchema` from `pydantic.json_schema` in the field annotation is accepted.",
            (
                "Whether the model reaches an OpenAPI schema is not provable per file, so models used only internally "
                "are also reported. Tests and generated files are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="schema-visible",
                title="An excluded field still appears in the schema",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "from pydantic import BaseModel, Field\n\n\nclass Task(BaseModel):\n"
                        "    name: str\n    owner_id: str | None = Field(default=None, exclude=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="schema-skipped",
                title="The excluded field is skipped in the schema",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "models.py",
                        "from pydantic import BaseModel, Field\nfrom pydantic.json_schema import SkipJsonSchema\n\n\n"
                        "class Task(BaseModel):\n    name: str\n"
                        "    owner_id: SkipJsonSchema[str | None] = Field(default=None, exclude=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if "exclude" not in context.symbol_source:
            return []
        imports = context.imports
        reported: set[int] = set()
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not _is_excluding_field(call, imports):
                continue
            field = _class_field(call, context.parents)
            if field is None or id(field) in reported or _skips_schema(field.annotation, imports):
                continue
            reported.add(id(field))
            diagnostics.append(
                Diagnostic(
                    context.path, field.lineno, field.col_offset + 1, self.code, _MESSAGE, severity=Severity.WARNING
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _is_excluding_field(call: ast.Call, imports: ImportIndex) -> bool:
    if imports.resolved_symbol(call.func, sources=_FIELD_MODULES) != "Field":
        return False
    return any(
        keyword.arg == "exclude" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )


def _class_field(call: ast.Call, parents: Mapping[ast.AST, ast.AST]) -> ast.AnnAssign | None:
    current = parents.get(call)
    while current is not None and not isinstance(current, (ast.stmt, ast.Lambda)):
        current = parents.get(current)
    if isinstance(current, ast.AnnAssign) and isinstance(parents.get(current), ast.ClassDef):
        return current
    return None


def _skips_schema(annotation: ast.expr, imports: ImportIndex) -> bool:
    return any(
        imports.resolved_symbol(node, sources=_SCHEMA_MODULES) == "SkipJsonSchema"
        for node in ast.walk(annotation)
        if isinstance(node, (ast.Name, ast.Attribute))
    )
