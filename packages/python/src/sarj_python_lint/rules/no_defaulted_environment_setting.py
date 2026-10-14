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
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_SETTINGS_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_ENVIRONMENT = "environment"
_ALIAS_KEYWORDS = frozenset({"alias", "validation_alias"})
_DEFAULT_KEYWORDS = frozenset({"default", "default_factory"})


@final
class NoDefaultedEnvironmentSetting(Rule):
    id = "no-defaulted-environment-setting"
    code = "SARJ497"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A settings field that names the deployment environment must not declare a default.",
        rationale=(
            "A defaulted environment setting lets a deployment that forgot the variable start as the default "
            "environment, so it quietly behaves like local or development code and can share state with another stack."
        ),
        remediation=(
            'Declare the field without a default, for example `environment: Environment = Field(alias="ENVIRONMENT")`, '
            "so a missing value fails at startup."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only classes deriving from pydantic-settings BaseSettings directly or through a class in the same file are checked.",
            "A field qualifies when its name or literal alias is `environment` in any letter case.",
            "Other environment-isolating settings, such as resource-name prefixes, have no stable name and are not checked.",
        ),
        examples=(
            RuleExample(
                example_id="defaulted-environment",
                title="A defaulted environment pretends to be local",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service/settings.py",
                        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n\n"
                        "class Settings(BaseSettings):\n"
                        "    environment: str = Field(default='local', alias='ENVIRONMENT')\n",
                    ),
                ),
                focus_path=PurePosixPath("service/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="required-environment",
                title="A required environment fails at startup when missing",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service/settings.py",
                        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n\n"
                        "class Settings(BaseSettings):\n"
                        "    environment: str = Field(alias='ENVIRONMENT')\n",
                    ),
                ),
                focus_path=PurePosixPath("service/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated or "BaseSettings" not in context.symbol_source:
            return []
        imports = context.imports
        settings_classes: set[str] = set()
        diagnostics: list[Diagnostic] = []
        for model in tree.body:
            if not isinstance(model, ast.ClassDef) or not _is_settings_class(model, settings_classes, imports):
                continue
            settings_classes.add(model.name)
            diagnostics.extend(
                Diagnostic(
                    context.path,
                    field.lineno,
                    field.col_offset + 1,
                    self.code,
                    "This environment setting has a default, so a deployment missing the variable starts as that "
                    "environment. Remove the default so startup fails instead.",
                    severity=Severity.WARNING,
                )
                for field in model.body
                if isinstance(field, ast.AnnAssign) and _is_defaulted_environment(field, imports)
            )
        return diagnostics


def _is_settings_class(model: ast.ClassDef, known: set[str], imports: ImportIndex) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id in known)
        or imports.resolves(base, sources=_SETTINGS_SOURCES, symbol="BaseSettings")
        for base in model.bases
    )


def _is_defaulted_environment(field: ast.AnnAssign, imports: ImportIndex) -> bool:
    if not isinstance(field.target, ast.Name) or field.value is None:
        return False
    value = field.value
    if not (isinstance(value, ast.Call) and imports.resolves(value.func, sources=_FIELD_SOURCES, symbol="Field")):
        return _is_environment_name(field.target.id, None)
    alias = next(
        (
            keyword.value.value
            for keyword in value.keywords
            if keyword.arg in _ALIAS_KEYWORDS
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ),
        None,
    )
    if not _is_environment_name(field.target.id, alias):
        return False
    positional_default = bool(value.args) and not (
        isinstance(value.args[0], ast.Constant) and value.args[0].value is Ellipsis
    )
    return positional_default or any(keyword.arg in _DEFAULT_KEYWORDS for keyword in value.keywords)


def _is_environment_name(name: str, alias: str | None) -> bool:
    return name.lower() == _ENVIRONMENT or (alias is not None and alias.lower() == _ENVIRONMENT)
