from __future__ import annotations

import ast
import copy
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
from sarj_python_lint.rules._pydantic_field_contract import DECORATOR_SOURCES


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MATCH_SOURCE = (
    "from pydantic import BaseModel, field_validator\n\n"
    "class Contact(BaseModel):\n"
    "    first_name: str\n"
    "    last_name: str\n\n"
    "    @field_validator('first_name', mode='before')\n"
    "    @classmethod\n"
    "    def strip_first(cls, value: str) -> str:\n"
    "        return value.strip()\n\n"
    "    @field_validator('last_name', mode='before')\n"
    "    @classmethod\n"
    "    def strip_last(cls, raw: str) -> str:\n"
    "        return raw.strip()\n"
)
_NO_MATCH_SOURCE = (
    "from pydantic import BaseModel, field_validator\n\n"
    "class Contact(BaseModel):\n"
    "    first_name: str\n"
    "    last_name: str\n\n"
    "    @field_validator('first_name', 'last_name', mode='before')\n"
    "    @classmethod\n"
    "    def strip_names(cls, value: str) -> str:\n"
    "        return value.strip()\n"
)


@final
class NoDuplicateFieldValidatorBody(Rule):
    id = "no-duplicate-field-validator-body"
    code = "SARJ496"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Pydantic field validators in one model repeat the same body.",
        rationale=(
            "Two field validators with the same mode and the same body are one validation rule written twice; "
            "a later fix to one copy silently leaves the other field validated by the old rule."
        ),
        remediation=(
            "List every field in one `@field_validator(...)` decorator and branch on `info.field_name` "
            "where the fields genuinely differ."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only methods decorated with an import-proven Pydantic `field_validator` in the same class body are compared.",
            "Bodies must match structurally after renaming parameters by position and dropping a leading docstring.",
            "Validators with different `mode` arguments, different decorator stacks, or near-identical bodies are not reported.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-strip-validators",
                title="Two validators repeat one strip rule",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("models/contact.py", _MATCH_SOURCE),),
                focus_path=PurePosixPath("models/contact.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="one-multi-field-validator",
                title="One validator names every field that shares the rule",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("models/contact.py", _NO_MATCH_SOURCE),),
                focus_path=PurePosixPath("models/contact.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "field_validator" not in context.symbol_source or context.tree is None or context.generated:
            return []
        diagnostics: list[Diagnostic] = []
        for model in context.nodes(ast.ClassDef):
            seen: dict[str, str] = {}
            for method in model.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                key = _validator_key(method, context)
                if key is None:
                    continue
                first = seen.get(key)
                if first is None:
                    seen[key] = method.name
                    continue
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        method.lineno,
                        method.col_offset + 1,
                        self.code,
                        f"Field validator `{method.name}` repeats the body of `{first}`. List both fields in one "
                        "field_validator and branch on info.field_name where they differ.",
                        severity=Severity.WARNING,
                    )
                )
        return diagnostics


def _validator_key(method: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> str | None:
    decorators = method.decorator_list
    if not decorators:
        return None
    outer = decorators[0]
    if (
        not isinstance(outer, ast.Call)
        or context.imports.resolved_symbol(outer.func, sources=DECORATOR_SOURCES) != "field_validator"
    ):
        return None
    keywords = sorted(ast.dump(keyword) for keyword in outer.keywords)
    stack = [ast.dump(decorator) for decorator in decorators[1:]]
    body = _normalized_body(method)
    if not body:
        return None
    return repr((type(method).__name__, keywords, stack, body))


def _normalized_body(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    statements = list(method.body)
    if (
        statements
        and isinstance(first := statements[0], ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        statements = statements[1:]
    if not statements:
        return ""
    parameters = [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]
    renames = {parameter.arg: f"__parameter_{index}" for index, parameter in enumerate(parameters)}
    module = ast.Module(body=[copy.deepcopy(statement) for statement in statements], type_ignores=[])
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and node.id in renames:
            node.id = renames[node.id]
    return ast.dump(module, annotate_fields=False)
