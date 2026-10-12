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
from sarj_python_lint.rules._pydantic_field_contract import direct_models, has_alias_validation_options, unique_members


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CONFIG_SOURCES = frozenset({"pydantic", "pydantic.config"})
_FLAGS = frozenset({"validate_by_alias", "validate_by_name"})
_PROJECT = '[project]\nname="example"\nversion="0.1"\ndependencies=["pydantic>=2.11"]\n'


@final
class NoConflictingPydanticAliasValidation(Rule):
    id = "no-conflicting-pydantic-alias-validation"
    code = "SARJ493"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Pydantic alias configuration must retain a validation path.",
        rationale="Explicitly disabling validation by both alias and field name prevents model construction.",
        remediation="Enable validation by alias, by field name, or both; disabling alias alone retains Pydantic's name fallback.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Requires a project dependency whose Pydantic lower bound is at least 2.11.",
            "Only plain direct module-level BaseModel subclasses and literal model_config declarations are inspected.",
            "Class keywords, duplicate keys, config mutation, unpacking, unknown factories and generated source are excluded.",
            "Visible namespace APIs, dynamic module access, ambiguous imports and escaped or mutated imported objects exclude the file.",
        ),
        examples=(
            RuleExample(
                example_id="disabled-paths",
                title="Both validation paths are explicitly disabled",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, ConfigDict\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n",
                    ),
                    ExampleFile(PurePosixPath("pyproject.toml"), _PROJECT),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="name-fallback",
                title="Disabling alias alone retains name validation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, ConfigDict\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False)\n",
                    ),
                    ExampleFile(PurePosixPath("pyproject.toml"), _PROJECT),
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
        if not all(flag in context.symbol_source for flag in _FLAGS):
            return []
        models = direct_models(context)
        if not models or not has_alias_validation_options(context):
            return []
        diagnostics: list[Diagnostic] = []
        for model in models:
            if "model_config" not in unique_members(model):
                continue
            for member in model.body:
                value = _config_value(member)
                options = _literal_options(value, context)
                if options is None or not all(_is_false(options.get(flag)) for flag in _FLAGS):
                    continue
                if is_suppressed(context.source_lines, member.lineno, self.code):
                    continue
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        member.lineno,
                        member.col_offset + 1,
                        self.code,
                        "Both validate_by_alias and validate_by_name are False. Enable at least one validation path.",
                        severity=Severity.ERROR,
                    )
                )
        return diagnostics


def _config_value(node: ast.stmt) -> ast.expr | None:
    match node:
        case (
            ast.Assign(targets=[ast.Name(id="model_config")], value=value)
            | ast.AnnAssign(target=ast.Name(id="model_config"), value=value)
        ):
            return value
        case _:
            return None


def _literal_options(node: ast.expr | None, context: PythonFileContext) -> dict[str, ast.expr] | None:
    pairs: list[tuple[str, ast.expr]] = []
    match node:
        case ast.Call(func=func, args=[], keywords=keywords) if context.imports.resolves(
            func, sources=_CONFIG_SOURCES, symbol="ConfigDict"
        ):
            for keyword in keywords:
                if keyword.arg is None:
                    return None
                pairs.append((keyword.arg, keyword.value))
        case ast.Dict(keys=keys, values=values):
            for key, value in zip(keys, values, strict=True):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    return None
                pairs.append((key.value, value))
        case _:
            return None
    if len({name for name, _value in pairs}) != len(pairs):
        return None
    return dict(pairs)


def _is_false(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is False
