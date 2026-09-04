from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_ORDINAL = re.compile(
    r"(?:^|[;(]\s*)(?P<minimum>\d{1,18})(?!\d)\s+for\s+(?:the\s+)?first(?=\s+[A-Za-z])",
    re.IGNORECASE,
)
_SENTINEL_MAPPING = re.compile(
    r"(?<![\w.])(?P<value>-?\d+|zero|negative values?|nonpositive values?)\s+"
    r"(?:means?|represents?|indicates?)\s+(?P<meaning>[^;().]+)",
    re.IGNORECASE,
)
_SENTINEL_STATE = re.compile(
    r"(?<![\w.])(?P<value>-?\d+|zero|negative values?|nonpositive values?)\s+"
    r"(?:is|are)\s+(?:an?\s+)?(?:unknown|unranked|sentinel|special|reserved)\b",
    re.IGNORECASE,
)
_ALLOWED_SENTINEL = re.compile(
    r"(?<![\w.])(?P<value>-?\d+|zero)\s+is\s+allowed\s+as\s+(?:an?\s+)?(?:sentinel|special value)\b",
    re.IGNORECASE,
)
_REJECTION_LANGUAGE = re.compile(r"\b(?:disallowed|invalid|not allowed|rejected)\b", re.IGNORECASE)
_PYDANTIC_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"})
_PYDANTIC_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields", "pydantic.v1", "pydantic.v1.fields"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.types", "pydantic.v1", "pydantic.v1.types"})
_PYDANTIC_VALIDATOR_SOURCES = frozenset(
    {
        "pydantic",
        "pydantic.class_validators",
        "pydantic.functional_validators",
        "pydantic.v1",
        "pydantic.v1.class_validators",
    }
)
_ANNOTATED_TYPES_SOURCES = frozenset({"annotated_types"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_ORDINAL_NAME_TOKENS = frozenset({"attempt", "dial", "index", "number", "ordinal", "position", "rank", "sequence"})


@final
class RequirePydanticOrdinalLowerBound(Rule):
    id = "require-pydantic-ordinal-lower-bound"
    code = "SARJ418"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A Pydantic ordinal field maps its first position to N but accepts smaller integers.",
        rationale=(
            "An unqualified `N for the first ...` mapping defines the origin of an ordinal field; matching schema "
            "metadata keeps runtime validation and generated JSON Schema aligned with that public contract."
        ),
        remediation=(
            "Use `PositiveInt` for a 1-based ordinal, `NonNegativeInt` for a 0-based ordinal, or encode the origin "
            "with `Field(ge=N)` or equivalent top-level `Annotated` metadata."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct, import-proven Pydantic BaseModel fields with a literal default and an unqualified `N for the first ...` clause at the start of a description or parenthetical clause are inspected.",
            "Descriptions that mention a smaller numeric value or explicit sentinel and exception language are skipped because the ordinal origin may not be the field minimum.",
            "Import-proven field or model validators cause conservative abstention; their bodies are not interpreted.",
            "Unknown named aliases, indirect model subclasses, nested container constraints, tests, and generated files are out of scope.",
        ),
        examples=(
            RuleExample(
                example_id="ordinal-prose-only",
                title="An unqualified ordinal origin lacks a lower bound",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from pydantic import BaseModel, Field\n\nclass CallDetail(BaseModel):\n    retry_attempt_number: int = Field(default=1, description='Which dial this call is within its retry group (1 for the first attempt).')\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="ordinal-bound-encoded",
                title="An ordinal minimum is enforced",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "api.py",
                        "from pydantic import BaseModel, Field, PositiveInt\n\nclass CallDetail(BaseModel):\n    retry_attempt_number: PositiveInt = Field(default=1, description='Which dial this call is within its retry group (1 for the first attempt).')\n",
                    ),
                ),
                focus_path=PurePosixPath("api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_test_support_path(path)
            or is_generated(path, source)
            or ("for first" not in source.lower() and "for the first" not in source.lower())
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        aliases = _annotation_aliases(tree)
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef) and _is_model(node, imports)):
            validators, validates_all = _validated_fields(cls, imports)
            if validates_all:
                continue
            class_bindings = _class_bindings(cls)
            for field in cls.body:
                if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                    continue
                if (
                    field.target.id.startswith("_")
                    or field.target.id in validators
                    or not _is_ordinal_field_name(field.target.id)
                    or _is_class_var(field.annotation, imports, aliases)
                ):
                    continue
                contract = _field_contract(field, imports, aliases, class_bindings)
                if contract is None:
                    continue
                default, description, field_calls = contract
                if not isinstance(default, int) or isinstance(default, bool) or not isinstance(description, str):
                    continue
                match = _ORDINAL.search(description)
                if (
                    match is None
                    or int(match.group("minimum")) != default
                    or _describes_smaller_exception(description, default)
                    or _lower_bound_status(field.annotation, field_calls, default, imports, aliases) is not False
                    or is_suppressed(source_lines, field.lineno, self.code)
                ):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=field.lineno,
                        col=field.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"`{field.target.id}` maps the first position to {default} but accepts smaller integers; encode the ordinal origin with `ge={default}` or an equivalent top-level integer constraint",
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _is_model(cls: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(imports.resolves(base, sources=_PYDANTIC_MODEL_SOURCES, symbol="BaseModel") for base in cls.bases)


def _annotation_aliases(tree: ast.Module) -> dict[str, ast.expr]:
    binding_counts = _module_binding_counts(tree)
    candidates: dict[str, list[ast.expr]] = {}
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value) | ast.TypeAlias(
                name=ast.Name(id=name), value=value
            ):
                candidates.setdefault(name, []).append(value)
            case _:
                pass
    return {name: values[0] for name, values in candidates.items() if len(values) == 1 and binding_counts[name] == 1}


def _module_binding_counts(tree: ast.Module) -> Counter[str]:
    counts: Counter[str] = Counter()
    stack: list[ast.AST] = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            counts[node.name] += 1
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Import | ast.ImportFrom):
            counts.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            counts[node.id] += 1
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return counts


def _class_bindings(cls: ast.ClassDef) -> frozenset[str]:
    names: set[str] = set()
    for statement in cls.body:
        match statement:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                names.add(name)
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.AugAssign(target=ast.Name(id=name)):
                names.add(name)
            case ast.Import(names=imported) | ast.ImportFrom(names=imported):
                names.update(alias.asname or alias.name.partition(".")[0] for alias in imported)
            case _:
                pass
    return frozenset(names)


def _field_contract(
    field: ast.AnnAssign,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    class_bindings: frozenset[str],
) -> tuple[object, object, tuple[ast.Call, ...]] | None:
    annotation_calls = tuple(
        metadata
        for metadata in _annotated_metadata(field.annotation, imports, aliases)
        if isinstance(metadata, ast.Call) and _is_field_call(metadata, imports, class_bindings)
    )
    assignment_call = (
        field.value
        if isinstance(field.value, ast.Call) and _is_field_call(field.value, imports, class_bindings)
        else None
    )
    calls = (*annotation_calls, *((assignment_call,) if assignment_call is not None else ()))
    if not calls:
        return None
    description = next(
        (value for call in reversed(calls) if (value := _literal_keyword(call, "description")) is not None),
        None,
    )
    if assignment_call is not None:
        default = _literal_keyword(assignment_call, "default")
        if default is None and assignment_call.args:
            default = _literal_value(assignment_call.args[0])
    else:
        default = _literal_value(field.value)
        if default is None:
            default = next(
                (value for call in reversed(calls) if (value := _literal_keyword(call, "default")) is not None),
                None,
            )
    return default, description, calls


def _is_field_call(call: ast.Call, imports: ImportIndex, class_bindings: frozenset[str]) -> bool:
    return imports.resolves(call.func, sources=_PYDANTIC_FIELD_SOURCES, symbol="Field") and not (
        (root := _root_name(call.func)) is not None and root in class_bindings
    )


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _literal_value(node: ast.expr | None) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        numeric = _numeric_value(node.operand.value)
        if numeric is not None:
            return -numeric
    return None


def _literal_keyword(call: ast.Call, name: str) -> object:
    keyword = next((item for item in call.keywords if item.arg == name), None)
    if keyword is None:
        return None
    return _literal_value(keyword.value)


def _lower_bound_status(
    annotation: ast.expr,
    field_calls: tuple[ast.Call, ...],
    minimum: int,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
) -> bool | None:
    has_ordered_constraints, ordered_status = _ordered_bound_status(annotation, field_calls, minimum, imports, aliases)
    if has_ordered_constraints:
        return ordered_status
    return _annotation_bound_status(annotation, minimum, imports, aliases, frozenset())


def _ordered_bound_status(
    annotation: ast.expr,
    field_calls: tuple[ast.Call, ...],
    minimum: int,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
) -> tuple[bool, bool | None]:
    base, annotation_calls = _top_level_constraint_calls(annotation, imports, aliases)
    ge_specified, ge_value, gt_specified, gt_value = _named_bound_seed(base, imports)
    base_has_overridable_bound = (
        ge_specified
        or gt_specified
        or (isinstance(base, ast.Call) and imports.resolves(base.func, sources=_PYDANTIC_SOURCES, symbol="conint"))
    )
    unknown_metadata = False
    for call in (*annotation_calls, *(call for call in field_calls if call not in annotation_calls)):
        updates = _bound_updates(call, imports)
        if updates is None:
            unknown_metadata = True
            continue
        call_ge_specified, call_ge, call_gt_specified, call_gt = updates
        if call_ge_specified:
            ge_specified, ge_value = True, call_ge
        if call_gt_specified:
            gt_specified, gt_value = True, call_gt
    if not ge_specified and not gt_specified:
        return False, None
    sufficient = (ge_value is not None and ge_value >= minimum) or (gt_value is not None and gt_value >= minimum - 1)
    if sufficient:
        return True, None if unknown_metadata else True
    if unknown_metadata:
        return True, None
    if (ge_specified and ge_value is None) or (gt_specified and gt_value is None):
        return True, None
    base_status = _annotation_bound_status(base, minimum, imports, aliases, frozenset())
    if base_status is True and not base_has_overridable_bound:
        return True, True
    return True, False


def _top_level_constraint_calls(
    annotation: ast.expr, imports: ImportIndex, aliases: dict[str, ast.expr]
) -> tuple[ast.expr, tuple[ast.Call, ...]]:
    annotation = _resolve_alias(annotation, aliases, frozenset())
    if isinstance(annotation, ast.Call) and imports.resolves(
        annotation.func, sources=_PYDANTIC_SOURCES, symbol="conint"
    ):
        return annotation, (annotation,)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        arguments = _subscript_arguments(annotation)
        if not arguments:
            return annotation, ()
        base, base_calls = _top_level_constraint_calls(arguments[0], imports, aliases)
        metadata_calls = tuple(item for item in arguments[1:] if isinstance(item, ast.Call))
        return base, (*base_calls, *metadata_calls)
    return annotation, ()


def _named_bound_seed(annotation: ast.expr, imports: ImportIndex) -> tuple[bool, float | None, bool, float | None]:
    if imports.resolves(annotation, sources=_PYDANTIC_SOURCES, symbol="PositiveInt"):
        return False, None, True, 0.0
    if imports.resolves(annotation, sources=_PYDANTIC_SOURCES, symbol="NonNegativeInt"):
        return True, 0.0, False, None
    return False, None, False, None


def _annotation_bound_status(
    annotation: ast.expr,
    minimum: int,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    resolving: frozenset[str],
) -> bool | None:
    if isinstance(annotation, ast.Name) and annotation.id in aliases and annotation.id not in resolving:
        return _annotation_bound_status(aliases[annotation.id], minimum, imports, aliases, resolving | {annotation.id})
    if isinstance(annotation, ast.Name) and annotation.id == "int" and imports.builtin_is_unshadowed("int"):
        return False
    if imports.resolves(annotation, sources=_PYDANTIC_SOURCES, symbol="PositiveInt"):
        return minimum <= 1
    if imports.resolves(annotation, sources=_PYDANTIC_SOURCES, symbol="NonNegativeInt"):
        return minimum <= 0
    if isinstance(annotation, ast.Call) and imports.resolves(
        annotation.func, sources=_PYDANTIC_SOURCES, symbol="conint"
    ):
        return _call_bound_status(annotation, minimum, imports)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _combined_union_status((annotation.left, annotation.right), minimum, imports, aliases, resolving)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        arguments = _subscript_arguments(annotation)
        if not arguments:
            return None
        base_status = _annotation_bound_status(arguments[0], minimum, imports, aliases, resolving)
        metadata = arguments[1:]
        metadata_statuses = tuple(
            _call_bound_status(item, minimum, imports) if isinstance(item, ast.Call) else None for item in metadata
        )
        if any(status is True for status in metadata_statuses):
            return True
        if any(status is None for status in metadata_statuses):
            return None
        if all(_is_known_constraint_metadata(item, imports) for item in metadata):
            return base_status
        return None
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Optional"
    ):
        return _effective_annotation_status(annotation.slice, minimum, imports, aliases, resolving)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Union"
    ):
        return _combined_union_status(_subscript_arguments(annotation), minimum, imports, aliases, resolving)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Literal"
    ):
        values = tuple(_literal_value(item) for item in _subscript_arguments(annotation))
        numeric_values = tuple(_numeric_value(value) for value in values)
        if values and all(value is not None for value in numeric_values):
            return all(value >= minimum for value in numeric_values if value is not None)
    return None


def _combined_union_status(
    branches: tuple[ast.expr, ...],
    minimum: int,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    resolving: frozenset[str],
) -> bool | None:
    statuses = tuple(
        _effective_annotation_status(branch, minimum, imports, aliases, resolving)
        for branch in branches
        if not _is_none_annotation(branch)
    )
    if not statuses or any(status is None for status in statuses):
        return None
    return all(statuses)


def _effective_annotation_status(
    annotation: ast.expr,
    minimum: int,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    resolving: frozenset[str],
) -> bool | None:
    has_ordered_constraints, status = _ordered_bound_status(annotation, (), minimum, imports, aliases)
    if has_ordered_constraints:
        return status
    return _annotation_bound_status(annotation, minimum, imports, aliases, resolving)


def _call_bound_status(call: ast.Call, minimum: int, imports: ImportIndex) -> bool | None:
    updates = _bound_updates(call, imports)
    if updates is None:
        return None
    ge_specified, ge_value, gt_specified, gt_value = updates
    if not ge_specified and not gt_specified:
        return False
    if (ge_specified and ge_value is None) or (gt_specified and gt_value is None):
        return None
    return (ge_value is not None and ge_value >= minimum) or (gt_value is not None and gt_value >= minimum - 1)


def _bound_updates(call: ast.Call, imports: ImportIndex) -> tuple[bool, float | None, bool, float | None] | None:
    is_keyword_constraint = any(
        imports.resolves(call.func, sources=sources, symbol=symbol)
        for sources, symbol in (
            (_PYDANTIC_FIELD_SOURCES, "Field"),
            (_PYDANTIC_SOURCES, "conint"),
            (_ANNOTATED_TYPES_SOURCES, "Interval"),
        )
    )
    if any(keyword.arg is None for keyword in call.keywords):
        return True, None, True, None
    ge_keyword = next((keyword for keyword in call.keywords if keyword.arg == "ge"), None)
    gt_keyword = next((keyword for keyword in call.keywords if keyword.arg == "gt"), None)
    ge = _literal_value(ge_keyword.value) if ge_keyword is not None else None
    gt = _literal_value(gt_keyword.value) if gt_keyword is not None else None
    if imports.resolves(call.func, sources=_ANNOTATED_TYPES_SOURCES, symbol="Ge") and call.args:
        ge_keyword = call.args[0]
        ge = _literal_value(call.args[0])
    elif imports.resolves(call.func, sources=_ANNOTATED_TYPES_SOURCES, symbol="Gt") and call.args:
        gt_keyword = call.args[0]
        gt = _literal_value(call.args[0])
    elif not is_keyword_constraint:
        return None
    ge_value = _numeric_value(ge)
    gt_value = _numeric_value(gt)
    return ge_keyword is not None, ge_value, gt_keyword is not None, gt_value


def _is_known_constraint_metadata(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Call) and any(
        imports.resolves(node.func, sources=sources, symbol=symbol)
        for sources, symbol in (
            (_PYDANTIC_FIELD_SOURCES, "Field"),
            (_ANNOTATED_TYPES_SOURCES, "Ge"),
            (_ANNOTATED_TYPES_SOURCES, "Gt"),
            (_ANNOTATED_TYPES_SOURCES, "Interval"),
        )
    )


def _annotated_metadata(
    annotation: ast.expr, imports: ImportIndex, aliases: dict[str, ast.expr]
) -> tuple[ast.expr, ...]:
    resolved = _resolve_alias(annotation, aliases, frozenset())
    if not isinstance(resolved, ast.Subscript) or not imports.resolves(
        resolved.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        return ()
    return _subscript_arguments(resolved)[1:]


def _resolve_alias(annotation: ast.expr, aliases: dict[str, ast.expr], resolving: frozenset[str]) -> ast.expr:
    if isinstance(annotation, ast.Name) and annotation.id in aliases and annotation.id not in resolving:
        return _resolve_alias(aliases[annotation.id], aliases, resolving | {annotation.id})
    return annotation


def _subscript_arguments(node: ast.Subscript) -> tuple[ast.expr, ...]:
    return tuple(node.slice.elts) if isinstance(node.slice, ast.Tuple) else (node.slice,)


def _is_none_annotation(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _numeric_value(value: object) -> float | None:
    match value:
        case bool():
            return None
        case int() | float():
            return float(value)
        case _:
            return None


def _describes_smaller_exception(description: str, minimum: int) -> bool:
    matches = (
        *((match, match.group("meaning")) for match in _SENTINEL_MAPPING.finditer(description)),
        *((match, "") for match in _SENTINEL_STATE.finditer(description)),
        *((match, "") for match in _ALLOWED_SENTINEL.finditer(description)),
    )
    for match, meaning in matches:
        if _REJECTION_LANGUAGE.search(meaning) is None and _sentinel_is_smaller(match.group("value"), minimum):
            return True
    return False


def _sentinel_is_smaller(value: str, minimum: int) -> bool:
    value = value.lower()
    return minimum >= 0 if value.startswith(("negative", "nonpositive")) or value == "zero" else float(value) < minimum


def _is_ordinal_field_name(name: str) -> bool:
    return bool(_ORDINAL_NAME_TOKENS & set(name.lower().split("_")))


def _is_class_var(annotation: ast.expr, imports: ImportIndex, aliases: dict[str, ast.expr]) -> bool:
    resolved = _resolve_alias(annotation, aliases, frozenset())
    return isinstance(resolved, ast.Subscript) and imports.resolves(
        resolved.value, sources=_TYPING_SOURCES, symbol="ClassVar"
    )


def _validated_fields(cls: ast.ClassDef, imports: ImportIndex) -> tuple[frozenset[str], bool]:
    fields: set[str] = set()
    validates_all = False
    for function in cls.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if any(
                imports.resolves(decorator.func, sources=_PYDANTIC_VALIDATOR_SOURCES, symbol=symbol)
                for symbol in ("model_validator", "root_validator")
            ):
                validates_all = True
            if any(
                imports.resolves(decorator.func, sources=_PYDANTIC_VALIDATOR_SOURCES, symbol=symbol)
                for symbol in ("field_validator", "validator")
            ):
                if any(isinstance(argument, ast.Starred) for argument in decorator.args) or not all(
                    isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    for argument in decorator.args
                ):
                    validates_all = True
                    continue
                if any(argument.value == "*" for argument in decorator.args if isinstance(argument, ast.Constant)):
                    validates_all = True
                    continue
                fields.update(
                    argument.value
                    for argument in decorator.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                )
    return frozenset(fields), validates_all
