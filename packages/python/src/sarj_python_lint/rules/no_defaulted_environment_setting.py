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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._pydantic_field_contract import model_namespace_hazards, required_default_sentinel


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SETTINGS_BASES = frozenset({"pydantic_settings.BaseSettings", "pydantic_settings.main.BaseSettings"})
_FIELD_PROVIDERS = frozenset({"pydantic.Field", "pydantic.fields.Field"})
_ANNOTATED = frozenset({"typing.Annotated", "typing_extensions.Annotated"})
_METADATA_WRAPPERS = frozenset(
    {"typing.ClassVar", "typing_extensions.ClassVar", "typing.Final", "typing_extensions.Final"}
)
_NATIVE_PROVIDERS = (
    _SETTINGS_BASES
    | _FIELD_PROVIDERS
    | _ANNOTATED
    | _METADATA_WRAPPERS
    | {"typing.TypeAlias", "typing_extensions.TypeAlias"}
)
_MAX_METADATA_DEPTH = 16
_MAX_METADATA_FIELDS = 64
_ENVIRONMENT = "environment"


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
            "Source-proven Annotated Field metadata and assignment defaults are merged in order; literal Ellipsis and the proven unshadowed bare builtin Ellipsis are equivalent required markers. Field Ellipsis retains an earlier default, bare Ellipsis resets it and default_factory=None clears an earlier factory. Only literal input aliases are followed; private fields, model_config, ClassVar/Final metadata and opaque Annotated metadata are excluded. Namespace mutation/escape, ambiguous imports and bounded metadata overflow abstain.",
        ),
        examples=(
            RuleExample(
                example_id="annotated-defaulted-environment",
                scenario="annotated-environment",
                title="Annotated metadata still supplies a deployment default",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service/settings.py",
                        "from typing import Annotated\nfrom pydantic import Field\n"
                        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n"
                        "    deployment: Annotated[str, Field(default='prod', alias='ENVIRONMENT')]\n",
                    ),
                ),
                focus_path=PurePosixPath("service/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="annotated-required-environment",
                scenario="annotated-environment",
                title="Annotated metadata can leave the input required",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service/settings.py",
                        "from typing import Annotated\nfrom pydantic import Field\n"
                        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n"
                        "    deployment: Annotated[str, Field(alias='ENVIRONMENT')]\n",
                    ),
                ),
                focus_path=PurePosixPath("service/settings.py"),
                expected_count=0,
                public=True,
            ),
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
        if model_namespace_hazards(context, include_settings=True, escape_symbols=_NATIVE_PROVIDERS):
            return []
        facts = AnnotationOrigins(context)
        settings_classes: set[ast.ClassDef] = set()
        diagnostics: list[Diagnostic] = []
        for model in tree.body:
            if not isinstance(model, ast.ClassDef) or not _is_settings_class(model, settings_classes, facts):
                continue
            settings_classes.add(model)
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
                if isinstance(field, ast.AnnAssign) and _is_defaulted_environment(field, facts)
            )
        return diagnostics


def _is_settings_class(model: ast.ClassDef, known: set[ast.ClassDef], facts: AnnotationOrigins) -> bool:
    return any(
        facts.qualified(base, base) in _SETTINGS_BASES
        or (isinstance(base, ast.Name) and facts.provenance.binding(base.id, base) in known)
        for base in model.bases
    )


def _is_defaulted_environment(field: ast.AnnAssign, facts: AnnotationOrigins) -> bool:
    if not isinstance(field.target, ast.Name) or field.target.id.startswith("_") or field.target.id == "model_config":
        return False
    options = _field_options(field, facts)
    if options is None:
        return False
    alias = options.get("validation_alias")
    if not _is_environment_name(
        field.target.id, alias.value if isinstance(alias, ast.Constant) and isinstance(alias.value, str) else None
    ):
        return False
    factory = options.get("default_factory")
    if factory is not None and not _is_none(factory):
        return True
    default = options.get("default")
    return default is not None and not _is_none(default)


def _field_options(field: ast.AnnAssign, facts: AnnotationOrigins) -> dict[str, ast.expr] | None:
    calls = _annotated_fields(field.annotation, facts)
    if calls is None:
        return None
    bare_default = field.value
    if isinstance(bare_default, ast.Call) and facts.qualified(bare_default.func, bare_default) in _FIELD_PROVIDERS:
        calls.append((bare_default, bare_default))
        bare_default = None
    options: dict[str, ast.expr] = {}
    for call, at in calls:
        if not _merge_field_options(call, at, options, facts):
            return None
    if bare_default is not None:
        if required_default_sentinel(bare_default, facts.context):
            options.pop("default", None)
        else:
            options["default"] = bare_default
    return options


def _merge_field_options(call: ast.Call, at: ast.expr, options: dict[str, ast.expr], facts: AnnotationOrigins) -> bool:
    if (
        len(call.args) > 1
        or any(keyword.arg is None for keyword in call.keywords)
        or any(isinstance(argument, ast.Starred) for argument in call.args)
    ):
        return False
    supplied = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
    default = supplied.get("default", call.args[0] if call.args else None)
    if default is not None and not required_default_sentinel(default, facts.context, at=at):
        options["default"] = default
    if "default_factory" in supplied:
        options["default_factory"] = supplied["default_factory"]
    if "alias" in supplied:
        options["validation_alias"] = supplied["alias"]
    validation_alias = supplied.get("validation_alias")
    # Field maps None to its own alias; without one, the earlier input alias remains.
    if validation_alias is not None and not _is_none(validation_alias):
        options["validation_alias"] = validation_alias
    return True


def _annotated_fields(annotation: ast.expr, facts: AnnotationOrigins) -> list[tuple[ast.Call, ast.expr]] | None:
    layers = _annotated_layers(annotation, facts)
    if layers is None:
        return None
    calls: list[tuple[ast.Call, ast.expr]] = []
    for metadata, at in reversed(layers):
        for value in metadata:
            if (
                not isinstance(value, ast.Call)
                or facts.qualified(value.func, at) not in _FIELD_PROVIDERS
                or len(calls) >= _MAX_METADATA_FIELDS
            ):
                return None
            calls.append((value, at))
    return calls


def _annotated_layers(annotation: ast.expr, facts: AnnotationOrigins) -> list[tuple[list[ast.expr], ast.expr]] | None:
    layers: list[tuple[list[ast.expr], ast.expr]] = []
    current = at = annotation
    for _ in range(_MAX_METADATA_DEPTH):
        resolved = facts.resolve_annotation(current, at=at)
        if resolved is None:
            return None
        current, at = resolved.expression, resolved.at
        if not isinstance(current, ast.Subscript):
            return layers
        wrapper = facts.qualified(current.value, at)
        if wrapper in _METADATA_WRAPPERS:
            return None
        if wrapper not in _ANNOTATED:
            return layers
        members = current.slice.elts if isinstance(current.slice, ast.Tuple) else [current.slice]
        if not members[1:]:
            return None
        layers.append((members[1:], at))
        current = members[0]
    return None


def _is_environment_name(name: str, alias: str | None) -> bool:
    return name.lower() == _ENVIRONMENT or (alias is not None and alias.lower() == _ENVIRONMENT)


def _is_none(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and value.value is None
