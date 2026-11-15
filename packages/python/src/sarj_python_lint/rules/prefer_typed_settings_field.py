from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, SETTINGS_BASES, DeclaredContracts
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._declared_contracts import DeclaredClass


_ENUM_BASES = frozenset({"enum.StrEnum", "enum.Enum", "enum.IntEnum"})
_FIELD_NAMES = frozenset({"pydantic.Field", "pydantic.fields.Field"})
_FIELD_VALIDATOR_ARGUMENT_COUNT = 2
_GUARD_AND_RETURN_STATEMENTS = 2
_NUMERIC_BOUNDS = frozenset({"gt", "ge", "lt", "le"})
_COUNT_TOKENS = frozenset({"count", "length", "size", "attempt", "attempts", "page", "limit"})
_FIELD_VALIDATORS = frozenset({"pydantic.field_validator", "pydantic.functional_validators.field_validator"})
_LEGACY_FIELD_VALIDATORS = frozenset({"pydantic.validator", "pydantic.class_validators.validator"})
_MODEL_VALIDATORS = frozenset(
    {
        "pydantic.model_validator",
        "pydantic.functional_validators.model_validator",
        "pydantic.root_validator",
        "pydantic.class_validators.root_validator",
    }
)
_CONSTRUCTION_OVERRIDES = frozenset(
    {"__init__", "__new__", "model_post_init", "__get_pydantic_core_schema__", "__get_validators__"}
)
_TOKEN_DEFAULT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_EXAMPLE = "from enum import StrEnum\nfrom pydantic import Field\nfrom pydantic_settings import BaseSettings\nclass Mode(StrEnum):\n    CLOUD = 'cloud'\nclass Settings(BaseSettings):\n"


@dataclass(frozen=True, slots=True)
class _FieldOptions:
    default: ast.expr | None
    options: dict[str, ast.expr]


@dataclass(frozen=True, slots=True)
class _FieldValidator:
    method: ast.FunctionDef
    decorator: ast.Call


@final
class PreferTypedSettingsField(ProjectRule):
    id = "prefer-typed-settings-field"
    code = "SARJ530"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare numeric model domains and use typed choices for token-valued defaults.",
        rationale="Bare model numbers omit their valid domain; raw token defaults hide a choice or identifier domain. A primitive annotation can also erase an enum, nominal identifier or URL contract demonstrated by its default.",
        remediation="Reuse the default's enum or NewType, use a Pydantic URL type with the accepted schemes, and prefer PositiveInt/NonNegativeInt or PositiveFloat/NonNegativeFloat for exact zero bounds. Keep units, aliases and source precedence explicit. Use SecretStr for secrets, existing domain identifiers, nested settings with default_factory, declarative bounds and pure computed properties where their contracts justify them. Validate textual environment values; do not enable blanket strict mode or change coercion, optionality or startup behavior without checking real environment inputs.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Source-proven BaseSettings and BaseModel fields are checked, including source-visible local inheritance and standard import aliases. Existing constrained types, explicit signed bounds, private attributes, model_config and ClassVar/Final metadata remain valid.",
            "Raw numeric fields request an explicit valid domain. Exact zero bounds prefer the matching standard constrained type; stronger positive bounds retain every original constraint. Count/length/size/attempt/page/limit name tokens together with an exact zero default suggest a nonnegative domain; a positive default alone never proves a strictly positive minimum. An unchanged guard-and-return synchronous after-validator with proven classmethod binding can refine that guidance only on a direct native model with no other field/model validators or class-construction/schema override; inherited or transformed contracts retain generic advice. This heuristic is warning-only and a signed domain remains a deliberate option.",
            "Nonempty short identifier-like string defaults request a StrEnum for closed choices or a nominal string type for an open vocabulary. Empty strings, prose, URL handling and existing enum/NewType contracts remain distinct. A default does not prove that every possible value is in a finite enum.",
            "Field providers and annotations use lexical scope, including generic shadowing; Optional and Annotated forms retain their original optionality. Dynamic Field keyword expansions abstain. No automatic rewrite changes coercion, aliases, environment parsing, signed sentinels, NaN/infinity or serialized contracts.",
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
            RuleExample(
                example_id="unbounded-model-measurement",
                scenario="numeric-model-domain",
                title="A measurement has no declared numeric domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass Audio(BaseModel):\n    duration_seconds: float\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="positive-model-measurement",
                scenario="numeric-model-domain",
                title="The model declares a positive measurement",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel, PositiveFloat\nclass Audio(BaseModel):\n    duration_seconds: PositiveFloat\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="raw-token-default",
                scenario="token-default-domain",
                title="A raw token default does not declare its domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    voice: str = 'voice_a'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-token-default",
                scenario="token-default-domain",
                title="A closed token default retains its enum domain",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "from enum import StrEnum\nfrom pydantic_settings import BaseSettings\nclass Voice(StrEnum):\n    MAIN = 'voice_a'\nclass Settings(BaseSettings):\n    voice: Voice = Voice.MAIN\n",
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
            if resolved is None or not contracts.inherits(resolved, MODEL_BASES | SETTINGS_BASES):
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
        if preferred is not None and not context.suppressions.is_suppressed(field.lineno, code):
            yield Diagnostic(
                context.path,
                field.lineno,
                field.col_offset + 1,
                code,
                f"Declare this model field with {preferred}; preserve aliases, optionality, environment parsing and the accepted value domain.",
                severity=Severity.WARNING,
            )


def _primitive(annotation: ast.expr, context: PythonFileContext, facts: AnnotationOrigins) -> str | None:
    parsed = context.annotation_semantics.parse(annotation)
    if isinstance(parsed, ast.Name) and facts.alias_value(parsed, annotation) is not None:
        resolved = facts.resolve_annotation(annotation)
        if resolved is not None and _numeric_alias_bound(resolved.expression, resolved.at, facts):
            return None
    primitives = [
        member.id
        for member in context.annotation_semantics.transparent_members(annotation)
        if isinstance(member, ast.Name)
        and member.id in {"str", "int", "float"}
        and facts.builtin(member, member.id, annotation)
    ]
    return primitives[0] if len(primitives) == 1 else None


def _numeric_alias_bound(annotation: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> bool:
    current = facts.context.annotation_semantics.parse(annotation)
    while (
        isinstance(current, ast.Subscript)
        and facts.qualified(current.value, at) in {"typing.Annotated", "typing_extensions.Annotated"}
        and isinstance(current.slice, ast.Tuple)
        and current.slice.elts
    ):
        base, *metadata = current.slice.elts
        if any(
            isinstance(item, ast.Call)
            and facts.qualified(item.func, at) in _FIELD_NAMES
            and any(keyword.arg in {"gt", "ge", "lt", "le"} for keyword in item.keywords)
            for item in metadata
        ):
            return True
        current = facts.context.annotation_semantics.parse(base)
    return False


def _preferred(
    field: ast.AnnAssign, primitive: str, facts: AnnotationOrigins, contracts: DeclaredContracts
) -> str | None:
    default_contract = _field_options(field, facts, contracts.context)
    if default_contract is None:
        return None
    default, options = default_contract.default, default_contract.options
    if (domain := _domain_type(default, contracts)) is not None:
        return domain
    match primitive:
        case "str":
            return _string_domain(default)
        case "int" | "float":
            return _numeric_type(primitive, options, field=field, default=default, facts=facts)
        case _:
            return None


def _field_options(field: ast.AnnAssign, facts: AnnotationOrigins, context: PythonFileContext) -> _FieldOptions | None:
    options: dict[str, ast.expr] = {}
    for call in _field_calls(field, facts, context):
        if any(keyword.arg is None for keyword in call.keywords):
            return None
        options.update({keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None})
    default = field.value
    if isinstance(default, ast.Call) and facts.qualified(default.func, default) in _FIELD_NAMES:
        default = options.get("default") or (default.args[0] if default.args else None)
    return _FieldOptions(default, options)


def _field_calls(field: ast.AnnAssign, facts: AnnotationOrigins, context: PythonFileContext) -> Iterator[ast.Call]:
    annotation = context.annotation_semantics.parse(field.annotation)
    if annotation is not None:
        for node in ast.walk(annotation):
            if isinstance(node, ast.Call) and facts.qualified(node.func, field.annotation) in _FIELD_NAMES:
                yield node
    default = field.value
    if isinstance(default, ast.Call) and facts.qualified(default.func, default) in _FIELD_NAMES:
        yield default


def _string_domain(default: ast.expr | None) -> str | None:
    if (url_type := _url_type(default)) is not None:
        return url_type
    if isinstance(default, ast.Constant) and isinstance(default.value, str) and _TOKEN_DEFAULT.fullmatch(default.value):
        return (
            "a StrEnum for a closed choice, or an explicit nominal string type for an intentionally open token domain"
        )
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


def _numeric_type(
    primitive: str,
    options: dict[str, ast.expr],
    *,
    field: ast.AnnAssign,
    default: ast.expr | None,
    facts: AnnotationOrigins,
) -> str | None:
    suffix = "Int" if primitive == "int" else "Float"
    if not _NUMERIC_BOUNDS.isdisjoint(options):
        return _bounded_numeric_type(options, suffix)
    count_domain = _count_numeric_type(field, default, facts, suffix)
    if count_domain is not None:
        return count_domain
    return f"an explicit numeric domain such as Positive{suffix} or NonNegative{suffix}, or a constrained signed type when negatives are valid"


def _numeric_literal(expression: ast.expr | None) -> int | float | None:
    if (
        isinstance(expression, ast.Constant)
        and isinstance(expression.value, int | float)
        and not isinstance(expression.value, bool)
    ):
        return expression.value
    return None


def _bounded_numeric_type(options: dict[str, ast.expr], suffix: str) -> str | None:
    for key, prefix in (("gt", "Positive"), ("ge", "NonNegative")):
        if _numeric_literal(options.get(key)) == 0 and not ({"gt", "ge"} - {key}).intersection(options):
            return prefix + suffix
    for key in ("gt", "ge"):
        bound = _numeric_literal(options.get(key))
        if bound is not None and bound > 0:
            return f"Positive{suffix} while retaining every stronger explicit bound"
    return None


def _count_numeric_type(
    field: ast.AnnAssign, default: ast.expr | None, facts: AnnotationOrigins, suffix: str
) -> str | None:
    if not isinstance(field.target, ast.Name) or _COUNT_TOKENS.isdisjoint(field.target.id.lower().split("_")):
        return None
    if (guard := _numeric_guard(field, facts)) is not None:
        return f"{guard}{suffix} while retaining the existing validator and every other constraint"
    if _numeric_literal(default) == 0:
        return f"NonNegative{suffix} when zero is valid; retain a signed domain if negative sentinels are accepted"
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


def _numeric_guard(field: ast.AnnAssign, facts: AnnotationOrigins) -> str | None:
    if not isinstance(field.target, ast.Name) or (model := _guard_model(field, facts)) is None:
        return None
    candidate = _single_native_field_validator(model, facts)
    if candidate is None:
        return None
    if not _unchanged_after_validator(candidate.method, candidate.decorator, field.target.id, facts):
        return None
    return _returned_guard_domain(candidate.method)


def _guard_model(field: ast.AnnAssign, facts: AnnotationOrigins) -> ast.ClassDef | None:
    model = facts.context.parents.get(field)
    if not isinstance(model, ast.ClassDef):
        return None
    if (
        len(model.bases) != 1
        or facts.qualified(model.bases[0], model.bases[0]) not in MODEL_BASES | SETTINGS_BASES
        or model.decorator_list
        or model.keywords
    ):
        return None
    return model


def _single_native_field_validator(model: ast.ClassDef, facts: AnnotationOrigins) -> _FieldValidator | None:
    candidates: list[_FieldValidator] = []
    for method in model.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if method.name in _CONSTRUCTION_OVERRIDES:
            return None
        decorators = _native_field_validator_calls(method, facts)
        if decorators is None:
            return None
        if isinstance(method, ast.AsyncFunctionDef):
            if decorators:
                return None
            continue
        candidates.extend(_FieldValidator(method, decorator) for decorator in decorators)
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    return candidate if facts.qualified(candidate.decorator.func, candidate.decorator) in _FIELD_VALIDATORS else None


def _native_field_validator_calls(
    method: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins
) -> list[ast.Call] | None:
    decorators: list[ast.Call] = []
    for decorator in method.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        provider = facts.qualified(decorator.func, decorator)
        if provider in _MODEL_VALIDATORS:
            return None
        if provider in _FIELD_VALIDATORS | _LEGACY_FIELD_VALIDATORS:
            decorators.append(decorator)
    return decorators


def _unchanged_after_validator(
    method: ast.FunctionDef, decorator: ast.Call, field_name: str, facts: AnnotationOrigins
) -> bool:
    targets_field = any(isinstance(arg, ast.Constant) and arg.value == field_name for arg in decorator.args)
    after_mode = all(
        keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "after"
        for keyword in decorator.keywords
    )
    identity_decorators = all(
        node is decorator or facts.builtin(node, "classmethod", node) for node in method.decorator_list
    )
    return targets_field and after_mode and identity_decorators and _native_classmethod_binding(method, facts)


def _native_classmethod_binding(method: ast.FunctionDef, facts: AnnotationOrigins) -> bool:
    if any(facts.builtin(node, "classmethod", node) for node in method.decorator_list):
        return True
    args = [*method.args.posonlyargs, *method.args.args]
    return bool(args) and args[0].arg == "cls"


def _returned_guard_domain(method: ast.FunctionDef) -> str | None:
    args = [*method.args.posonlyargs, *method.args.args]
    if len(args) != _FIELD_VALIDATOR_ARGUMENT_COUNT or len(method.body) != _GUARD_AND_RETURN_STATEMENTS:
        return None
    statement, returned = method.body
    if (
        not isinstance(returned, ast.Return)
        or not isinstance(returned.value, ast.Name)
        or returned.value.id != args[1].arg
    ):
        return None
    comparison = _raising_comparison(statement)
    return _zero_guard_domain(comparison, args[1].arg) if comparison is not None else None


def _raising_comparison(statement: ast.stmt) -> ast.Compare | None:
    if (
        not isinstance(statement, ast.If)
        or statement.orelse
        or len(statement.body) != 1
        or not isinstance(statement.body[0], ast.Raise)
        or statement.body[0].exc is None
    ):
        return None
    test = statement.test
    return test if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1 else None


def _zero_guard_domain(comparison: ast.Compare, value_name: str) -> str | None:
    if (
        not isinstance(comparison.left, ast.Name)
        or comparison.left.id != value_name
        or _numeric_literal(comparison.comparators[0]) != 0
    ):
        return None
    if isinstance(comparison.ops[0], ast.Lt):
        return "NonNegative"
    if isinstance(comparison.ops[0], ast.LtE):
        return "Positive"
    return None
