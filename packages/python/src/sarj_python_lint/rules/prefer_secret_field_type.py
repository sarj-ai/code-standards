from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._secret_names import is_secret_name
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._value_models import value_model


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferSecretFieldType(ProjectRule):
    id = "prefer-secret-field-type"
    code = "SARJ613"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use Pydantic secret types for credential fields.",
        rationale="Plain credential fields expose their values in model representations and default JSON serialization. SecretStr and SecretBytes mask those values after validation.",
        remediation="Use SecretStr for text credentials and SecretBytes for byte credentials. Use get_secret_value() at boundaries that need the raw credential and preserve any required wire format explicitly.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule uses the shared credential vocabulary on field names in source-resolved Pydantic BaseModel and BaseSettings classes. Names such as page tokens and token counts are excluded. Naming can still match public values, hashes, or references that should retain their original type.",
            "Only annotated instance fields declared directly in module-level models are inspected. Inherited fields are reported at their declaration. Dataclasses, function parameters, generated files, and already typed credentials are excluded.",
            "Masking covers validated values. Settings classes can also use hide_input_in_errors to mask raw inputs on validation errors.",
        ),
        examples=(
            RuleExample(
                example_id="plaintext-model-credential",
                title="A model exposes its access token",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass GoogleTokenResponse(BaseModel):\n    access_token: str\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="masked-settings-credential",
                title="A settings field masks its credential",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from pydantic import SecretStr\nfrom pydantic_settings import BaseSettings\n"
                        "class CloudflareSettings(BaseSettings):\n    api_token: SecretStr\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated:
            return []
        secret_names = {
            field.target.id
            for field in context.nodes(ast.AnnAssign)
            if isinstance(field.target, ast.Name) and is_secret_name(field.target.id)
        }
        if not secret_names:
            return []
        contracts = DeclaredContracts(context)
        origins = AnnotationOrigins(context)
        findings: list[Diagnostic] = []
        for model in _pydantic_models(tree, contracts):
            for name, field in contracts.model_fields(model).items():
                if name not in secret_names or context.suppressions.is_suppressed(field.lineno, self.code):
                    continue
                preferred = _secret_type(field, origins)
                if preferred is not None:
                    findings.append(
                        Diagnostic(
                            context.path,
                            field.lineno,
                            field.col_offset + 1,
                            self.code,
                            f"Use Pydantic {preferred} for {name} to mask the validated credential by default.",
                            severity=Severity.WARNING,
                        )
                    )
        return findings


def _pydantic_models(tree: ast.Module, contracts: DeclaredContracts) -> Iterator[DeclaredClass]:
    unit = contracts.unit
    if unit is None:
        return
    for declaration in tree.body:
        if not isinstance(declaration, ast.ClassDef) or not declaration.bases:
            continue
        model = DeclaredClass(unit, declaration)
        if value_model(model, contracts, include_settings=True, include_dataclasses=False):
            yield model


def _secret_type(field: ast.AnnAssign, origins: AnnotationOrigins) -> str | None:
    members = tuple(
        member
        for member in origins.context.annotation_semantics.transparent_members(field.annotation)
        if not (isinstance(member, ast.Constant) and member.value is None)
    )
    match members:
        case (ast.Name(id=("str" | "bytes") as carrier) as member,) if origins.builtin(
            member, carrier, field.annotation
        ):
            return "SecretStr" if carrier == "str" else "SecretBytes"
        case _:
            return None
