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
_HEADER = "from pydantic import BaseModel\nclass CacheEntry(BaseModel):\n"


@final
class PreferSemanticTemporalTypes(ProjectRule):
    id = "prefer-semantic-temporal-types"
    code = "SARJ573"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use temporal types for model instants and durations with explicit units.",
        rationale="Primitive model numbers erase whether a value is an instant or an elapsed duration and allow accidental mixing of seconds and milliseconds.",
        remediation="Represent instants with datetime, or Pydantic AwareDatetime when timezone awareness is required; represent durations and TTLs with timedelta. Convert explicit epoch units at serialization and storage boundaries while preserving the wire contract.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This warning uses an explicitly requested naming heuristic only within import-proven dataclass/BaseModel/BaseSettings fields: a temporal role token plus an explicit numeric unit suffix. Names are evidence for review, not proof of the domain. Settings bases require stable native pydantic_settings or pydantic.v1 provider identity; rebound names, mutated modules, generic shadows and unknown class decorators are excluded.",
            "Created/updated/expires and timestamp instants receive datetime advice; duration/TTL/timeout values receive timedelta advice. Ambiguous or conflicting role names, bare names without units, signed sentinel defaults, plain function annotations, metadata and generated files are excluded.",
            "Only primitive int/float annotations, including transparent Optional/Annotated forms, are inspected. Existing temporal/domain types are preserved. Epoch integers required by external protocols need an explained local exception or conversion at the boundary; no automatic fix changes accepted values, timezone semantics or JSON representation.",
            "When selected together, this temporal advice supersedes the generic SARJ530 numeric-domain warning at the same field. Exact-code suppressions retain the generic warning when temporal advice is suppressed.",
        ),
        examples=(
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
        if not any(
            isinstance(field.target, ast.Name) and _temporal_kind(field.target.id) is not None
            for field in context.nodes(ast.AnnAssign)
        ):
            return []
        contracts = DeclaredContracts(context)
        facts = AnnotationOrigins(context)
        findings: list[Diagnostic] = []
        for model in _temporal_models(context.tree, contracts):
            for field in contracts.model_fields(model).values():
                kind = _field_temporal_kind(field, context, facts)
                if kind is None or context.suppressions.is_suppressed(field.lineno, self.code):
                    continue
                findings.append(_temporal_diagnostic(field, kind, context, self.code))
        return findings


def _temporal_models(tree: ast.Module, contracts: DeclaredContracts) -> Iterator[DeclaredClass]:
    if contracts.unit is None:
        return
    for declaration in tree.body:
        if not isinstance(declaration, ast.ClassDef):
            continue
        model = DeclaredClass(contracts.unit, declaration)
        if value_model(model, contracts, include_settings=True):
            yield model


def _field_temporal_kind(field: ast.AnnAssign, context: PythonFileContext, facts: AnnotationOrigins) -> str | None:
    if not isinstance(field.target, ast.Name) or (kind := _temporal_kind(field.target.id)) is None:
        return None
    members = context.annotation_semantics.transparent_members(field.annotation)
    numeric = any(
        isinstance(member, ast.Name)
        and member.id in {"int", "float"}
        and facts.builtin(member, member.id, field.annotation)
        for member in members
    )
    return kind if numeric and not _negative_default(field.value) else None


def _temporal_diagnostic(field: ast.AnnAssign, kind: str, context: PythonFileContext, code: str) -> Diagnostic:
    preferred = (
        "datetime or Pydantic AwareDatetime for this instant" if kind == "instant" else "timedelta for this duration"
    )
    return Diagnostic(
        context.path,
        field.lineno,
        field.col_offset + 1,
        code,
        f"Use {preferred}; convert explicit epoch or duration units at the boundary and preserve serialized contracts.",
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
