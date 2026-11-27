from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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

_UNITS = frozenset(
    {"ms", "milliseconds", "us", "microseconds", "ns", "nanoseconds", "s", "seconds", "minutes", "hours"}
)
_INSTANTS = frozenset({"created", "updated", "expires", "expired", "deleted", "received", "sent", "timestamp"})
_DURATIONS = frozenset({"ttl", "duration", "timeout", "elapsed", "delay", "interval", "latency"})
_NUMERIC_TYPES = frozenset({"int", "float"})
_STRING_TYPE = frozenset({"str"})
_STRING_INSTANT_SUFFIXES = ("_at", "_timestamp")
_HEADER = "from pydantic import BaseModel\nclass CacheEntry(BaseModel):\n"
_SUMMARY = "Use semantic types for temporal fields and function boundaries."


@final
class PreferSemanticTemporalTypes(ProjectRule):
    id = "prefer-semantic-temporal-types"
    code = "SARJ573"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary=_SUMMARY,
        rationale="Primitive numbers erase the distinction between instants and durations and allow accidental mixing of units. Strings leave Pydantic instant fields unparsed.",
        remediation="Represent instants with datetime, or Pydantic AwareDatetime when timezone awareness is required. Represent durations and TTLs with timedelta. Convert explicit units at boundaries and preserve the serialized contract.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Numeric annotations require both a temporal role token and an explicit unit suffix. The rule checks parameters, return annotations using the function name, and annotated fields of import-proven dataclasses, Pydantic models and settings, TypedDicts, and NamedTuples.",
            "String fields ending in _at or _timestamp receive ISO datetime advice only on import-proven Pydantic models and settings. Names identify candidates for review. The rule supports transparent Optional and Annotated forms and excludes class metadata, generated files, and signed numeric defaults.",
            "Convert numeric or ISO datetime values at external boundaries or use an explained local exception where the primitive is required. The warning has no autofix because a change can affect accepted values, timezone semantics, or JSON representation.",
            "When selected together, this temporal advice supersedes the generic SARJ530 numeric-domain warning at the same field. Exact-code suppressions retain the generic warning when temporal advice is suppressed.",
        ),
        examples=(
            RuleExample(
                example_id="primitive-temporal-boundaries",
                scenario="temporal-boundaries",
                title="A model instant and a function timeout use primitives",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        _HEADER + "    queued_at: str\n\ndef flush(timeout_seconds: float | None) -> None:\n    pass\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="typed-temporal-boundaries",
                scenario="temporal-boundaries",
                title="A model instant and a function timeout retain their types",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from datetime import timedelta\nfrom pydantic import AwareDatetime, BaseModel\nclass CacheEntry(BaseModel):\n    queued_at: AwareDatetime\n\ndef flush(timeout: timedelta | None) -> None:\n    pass\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="epoch-instant",
                title="An epoch instant erases its temporal type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/models.py", _HEADER + "    created_ms: int\n    ttl_seconds: float = 60\n"),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="typed-temporal-values",
                title="Instants and durations retain distinct types",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from datetime import timedelta\nfrom pydantic import BaseModel, AwareDatetime\nclass CacheEntry(BaseModel):\n    created_at: AwareDatetime\n    ttl: timedelta\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="numeric-settings-instant",
                scenario="settings-provider",
                title="A native settings model retains an epoch integer",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "import pydantic_settings as ps\nclass Settings(ps.BaseSettings):\n    created_ms: int\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-settings-instant",
                scenario="settings-provider",
                title="The native settings model declares an aware instant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "import pydantic_settings as ps\nfrom pydantic import AwareDatetime\nclass Settings(ps.BaseSettings):\n    created_at: AwareDatetime\n",
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
        functions = _function_temporal_annotations(context)
        has_field_candidates = any(
            isinstance(field.target, ast.Name)
            and (_temporal_kind(field.target.id) is not None or _string_instant_name(field.target.id))
            for field in context.nodes(ast.AnnAssign)
        )
        if not functions and not has_field_candidates:
            return []
        facts = AnnotationOrigins(context)
        findings = [
            _temporal_diagnostic(annotation, kind, context, self.code)
            for annotation, kind in functions.items()
            if not context.suppressions.is_suppressed(annotation.lineno, self.code)
            and _annotation_uses_builtin(annotation, _NUMERIC_TYPES, facts)
        ]
        if has_field_candidates:
            findings.extend(_field_findings(context.tree, facts, self.code))
        return findings


def _function_temporal_annotations(context: PythonFileContext) -> dict[ast.expr, str]:
    annotations: dict[ast.expr, str] = {}
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        for parameter, default in _parameter_defaults(function.args).items():
            if (
                parameter.annotation is not None
                and (kind := _temporal_kind(parameter.arg)) is not None
                and not _negative_default(default)
            ):
                annotations[parameter.annotation] = kind
        if function.returns is not None and (kind := _temporal_kind(function.name)) is not None:
            annotations[function.returns] = kind
    return annotations


def _parameter_defaults(arguments: ast.arguments) -> dict[ast.arg, ast.expr | None]:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    defaults.extend(arguments.defaults)
    defaults_by_parameter = dict(zip(positional, defaults, strict=True))
    if arguments.vararg is not None:
        defaults_by_parameter[arguments.vararg] = None
    defaults_by_parameter.update(zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True))
    if arguments.kwarg is not None:
        defaults_by_parameter[arguments.kwarg] = None
    return defaults_by_parameter


def _field_findings(tree: ast.Module, facts: AnnotationOrigins, code: str) -> Iterator[Diagnostic]:
    context = facts.context
    contracts = DeclaredContracts(context)
    for model in _temporal_models(tree, contracts):
        for field in contracts.model_fields(model).values():
            if context.suppressions.is_suppressed(field.lineno, code):
                continue
            kind = _field_temporal_kind(field, facts)
            if kind is None:
                continue
            if kind == "string-instant" and not value_model(
                model, contracts, include_settings=True, include_dataclasses=False
            ):
                continue
            yield _temporal_diagnostic(field, kind, context, code)


def _temporal_models(tree: ast.Module, contracts: DeclaredContracts) -> Iterator[DeclaredClass]:
    if contracts.unit is None:
        return
    for declaration in tree.body:
        if not isinstance(declaration, ast.ClassDef):
            continue
        model = DeclaredClass(contracts.unit, declaration)
        if value_model(model, contracts, include_settings=True, include_typing_records=True):
            yield model


def _field_temporal_kind(field: ast.AnnAssign, facts: AnnotationOrigins) -> str | None:
    if not isinstance(field.target, ast.Name):
        return None
    name = field.target.id
    if (kind := _temporal_kind(name)) is not None:
        if not _negative_default(field.value) and _annotation_uses_builtin(field.annotation, _NUMERIC_TYPES, facts):
            return kind
    elif _string_instant_name(name) and _annotation_uses_builtin(field.annotation, _STRING_TYPE, facts):
        return "string-instant"
    return None


def _string_instant_name(name: str) -> bool:
    return name.lower().endswith(_STRING_INSTANT_SUFFIXES)


def _annotation_uses_builtin(annotation: ast.expr, names: frozenset[str], facts: AnnotationOrigins) -> bool:
    return any(
        isinstance(member, ast.Name) and member.id in names and facts.builtin(member, member.id, annotation)
        for member in facts.context.annotation_semantics.transparent_members(annotation)
    )


def _temporal_diagnostic(
    node: ast.AnnAssign | ast.expr, kind: str, context: PythonFileContext, code: str
) -> Diagnostic:
    if kind == "string-instant":
        message = "Use datetime or Pydantic AwareDatetime for this ISO datetime field. Preserve the accepted string format at the serialization boundary."
    else:
        preferred = (
            "datetime or Pydantic AwareDatetime for this instant"
            if kind == "instant"
            else "timedelta for this duration"
        )
        message = f"Use {preferred}; convert explicit epoch or duration units at the boundary and preserve serialized contracts."
    return Diagnostic(
        context.path,
        node.lineno,
        node.col_offset + 1,
        code,
        message,
        severity=Severity.WARNING,
    )


def _temporal_kind(name: str) -> str | None:
    tokens = name.lower().split("_")
    if not tokens or tokens[-1] not in _UNITS:
        return None
    instant = not _INSTANTS.isdisjoint(tokens[:-1])
    duration = not _DURATIONS.isdisjoint(tokens[:-1])
    if instant == duration:
        return None
    return "instant" if instant else "duration"


def _negative_default(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Call):
        defaults = [keyword.value for keyword in value.keywords if keyword.arg == "default"]
        value = defaults[0] if defaults else (value.args[0] if value.args else None)
    return (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, ast.USub)
        and isinstance(value.operand, ast.Constant)
        and type(value.operand.value) in {int, float}
    )
