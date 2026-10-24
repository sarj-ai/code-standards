from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override
from urllib.parse import urlsplit

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
from sarj_python_lint.rules._annotation_semantics import module_rebindings
from sarj_python_lint.rules._declared_contracts import SETTINGS_BASES, DeclaredContracts
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._declared_contracts import DeclaredClass


_ENUM_BASES = frozenset({"enum.StrEnum", "enum.Enum", "enum.IntEnum"})
_EXAMPLE = "from enum import StrEnum\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nclass Mode(StrEnum):\n    CLOUD = 'cloud'\nclass Settings(BaseSettings):\n"


@final
class PreferTypedSettingsField(ProjectRule):
    id = "prefer-typed-settings-field"
    code = "SARJ530"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare settings fields with the domain types already demonstrated by their defaults.",
        rationale="A primitive annotation can accept values outside an enum, nominal identifier or URL contract already demonstrated by its default. Repeated lower-bound metadata can also hide a standard validated type.",
        remediation="Reuse the default's enum or NewType, use a Pydantic URL type with the accepted schemes, and prefer PositiveInt/NonNegativeInt or PositiveFloat/NonNegativeFloat for exact zero bounds. Keep units, aliases and source precedence explicit. Use SecretStr for secrets, existing domain identifiers, nested settings with default_factory, declarative bounds and pure computed properties where their contracts justify them. Validate textual environment values; do not enable blanket strict mode or change coercion, optionality or startup behavior without checking real environment inputs.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only source-proven BaseSettings classes and raw str/int/float fields are checked. Evidence comes from an enum or stable NewType default, an absolute HTTP/HTTPS/WS/WSS URL default or exact Field(gt=0)/Field(ge=0) metadata. Field names alone never imply credentials, IDs, ports, paths or allowed choices. Existing constrained/optional domain types remain valid. Field types and Field providers use their lexical scope, including generic parameter shadowing. Private attributes, model_config and ClassVar type wrappers are excluded; Final annotations are conservatively excluded as well. URL and numeric changes require review; SDK conversion, required None defaults, NaN/infinity and environment source parsing need explicit tests. No automatic rewrite.",
        ),
        examples=(
            RuleExample(
                example_id="enum-default-erased",
                title="A primitive annotation erases an enum default",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py", _EXAMPLE + "    mode: str = Field(default=Mode.CLOUD, alias='MODE')\n"
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="enum-field-preserved",
                title="The field retains its domain type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py", _EXAMPLE + "    mode: Mode = Field(default=Mode.CLOUD, alias='MODE')\n"
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
        if context.tree is None or context.generated:
            return []
        contracts = DeclaredContracts(context)
        facts: AnnotationOrigins | None = None
        findings: list[Diagnostic] = []
        for model in context.tree.body:
            if not isinstance(model, ast.ClassDef):
                continue
            resolved = contracts.class_type(ast.Name(id=model.name))
            if resolved is None or not contracts.inherits(resolved, SETTINGS_BASES):
                continue
            if facts is None:
                facts = AnnotationOrigins(context)
            findings.extend(_settings_fields(resolved, context, contracts, facts, self.code))
        return findings


def _settings_fields(
    model: DeclaredClass, context: PythonFileContext, contracts: DeclaredContracts, facts: AnnotationOrigins, code: str
) -> Iterator[Diagnostic]:
    for field in contracts.model_fields(model).values():
        primitive = _primitive(field.annotation, context, facts)
        if primitive is None:
            continue
        preferred = _preferred(field, primitive, facts, contracts)
        if preferred is not None:
            yield Diagnostic(
                context.path,
                field.lineno,
                field.col_offset + 1,
                code,
                f"Declare this settings field with {preferred}; preserve aliases, optionality, environment parsing and the accepted value domain.",
                severity=Severity.WARNING,
            )


def _primitive(annotation: ast.expr, context: PythonFileContext, facts: AnnotationOrigins) -> str | None:
    primitives = [
        member.id
        for member in context.annotation_semantics.transparent_members(annotation)
        if isinstance(member, ast.Name)
        and member.id in {"str", "int", "float"}
        and facts.builtin(member, member.id, annotation)
    ]
    return primitives[0] if len(primitives) == 1 else None


def _preferred(
    field: ast.AnnAssign, primitive: str, facts: AnnotationOrigins, contracts: DeclaredContracts
) -> str | None:
    default = field.value
    options: dict[str, ast.expr] = {}
    if isinstance(default, ast.Call) and facts.qualified(default.func, default) in {
        "pydantic.Field",
        "pydantic.fields.Field",
    }:
        options = {keyword.arg: keyword.value for keyword in default.keywords if keyword.arg is not None}
        default = options.get("default") or (default.args[0] if default.args else None)
    if (domain := _domain_type(default, contracts)) is not None:
        return domain
    if primitive == "str":
        return _url_type(default)
    if primitive in {"int", "float"}:
        return _numeric_type(primitive, options)
    return None


def _domain_type(default: ast.expr | None, contracts: DeclaredContracts) -> str | None:
    if (
        isinstance(default, ast.Attribute)
        and (enum := contracts.class_type(default.value)) is not None
        and contracts.inherits(enum, _ENUM_BASES)
    ):
        return f"{enum.declaration.name} when it covers all allowed values, or a nominal identifier type for an open vocabulary"
    if isinstance(default, ast.Call) and (nominal := _nominal(default.func, contracts)) is not None:
        return nominal
    return None


def _url_type(default: ast.expr | None) -> str | None:
    if not isinstance(default, ast.Constant) or not isinstance(default.value, str):
        return None
    try:
        url = urlsplit(default.value)
    except ValueError:
        return None
    if url.scheme in {"http", "https", "ws", "wss"} and url.netloc:
        return "a Pydantic URL type with the required scheme constraints"
    return None


def _numeric_type(primitive: str, options: dict[str, ast.expr]) -> str | None:
    for key, prefix in (("gt", "Positive"), ("ge", "NonNegative")):
        bound = options.get(key)
        if (
            isinstance(bound, ast.Constant)
            and type(bound.value) in {int, float}
            and bound.value == 0
            and not ({"gt", "ge"} - {key}).intersection(options)
        ):
            return prefix + ("Int" if primitive == "int" else "Float")
    return None


def _nominal(expression: ast.expr, contracts: DeclaredContracts) -> str | None:
    if contracts.unit is None:
        return None
    symbol = contracts.project.resolve(contracts.unit, expression)
    unit = contracts.project.source_unit(symbol.module) if symbol is not None else None
    if unit is None or unit.tree is None or symbol is None or symbol.name in module_rebindings(unit.tree):
        return None
    imports = ImportIndex.from_tree(unit.tree, module_scope_only=True)
    for node in unit.tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if (
            isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == symbol.name
            and isinstance(node.value, ast.Call)
            and imports.resolves(node.value.func, sources=frozenset({"typing", "typing_extensions"}), symbol="NewType")
        ):
            return symbol.name
    return None
